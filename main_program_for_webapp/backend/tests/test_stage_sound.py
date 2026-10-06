"""Stage motors as a buzzer: TONE in the protocol, capability check, tunes that never block motion."""
import time
import unittest
from unittest.mock import patch

from app.config import settings
from app.core.motion_protocol import MotionClient, SimulatedTransport
from app.services.machine_service import TUNES, machine_service


class Clock:
    def __init__(self):
        self.time = 0.0

    def __call__(self):
        return self.time


class OldFirmware(SimulatedTransport):
    """Firmware before TONE: its HELP line does not list it."""

    def write(self, data):
        if data.decode().strip() == "HELP":
            self.emit("CNC v2: HOME AUTOCAL MOVE x y speed X/Y/XY/XD/YD/XR/YR S STOP OFF ON RELEASE POS")
            return len(data)
        return super().write(data)


class ToneProtocolTests(unittest.TestCase):
    def _client(self, transport_cls=SimulatedTransport):
        clock = Clock()
        transport = transport_cls(clock)
        client = MotionClient(transport, clock)
        client.tick()
        clock.time += 0.1
        client.tick()
        return client, clock

    def test_capabilities_come_from_help_and_tone_round_trips(self):
        client, clock = self._client()
        self.assertIn("TONE", client.capabilities)
        lines = []
        client.on_event = lambda kind, data: kind == "wire" and lines.append(data)
        seq = client.command("TONE", 440, 120, 3)
        self.assertIn(f"TX  @{seq} TONE 440 120 3", lines)
        self.assertEqual(client.pending[1], "TONE")
        clock.time += 0.2
        client.tick()
        self.assertIsNone(client.pending)
        self.assertFalse(client.closed)
        self.assertFalse(client.homed)  # a tone does not need, nor give, HOME

    def test_old_firmware_is_never_sent_a_tone(self):
        client, _ = self._client(OldFirmware)
        self.assertNotIn("TONE", client.capabilities)
        with self.assertRaisesRegex(ValueError, "cannot play tones"):
            client.command("TONE", 440, 120, 3)
        self.assertFalse(client.closed)  # the link is not faulted

    def test_tone_limits(self):
        client, _ = self._client()
        for args in [(20, 100, 3), (440, 9000, 3), (440, 100, 0)]:
            with self.assertRaises(ValueError):
                client.command("TONE", *args)


class TuneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        machine_service.connect(mode="simulation")
        machine_service.home()

    @classmethod
    def tearDownClass(cls):
        machine_service.disconnect()

    def _wait_quiet(self, timeout=5):
        deadline = time.monotonic() + timeout
        while machine_service._tune_lock.locked() and time.monotonic() < deadline:
            time.sleep(0.02)

    def test_plays_in_the_background_and_motion_still_works(self):
        self._wait_quiet()
        with patch.object(settings, "stage_sound_enabled", True):
            self.assertTrue(machine_service.can_play)
            self.assertTrue(machine_service.play("test"))
            self.assertFalse(machine_service.play("done"))  # one tune at a time
            spm = machine_service.steps_per_mm
            started = time.monotonic()
            machine_service.move_to_steps(int(5 * spm), int(5 * spm))  # waits for the sounding note, then moves
            self.assertEqual(machine_service.get_state().position_mm, (5.0, 5.0))
            self.assertLess(time.monotonic() - started, 3.0)
            self._wait_quiet()
            self.assertTrue(machine_service.get_state().homed)

    def test_off_when_disabled(self):
        self._wait_quiet()
        with patch.object(settings, "stage_sound_enabled", False):
            self.assertFalse(machine_service.play("pass"))

    def test_tunes_are_short(self):
        for name, notes in TUNES.items():
            self.assertLess(sum(ms for _, ms in notes), 1000, name)


if __name__ == "__main__":
    unittest.main()
