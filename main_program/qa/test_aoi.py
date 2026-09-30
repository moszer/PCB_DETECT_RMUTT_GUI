"""AOI protocol and offscreen workflow tests; no real serial/camera IO."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import sys
import tempfile
import time
import unittest
from threading import Event
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.aoi_motion import MotionClient, SimulatedTransport, raster_points
from app.aoi_dialog import AOIDialog
from app.window import DefectDetectionGUI


class Clock:
    value = 0
    def __call__(self): return self.value


class MotionTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.transport = SimulatedTransport(self.clock)
        self.client = MotionClient(self.transport, self.clock)
        self.client.tick()

    def complete(self):
        self.clock.value += .3
        self.client.tick()

    def home(self):
        self.client.command("HOME")
        self.complete()

    def test_requires_home_and_enforces_limits(self):
        with self.assertRaises(ValueError): self.client.command("MOVE", 1, 1)
        self.home()
        for args in ((-1, 0, 800), (30000, 0, 800), (0, 0, 1501)):
            with self.assertRaises(ValueError): self.client.command("MOVE", *args)
        self.client.command("MOVE", 100, 200)
        with self.assertRaises(ValueError): self.client.command("MOVE", 0, 0)
        self.complete()
        self.assertEqual(self.client.position, (100, 200))

    def test_soft_limits_enforced_in_client(self):
        self.home()
        self.client.soft_limits = (500, 600)
        self.client.command("MOVE", 500, 600)
        self.complete()
        self.assertEqual(self.client.position, (500, 600))
        with self.assertRaises(ValueError):
            self.client.command("MOVE", 501, 600)
        with self.assertRaises(ValueError):
            self.client.command("MOVE", 500, 601)

    def test_stop_preempts_and_stale_done_does_not_release(self):
        self.home()
        move_id = self.client.command("MOVE", 100, 200)
        self.client.command("STOP")
        self.client._line(f"[DONE] {move_id} 100 200 1")
        self.assertEqual(self.client.pending[1], "STOP")
        self.client.tick()
        self.assertIsNone(self.client.pending)
        self.assertEqual(self.client.position, (0, 0))

    def test_off_requires_new_home(self):
        self.home()
        self.client.command("OFF")
        self.client.tick()
        self.assertFalse(self.client.homed)
        with self.assertRaises(ValueError): self.client.command("MOVE", 0, 0)

    def test_reset_aborts_and_disconnects(self):
        self.home()
        self.client.command("MOVE", 100, 200)
        self.transport.emit("[READY] 2 0 0 21167 20446 0")
        self.client.tick()
        self.assertTrue(self.client.closed)
        self.assertTrue(any(e[0] == "error" for e in self.client.events))

    def test_wrong_completion_aborts(self):
        self.home()
        ident = self.client.command("MOVE", 100, 200)
        self.client._line(f"[DONE] {ident} 99 200 1")
        self.assertTrue(self.client.closed)

    def test_boot_banner_and_hello_reply_allowed_before_home(self):
        self.transport.emit("[READY] 2 0 0 21167 20446 0")
        self.client.tick()
        self.assertFalse(self.client.closed)
        self.assertTrue(self.client.ready)

    def test_reconnect_does_not_trust_previous_home(self):
        self.client._line("[POS] 0 0 0 1")
        self.assertFalse(self.client.homed)
        with self.assertRaises(ValueError): self.client.command("MOVE", 0, 0)

    def test_heartbeat_sent_while_idle(self):
        with patch.object(self.transport, "write", wraps=self.transport.write) as writer:
            self.clock.value += 1.1
            self.client.tick()
        self.assertNotIn(b"PING\n", [call.args[0] for call in writer.call_args_list])
        self.assertIn(b"POS\n", [call.args[0] for call in writer.call_args_list])

    def test_hardware_startup_delay_does_not_transmit_during_boot(self):
        transport = SimulatedTransport(self.clock)
        with patch.object(transport, "write", wraps=transport.write) as writer:
            client = MotionClient(transport, self.clock, startup_delay=2.5)
            self.clock.value = 2
            client.tick()
            writer.assert_not_called()
            self.clock.value = 2.6
            client.tick()
            writer.assert_called_once_with(b"HELLO\n")

    def test_unsupported_and_malformed_firmware(self):
        for line in ("[READY] 1 0 0 100 100 0", "[READY] 2 bad data", "[POS] 0 1 2 9"):
            client = MotionClient(SimulatedTransport(self.clock), self.clock)
            client._line(line)
            self.assertTrue(client.closed)

    def test_link_and_operation_timeout(self):
        self.home()
        self.transport.buffer.clear()
        self.clock.value += 7
        self.client.tick()
        self.assertTrue(self.client.closed)
        client = MotionClient(SimulatedTransport(self.clock), self.clock)
        client.tick()
        client.command("HOME")
        client.transport.job = None
        self.clock.value += 541
        client.last_rx = self.clock.value
        client.tick()
        self.assertTrue(client.closed)

    def test_raster_and_duplicate_rejection(self):
        self.assertEqual(raster_points(0, 0, 2, 2, 1, 1, 512, (1000, 1000)),
                         [(0, 0), (512, 0), (512, 512), (0, 512)])
        for args in ((0,0,2,2,0,1,512,(1000,1000)), (0,0,2,2,10,1,512,(1000,1000)),
                     (0,0,100,100,1,1,512,(100000,100000)), (float('nan'),0,1,1,1,1,512,(1000,1000))):
            with self.assertRaises(ValueError): raster_points(*args)


class Host(DefectDetectionGUI):
    def load_default_assets(self): pass
    def load_settings(self): pass
    def save_settings(self): pass


class FakeCamera:
    def __init__(self):
        self.running = True
        self.timestamp = None
    def snapshot(self):
        return (time.monotonic() if self.timestamp is None else self.timestamp,
                np.zeros((120, 160, 3), dtype=np.uint8))
    def isRunning(self): return self.running
    def requestInterruption(self): self.running = False


class FakeModel:
    def predict(self, source, **kwargs):
        import cv2
        box = SimpleNamespace(cls=[0], conf=[.9], xyxy=[np.array([20., 20., 40., 40.])])
        return [SimpleNamespace(orig_img=cv2.imread(source), boxes=[box], speed={"inference": 1})]


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.host = Host()
        self.host.main_program_root = self.tmp.name
        self.host.model = FakeModel()
        self.host.model_names = {0: "resistor"}
        self.host.current_model_path = "test-model.pt"
        self.dialog = AOIDialog(self.host)
        self.dialog.mode.setCurrentIndex(0)  # Never select real USB hardware in tests.
        self.dialog.camera = FakeCamera()
        self.dialog.settle.setValue(.2)
        self.dialog.columns.setValue(2)
        self.dialog.rows.setValue(1)
        self.dialog.connect_machine()
        self.wait(lambda: self.dialog.machine.ready)
        self.dialog.command("HOME")
        self.wait(lambda: self.dialog.machine.homed)

    def wait(self, predicate, timeout=7000):
        deadline = time.monotonic() + timeout/1000
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(25)
        self.assertTrue(predicate(), self.dialog.status.text())

    def tearDown(self):
        self.dialog.reject()
        self.wait(lambda: not self.dialog.timer.isActive())
        self.dialog.deleteLater()
        self.host.close()
        self.host.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def test_scan_without_reference_and_complete_reports(self):
        with patch("app.aoi_dialog.AOIInference.run", autospec=True) as run:
            def infer(worker):
                worker.finished.emit([{"x":30,"y":30,"label":"resistor","conf":.9,"box":[20,20,40,40]}],
                                     np.zeros((120,160,3),dtype=np.uint8), {"inference":1})
            run.side_effect = infer
            self.dialog.start_scan()
            self.wait(lambda: not self.dialog.active)
        report = json.loads((self.dialog.run_folder / "report.json").read_text())
        self.assertEqual(report["status"], "complete")
        self.assertEqual(len(report["results"]), 2)
        self.assertEqual([r["verdict"] for r in report["results"]], ["REVIEW", "REVIEW"])
        for row in report["results"]:
            self.assertTrue((self.dialog.run_folder / row["image"]).is_file())
            self.assertTrue((self.dialog.run_folder / row["annotated_image"]).is_file())

    def test_teach_then_inspect_matching_points(self):
        with patch("app.mixins.inspection_mixin.select_device", return_value=SimpleNamespace(device="cpu", label="CPU", detail="")):
            self.dialog.start_scan(True)
            self.wait(lambda: not self.dialog.active)
            self.assertIsNotNone(self.dialog.profile)
            self.dialog.start_scan(False)
            self.wait(lambda: not self.dialog.active)
        self.assertEqual(self.dialog.report["status"], "complete")
        self.assertEqual([r["verdict"] for r in self.dialog.report["results"]], ["PASS", "PASS"])

    def test_stop_during_motion_does_not_capture(self):
        self.dialog.start_scan()
        self.dialog.stop()
        QTest.qWait(500)
        self.assertEqual(self.dialog.report["status"], "aborted")
        self.assertEqual(self.dialog.report["results"], [])
        self.assertEqual(list(self.dialog.run_folder.glob("*.png")), [])

    def test_stale_frame_cannot_trigger_capture(self):
        self.dialog.start_scan()
        self.dialog.camera.timestamp = time.monotonic() - 10
        self.wait(lambda: self.dialog.phase == "settling")
        self.dialog.capture_deadline = time.monotonic() - 1
        self.wait(lambda: not self.dialog.active)
        self.assertIn("fresh camera frame", self.dialog.status.text())
        self.assertEqual(self.dialog.report["results"], [])

    def test_disk_failure_stops_before_inference(self):
        with patch("app.aoi_dialog.cv2.imwrite", return_value=False):
            self.dialog.start_scan()
            self.wait(lambda: not self.dialog.active)
        self.assertIn("save camera image", self.dialog.status.text())
        self.assertIsNone(self.dialog.inference)

    def test_out_of_bounds_cannot_start_motion(self):
        self.dialog.origin_x.setValue(500)
        self.dialog.start_scan()
        self.assertFalse(self.dialog.active)
        self.assertIsNone(self.dialog.report)

    def test_controller_reset_aborts_scan(self):
        self.dialog.start_scan()
        self.dialog.machine.transport.emit("[READY] 2 0 0 21167 20446 0")
        self.wait(lambda: not self.dialog.active)
        self.assertTrue(self.dialog.machine.closed)
        self.assertEqual(self.dialog.report["status"], "aborted")

    def test_late_inference_result_after_stop_is_ignored(self):
        self.dialog.start_scan()
        self.dialog.phase = "inference"
        self.dialog.stop()
        self.dialog._inferred([], np.zeros((120,160,3),dtype=np.uint8), {})
        self.assertEqual(self.dialog.report["results"], [])
        self.assertEqual(self.dialog.point_index, 0)

    def test_reference_mismatch_prevents_start(self):
        self.dialog.profile = {"signature": {"different": True}}
        self.dialog.start_scan()
        self.assertFalse(self.dialog.active)
        self.assertIn("Reference settings differ", self.dialog.status.text())

    def test_usb_port_selection_and_mode_do_not_open_port(self):
        ports = [SimpleNamespace(device='/dev/cu.debug-console',description='n/a',vid=None,pid=None),
                 SimpleNamespace(device='/dev/cu.usbserial-test',description='USB Serial',vid=0x1a86,pid=0x7523)]
        self.dialog.port.clear()
        self.dialog._ports_initialized = False
        with patch('serial.tools.list_ports.comports', return_value=ports), patch('serial.Serial') as opener:
            self.dialog.refresh_ports()
            self.assertEqual(self.dialog.port.currentData(), '/dev/cu.usbserial-test')
            self.assertEqual(self.dialog.mode.currentIndex(), 1)
            self.dialog.mode.setCurrentIndex(0)
            self.dialog.refresh_ports()
            self.assertEqual(self.dialog.mode.currentIndex(), 0)
            opener.assert_not_called()

    def test_inference_failure_aborts_report(self):
        with patch.object(self.host.model, "predict", side_effect=RuntimeError("test inference failure")):
            self.dialog.start_scan()
            self.wait(lambda: not self.dialog.active)
        self.assertEqual(self.dialog.report["status"], "aborted")
        self.assertEqual(self.dialog.report["results"], [])

    def test_close_waits_for_running_inference_without_advancing(self):
        entered, release = Event(), Event()
        original_predict = self.host.model.predict
        def predict(*args, **kwargs):
            entered.set()
            release.wait(5)
            return original_predict(*args, **kwargs)
        with patch.object(self.host.model, "predict", side_effect=predict):
            self.dialog.start_scan()
            try:
                self.wait(entered.is_set)
                self.dialog.reject()
                QTest.qWait(100)
                self.assertTrue(self.dialog.timer.isActive())
                self.assertFalse(self.dialog.active)
                self.assertTrue(self.dialog.machine.closed)
            finally:
                release.set()
            self.wait(lambda: not self.dialog.timer.isActive())
        self.assertEqual(self.dialog.report["results"], [])

    def test_soft_limit_restricts_scan_and_jog(self):
        self.assertAlmostEqual(self.dialog.limit_x.value(), 38.0, places=1)
        self.assertAlmostEqual(self.dialog.limit_y.value(), 38.0, places=1)

        self.dialog.limit_x.setValue(10.0)
        self.assertEqual(self.dialog.effective_limits()[0], round(10.0 * 512))

        self.dialog.origin_x.setValue(12.0)
        with self.assertRaises(ValueError):
            self.dialog.plan()

        self.dialog.origin_x.setValue(0.0)
        self.dialog.jog_step.setValue(1.0)
        self.dialog.jog(-1, 0)
        self.assertIn("blocked by soft limit", self.dialog.status.text())
        self.assertEqual(self.dialog.machine.position, (0, 0))

        self.dialog.jog(1, 0)
        self.wait(lambda: self.dialog.machine.position == (512, 0))
        self.assertEqual(self.dialog.machine.position, (512, 0))

        self.dialog.jog_step.setValue(10.0)
        self.dialog.jog(1, 0)
        self.assertIn("blocked by soft limit", self.dialog.status.text())


if __name__ == "__main__":
    unittest.main()
