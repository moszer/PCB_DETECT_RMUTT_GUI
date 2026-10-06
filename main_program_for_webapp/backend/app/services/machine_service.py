"""Machine service: owns Serial transport or Simulated stage with state machine."""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple
import serial
import serial.tools.list_ports

from ..config import settings
from ..core.motion_protocol import MotionClient, SimulatedTransport
from ..core.schemas import MachineState

logger = logging.getLogger("machine_service")

# Short tunes the motors buzz (frequency Hz, duration ms; 0 Hz = rest). Both motors play together.
TUNES: Dict[str, List[Tuple[int, int]]] = {
    "done": [(1760, 70)],
    "pass": [(1319, 90), (0, 40), (1760, 160)],
    "fail": [(523, 220), (0, 60), (392, 380)],
    "error": [(440, 140), (0, 60), (440, 140), (0, 60), (440, 140)],
    "test": [(1047, 120), (1319, 120), (1568, 120), (2093, 240)],
}


class MachineService:
    """Thread-safe controller for the Nano XY Stage."""

    def __init__(self, steps_per_mm: float = settings.steps_per_mm):
        self._lock = threading.RLock()
        self.steps_per_mm = steps_per_mm
        self._client: Optional[MotionClient] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._mode: Literal["simulation", "serial"] = "simulation"
        self._port: Optional[str] = None
        self._soft_limits_mm: Tuple[float, float] = (settings.soft_limit_x_mm, settings.soft_limit_y_mm)
        self._rx_log: List[str] = []
        self._last_error: Optional[str] = None
        self._last_event: Optional[str] = None
        self._move_completion_events: Dict[int, threading.Event] = {}
        self._move_completion_status: Dict[int, str] = {}
        self._state_subscribers: List[Callable[[MachineState], None]] = []
        self._last_reported_pos = (0, 0)
        self._last_reported_pending = None
        self._tune_lock = threading.Lock()

    def subscribe(self, callback: Callable[[MachineState], None]):
        self._state_subscribers.append(callback)

    def _notify(self):
        state = self.get_state()
        for sub in list(self._state_subscribers):
            try:
                sub(state)
            except Exception:
                pass

    def get_state(self) -> MachineState:
        with self._lock:
            if self._client is None or self._client.closed:
                return MachineState(
                    connected=False,
                    mode=self._mode,
                    port=self._port,
                    ready=False,
                    homed=False,
                    position_steps=(0, 0),
                    position_mm=(0.0, 0.0),
                    limits_steps=(21167, 20446),
                    soft_limits_mm=self._soft_limits_mm,
                    is_moving=False,
                    last_error=self._last_error,
                    last_event=self._last_event,
                    rx_log=list(self._rx_log[-30:])
                )

            pos_x, pos_y = self._client.position
            mm_x = round(pos_x / self.steps_per_mm, 2)
            mm_y = round(pos_y / self.steps_per_mm, 2)
            is_moving = bool(self._client.pending)

            return MachineState(
                connected=True,
                mode=self._mode,
                port=self._port,
                ready=self._client.ready,
                homed=self._client.homed,
                position_steps=self._client.position,
                position_mm=(mm_x, mm_y),
                limits_steps=self._client.limits,
                soft_limits_mm=self._soft_limits_mm,
                is_moving=is_moving,
                last_error=self._last_error,
                last_event=self._last_event,
                rx_log=list(self._rx_log[-30:])
            )

    def set_soft_limits(self, limit_x_mm: float, limit_y_mm: float):
        """Update soft limits and enforce immediately on active MotionClient."""
        with self._lock:
            if limit_x_mm <= 0 or limit_y_mm <= 0:
                raise ValueError("Soft limits must be positive numbers.")
            self._soft_limits_mm = (limit_x_mm, limit_y_mm)
            if self._client is not None and not self._client.closed:
                soft_steps = (
                    round(limit_x_mm * self.steps_per_mm),
                    round(limit_y_mm * self.steps_per_mm)
                )
                self._client.soft_limits = soft_steps
        self._notify()

    @staticmethod
    def list_ports() -> List[Dict[str, Any]]:
        """List available serial communication ports without opening them, prioritizing USB devices."""
        results = []
        for p in serial.tools.list_ports.comports():
            dev_lower = (p.device or "").lower()
            desc_lower = (p.description or "").lower()
            hwid_lower = (p.hwid or "").lower()

            is_usb = any(
                key in dev_lower or key in desc_lower or key in hwid_lower
                for key in ("usbserial", "wchusb", "usbmodem", "ttyusb", "ttyacm", "ch340", "cp210", "ftdi", "com")
            ) and not any(
                skip in dev_lower for skip in ("debug-console", "bluetooth")
            )

            results.append({
                "device": p.device,
                "description": p.description or "Serial Device",
                "hwid": p.hwid or "",
                "is_usb": is_usb,
            })

        # Sort USB ports to top
        results.sort(key=lambda x: (not x["is_usb"], x["device"]))
        return results

    def connect(
        self,
        mode: Literal["simulation", "serial"] = "simulation",
        port: Optional[str] = None,
        baud: int = 9600,
        startup_delay: float = 2.5
    ) -> bool:
        """Connect to the stage in Simulation or Serial mode."""
        with self._lock:
            if self._running:
                self.disconnect_locked()

            self._mode = mode
            self._port = port
            self._last_error = None
            self._last_event = "connecting"
            self._rx_log.clear()

            if mode == "simulation":
                logger.info("Initializing simulated stage transport.")
                transport = SimulatedTransport()
                delay = 0.0
            else:
                if not port:
                    raise ValueError("Serial port must be specified for serial mode.")
                logger.info("Opening serial port %s at %d baud...", port, baud)
                transport = serial.Serial(
                    port,
                    baud,
                    timeout=0,
                    write_timeout=0.2,
                    exclusive=True if os.name == "posix" else None
                )
                delay = startup_delay

            def on_event(kind: str, data: any):
                notify_needed = False
                with self._lock:
                    if kind == "wire":
                        self._rx_log.append(str(data))
                        if len(self._rx_log) > 100:
                            self._rx_log.pop(0)
                    elif kind == "error":
                        self._last_error = str(data)
                        for seq, evt in self._move_completion_events.items():
                            self._move_completion_status[seq] = "cancelled"
                            evt.set()
                        notify_needed = True
                    elif kind == "ready":
                        self._last_event = "ready"
                        notify_needed = True
                    elif kind == "done":
                        self._last_event = f"done_{data}"
                        notify_needed = True
                        # Mark completed
                        for seq, evt in list(self._move_completion_events.items()):
                            self._move_completion_status[seq] = "done"
                            evt.set()

                if notify_needed:
                    self._notify()

            client = MotionClient(
                transport=transport,
                startup_delay=delay,
                on_event=on_event
            )
            # Enforce soft limits
            soft_steps = (
                round(self._soft_limits_mm[0] * self.steps_per_mm),
                round(self._soft_limits_mm[1] * self.steps_per_mm)
            )
            client.soft_limits = soft_steps

            self._client = client
            self._running = True
            self._thread = threading.Thread(target=self._pump_loop, args=(client,), daemon=True, name="MotionPumpWorker")
            self._thread.start()

        wait_deadline = time.monotonic() + (0.5 if mode == "simulation" else 3.5)
        while time.monotonic() < wait_deadline:
            with self._lock:
                if self._client is not None and self._client.ready:
                    break
            time.sleep(0.05)

        self._notify()
        return True


    def disconnect(self):
        with self._lock:
            self.disconnect_locked()
        self._notify()

    def disconnect_locked(self):
        self._running = False
        if self._client is not None:
            try:
                self._client.close()
            except Exception as e:
                logger.error("Error closing client: %s", e)
            self._client = None
        for seq, evt in list(self._move_completion_events.items()):
            self._move_completion_status[seq] = "cancelled"
            evt.set()
        self._move_completion_events.clear()

    def _pump_loop(self, owned_client):
        from ..core.security import lease_manager
        was_controlled = False
        while True:
            with self._lock:
                if not self._running or self._client is not owned_client or owned_client.closed:
                    return
                
                is_controlled = lease_manager.get_lease_info().is_controlled
                # Lease check - stop motion if lease expires (transition from controlled to not controlled)
                if was_controlled and not is_controlled and owned_client.pending:
                    try:
                        owned_client.command("STOP")
                    except Exception:
                        pass
                was_controlled = is_controlled
                
                owned_client.tick()
                pos, pending = owned_client.position, bool(owned_client.pending)
                changed = pos != self._last_reported_pos or pending != self._last_reported_pending
                self._last_reported_pos, self._last_reported_pending = pos, pending
            if changed:
                self._notify()
            time.sleep(0.04)

    def home(self, timeout_sec: float = 545.0) -> bool:
        """Command machine HOME and wait for completion."""
        # Wait up to 3.5s for ready handshake if just connected
        deadline = time.monotonic() + 3.5
        while time.monotonic() < deadline:
            with self._lock:
                if self._client is not None and self._client.ready:
                    break
            time.sleep(0.05)

        self._wait_for_tone()
        evt = threading.Event()
        with self._lock:
            if not self._client or self._client.closed or not self._client.ready:
                raise ValueError("Machine is not connected or ready. Please wait for Nano startup handshake.")
            seq = self._client.command("HOME")
            self._move_completion_events[seq] = evt
            self._move_completion_status[seq] = "pending"
            if self._client.pending:
                timeout_sec = max(timeout_sec, self._client.pending[2] - time.monotonic() + 2)

        self._notify()
        finished = evt.wait(timeout_sec)
        if not finished:
            self.stop()
        with self._lock:
            status = self._move_completion_status.pop(seq, "unknown")
            self._move_completion_events.pop(seq, None)
            if not finished:
                raise TimeoutError("HOME operation timed out.")
            if status == "cancelled" or not self._client or self._client.closed:
                raise RuntimeError("Stage was disconnected or cancelled during HOME.")
            if not self._client.homed:
                raise RuntimeError("HOME operation failed: stage is not homed.")
        self._notify()
        self.play("done")
        return True

    def jog(self, dx_mm: float, dy_mm: float, speed: int = 800) -> bool:
        """Jog relative distance in mm."""
        self._wait_for_tone()
        with self._lock:
            if not self._client or not self._client.homed:
                raise ValueError("Stage must be HOMED before moving.")

            curr_x, curr_y = self._client.position
            dx_steps = round(dx_mm * self.steps_per_mm)
            dy_steps = round(dy_mm * self.steps_per_mm)
            target_x = curr_x + dx_steps
            target_y = curr_y + dy_steps

            max_x = min(self._client.limits[0], self._client.soft_limits[0])
            max_y = min(self._client.limits[1], self._client.soft_limits[1])

            if not (0 <= target_x <= max_x and 0 <= target_y <= max_y):
                raise ValueError(
                    f"Jog to ({target_x}, {target_y}) steps is outside travel limits (max: {max_x}, {max_y})."
                )

            self._client.command("MOVE", target_x, target_y, speed)

        self._notify()
        return True

    def move_to_steps(self, target_x_steps: int, target_y_steps: int, speed: int = 800, timeout_sec: float = 30.0,
                      compensate: bool = True) -> bool:
        """Move to absolute machine steps position and wait for completion.

        With backlash compensation on (settings.stage_approach_mm > 0), an axis that would arrive
        moving - first overshoots below the target and then comes up to it, so every axis always
        ends its move in +: the slack in the drive is then always on the same side.
        """
        approach = round(settings.stage_approach_mm * self.steps_per_mm) if compensate else 0
        if approach > 0:
            with self._lock:
                current = self._client.position if self._client else (target_x_steps, target_y_steps)
            pre = (
                max(0, target_x_steps - approach) if target_x_steps < current[0] else target_x_steps,
                max(0, target_y_steps - approach) if target_y_steps < current[1] else target_y_steps,
            )
            if pre != (target_x_steps, target_y_steps):
                self._move_raw(pre[0], pre[1], speed, timeout_sec)
        return self._move_raw(target_x_steps, target_y_steps, speed, timeout_sec)

    def _move_raw(self, target_x_steps: int, target_y_steps: int, speed: int, timeout_sec: float) -> bool:
        self._wait_for_tone()
        evt = threading.Event()
        with self._lock:
            if not self._client or not self._client.homed:
                raise ValueError("Stage must be HOMED before moving.")

            seq = self._client.command("MOVE", target_x_steps, target_y_steps, speed)
            self._move_completion_events[seq] = evt
            self._move_completion_status[seq] = "pending"
            if self._client.pending:
                timeout_sec = max(timeout_sec, self._client.pending[2] - time.monotonic() + 2)

        self._notify()
        finished = evt.wait(timeout_sec)
        if not finished:
            self.stop()
        with self._lock:
            status = self._move_completion_status.pop(seq, "unknown")
            self._move_completion_events.pop(seq, None)
            if not finished:
                raise TimeoutError("MOVE operation timed out.")
            if status == "cancelled" or not self._client or self._client.closed:
                raise RuntimeError("Stage was disconnected or cancelled during motion.")
            if not self._client.homed:
                raise RuntimeError("Stage lost homed status during motion.")
            if self._client.position != (target_x_steps, target_y_steps):
                raise RuntimeError(
                    f"MOVE completed at mismatched position: expected {target_x_steps, target_y_steps}, "
                    f"actual {self._client.position}."
                )
        self._notify()
        return True

    # ── sound ─────────────────────────────────────────────────────────────────
    @property
    def can_play(self) -> bool:
        with self._lock:
            return bool(self._client and not self._client.closed and self._client.ready and "TONE" in self._client.capabilities)

    def tone(self, freq: int, ms: int, motors: int = 3) -> None:
        """Buzz the motors (blocking until the tone ends). Position and HOME are kept."""
        evt = threading.Event()
        with self._lock:
            if not self._client or self._client.closed or not self._client.ready:
                raise ValueError("Machine is not connected.")
            seq = self._client.command("TONE", int(freq), int(ms), int(motors))
            self._move_completion_events[seq] = evt
            self._move_completion_status[seq] = "pending"
        evt.wait(ms / 1000 + 3)
        with self._lock:
            self._move_completion_events.pop(seq, None)
            self._move_completion_status.pop(seq, None)

    def play(self, tune: str) -> bool:
        """Play a short tune in the background when sound is on, the firmware can and the stage
        is idle (never delays or interrupts motion). Returns whether it started."""
        notes = TUNES.get(tune)
        if not notes or not settings.stage_sound_enabled or not self.can_play:
            return False
        if not self._tune_lock.acquire(blocking=False):
            return False  # one tune at a time

        def run():
            try:
                for freq, ms in notes:
                    with self._lock:
                        busy = bool(self._client and self._client.pending)
                    if busy:
                        break  # motion asked for the stage: give way
                    if freq <= 0:
                        time.sleep(ms / 1000)
                    else:
                        self.tone(freq, ms)
            except Exception:
                logger.debug("Tune %s not played", tune, exc_info=True)
            finally:
                self._tune_lock.release()

        threading.Thread(target=run, name="stage-tune", daemon=True).start()
        return True

    def _wait_for_tone(self, timeout: float = 2.0) -> None:
        """A tune note may still be sounding: motion waits for it rather than failing."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                pending = self._client.pending if self._client else None
            if not pending or pending[1] != "TONE":
                return
            time.sleep(0.01)

    def stop(self):
        """Immediately command STOP and cancel pending motions."""
        with self._lock:
            if self._client is not None and not self._client.closed:
                try:
                    self._client.command("STOP")
                except Exception:
                    pass
            for seq, evt in list(self._move_completion_events.items()):
                self._move_completion_status[seq] = "cancelled"
                evt.set()
            self._move_completion_events.clear()
            self._last_event = "stopped"
        self._notify()

    def motors_off(self):
        """Unenergize motors (requires re-homing afterward)."""
        with self._lock:
            if self._client is not None and not self._client.closed:
                self._client.command("OFF")
        self._notify()


# Global singleton
machine_service = MachineService()
