"""Station review round: live stream sends each frame once, idle camera stops decoding,
internet visitors can't use the AI / inspect / download, Git LFS placeholders aren't models,
board serials are stored and searchable, and scan alerts (Telegram / webhook)."""
import asyncio
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core.access import needs_lease, request_origin
from app.core.model_catalog import discover_models
from app.core.security import lease_manager
from app.main import app
from app.services import notify_service as ns
from app.services.camera_service import CameraService


def req(headers=None, peer="127.0.0.1"):
    scope = {"type": "http", "method": "GET", "path": "/", "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
             "client": (peer, 1234), "query_string": b""}
    return Request(scope)


class StreamTests(unittest.TestCase):
    def test_each_frame_is_sent_once(self):
        cam = CameraService()
        cam._running = True
        cam._latest_jpeg, cam._latest_timestamp = b"A", 1.0

        async def run():
            g = cam.generate_mjpeg_stream(max_fps=500, client="c")
            first = await anext(g)
            self.assertIn(b"A", first)
            # Same frame: nothing is sent until a new one arrives.
            task = asyncio.ensure_future(anext(g))
            await asyncio.sleep(0.05)
            self.assertFalse(task.done())
            cam._latest_jpeg, cam._latest_timestamp = b"B", 2.0
            self.assertIn(b"B", await asyncio.wait_for(task, 1))
            await g.aclose()

        asyncio.run(run())


class IdleCameraTests(unittest.TestCase):
    def test_idle_camera_grabs_without_decoding(self):
        cam = CameraService()
        cap = MagicMock()
        cap.isOpened.return_value = True
        frame = np.zeros((40, 60, 3), np.uint8)
        cap.read.return_value = (True, frame)
        cap.retrieve.return_value = (True, frame)
        cap.grab.return_value = True
        cam._running, cam._generation = True, 1
        cam._demand = time.monotonic() - 60  # nobody asked for frames for a minute
        calls = {"n": 0}

        def stop_after(*_a):
            calls["n"] += 1
            if calls["n"] > 200:
                cam._running = False
            return True

        cap.grab.side_effect = stop_after
        cam._capture_frames(1, cap, False)
        self.assertGreater(cap.grab.call_count, 150)
        self.assertLessEqual(cap.retrieve.call_count, 2)  # one decode per IDLE_DECODE_SEC
        self.assertEqual(cap.read.call_count, 0)

    def test_asking_for_a_frame_wakes_it(self):
        cam = CameraService()
        cam._running = True
        cam._demand = time.monotonic() - 60
        self.assertTrue(cam._idle(time.monotonic()))
        cam._latest_frame, cam._latest_timestamp = np.zeros((4, 4, 3), np.uint8), 1.0
        with patch.object(CameraService, "_wake", wraps=cam._wake):
            cam.get_latest_frame(raw=True)
        self.assertFalse(cam._idle(time.monotonic()))


class AccessTests(unittest.TestCase):
    def test_origins(self):
        self.assertEqual(request_origin(req({"x-forwarded-host": "192.168.1.47:3001"})), "local")
        self.assertEqual(request_origin(req({"x-forwarded-host": "localhost:3001"})), "local")
        self.assertEqual(request_origin(req({}, peer="192.168.1.42")), "local")
        # Tailnet user through Serve: identity header, tailnet address.
        self.assertEqual(request_origin(req({"x-forwarded-host": "box.tail0.ts.net", "x-forwarded-for": "100.98.1.2",
                                             "tailscale-user-login": "me@example.com"})), "local")
        # Funnel: public address, or no identity, or the explicit header.
        self.assertEqual(request_origin(req({"x-forwarded-host": "box.tail0.ts.net", "x-forwarded-for": "8.8.4.4"})), "internet")
        self.assertEqual(request_origin(req({"x-forwarded-host": "box.tail0.ts.net"})), "internet")
        self.assertEqual(request_origin(req({"tailscale-funnel-request": "?1", "x-forwarded-host": "192.168.1.47"})), "internet")
        # A forged private address in front of the real one does not hide the public hop.
        self.assertEqual(request_origin(req({"x-forwarded-for": "10.0.0.1, 1.1.1.1"})), "internet")

    def test_guarded_paths(self):
        self.assertTrue(needs_lease("POST", "/api/chat/agent"))
        self.assertTrue(needs_lease("POST", "/api/inspection/ocr"))
        self.assertTrue(needs_lease("GET", "/api/boards/ps_1/export"))
        self.assertTrue(needs_lease("GET", "/api/history/export/csv"))
        self.assertFalse(needs_lease("GET", "/api/chat/status"))
        self.assertFalse(needs_lease("GET", "/api/history/runs"))
        self.assertFalse(needs_lease("POST", "/api/aoi/stop"))  # STOP stays open to everyone

    def test_internet_visitor_needs_the_password(self):
        client = TestClient(app)
        funnel = {"x-forwarded-for": "8.8.4.4", "x-forwarded-host": "box.tail0.ts.net"}
        r = client.post("/api/inspection/ocr", json={"image_url": "x", "box": [0, 0, 1, 1]}, headers=funnel)
        self.assertEqual(r.status_code, 403)
        self.assertIn("รหัสสถานี", r.json()["detail"])
        self.assertEqual(client.get("/api/history/export/csv", headers=funnel).status_code, 403)
        self.assertEqual(client.get("/api/history/runs", headers=funnel).status_code, 200)  # looking is fine
        self.assertEqual(client.get("/api/auth/origin", headers=funnel).json()["origin"], "internet")
        ok, token, _ = lease_manager.acquire_lease("remote owner", "8.8.4.4", force=True)
        try:
            self.assertEqual(client.get(f"/api/history/export/csv?operator_token={token}", headers=funnel).status_code, 200)
        finally:
            lease_manager.release_lease(token)
        # Locally nothing changes.
        self.assertEqual(client.get("/api/history/export/csv").status_code, 200)


class ModelCatalogTests(unittest.TestCase):
    def test_lfs_pointers_are_listed_as_unusable(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            Path(d, "real.pt").write_bytes(b"\x80" * 4096)
            Path(d, "pointer.pt").write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 42\n")
            Path(d, "empty.pt").write_bytes(b"")
            models = {Path(m["path"]).name: m for m in discover_models([Path(d)])}
        self.assertIsNone(models["real.pt"]["unusable"])
        self.assertIn("Git LFS", models["pointer.pt"]["unusable"])
        self.assertEqual(models["empty.pt"]["unusable"], "ไฟล์ว่าง")


class SerialTests(unittest.TestCase):
    def test_serial_is_stored_and_searchable(self):
        from app.core.schemas import AOIRunReport, ScanPlanRequest
        from app.services.storage_service import storage_service

        stamp = int(time.time() * 1000)
        plan = ScanPlanRequest(serial=f"SN-{stamp}", board_name="Astron A")
        report = AOIRunReport(id=f"aoi_serial_{stamp}", plan=plan, status="complete", overall_verdict="PASS")
        storage_service.create_run(report)
        client = TestClient(app)
        rows = client.get("/api/history/runs", params={"q": f"SN-{stamp}"}).json()
        self.assertEqual(rows["total"], 1)
        self.assertEqual(rows["runs"][0]["serial"], f"SN-{stamp}")
        self.assertEqual(rows["runs"][0]["board_name"], "Astron A")
        self.assertEqual(client.get("/api/history/runs", params={"q": "no-such-serial-xyz"}).json()["total"], 0)
        self.assertIn(f"SN-{stamp}", client.get("/api/history/export/csv").text)


def fake_report(verdict="FAIL", status="complete", sim=False):
    comp = [{"expected": {"id": "P2", "name": "resistor"}, "status": "missing"}]
    result = SimpleNamespace(verdict="FAIL", name="จุด 2", point_index=1, reason=None, component_eval=comp, annotated_path="/nope.jpg")
    return SimpleNamespace(
        id="aoi_x", status=status, overall_verdict=verdict, is_golden_scan=False, is_simulation=sim,
        plan=SimpleNamespace(board_name="Astron A", serial="SN-7"), points=[1, 2, 3], results=[result] if verdict == "FAIL" else [],
        pass_count=2, fail_count=1, review_count=0, error_message="motor stalled" if status == "error" else None)


class NotifyTests(unittest.TestCase):
    def setUp(self):
        self.cfg = ns.CONFIG_FILE.with_name("notify.test.json")
        self.env = ns.CONFIG_FILE.with_name("env.test")
        self.cfg.unlink(missing_ok=True)
        self.env.unlink(missing_ok=True)
        self.p = patch.object(ns, "CONFIG_FILE", self.cfg)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.cfg.unlink(missing_ok=True)
        self.env.unlink(missing_ok=True)
        import os

        os.environ.pop(ns.TOKEN_VAR, None)
        os.environ.pop(ns.WEBHOOK_VAR, None)

    def test_fail_message_names_the_parts(self):
        msgs = ns.messages_for(fake_report(), {**ns.DEFAULTS})
        self.assertEqual(len(msgs), 1)
        self.assertIn("FAIL", msgs[0]["text"])
        self.assertIn("SN-7", msgs[0]["text"])
        self.assertIn("resistor ขาด", msgs[0]["text"])
        self.assertEqual(ns.messages_for(fake_report("PASS"), {**ns.DEFAULTS}), [])
        err = ns.messages_for(fake_report("ERROR", "error"), {**ns.DEFAULTS})
        self.assertIn("motor stalled", err[0]["text"])

    def test_streak_and_yield(self):
        data = {**ns.DEFAULTS, "fail_streak": 3, "yield_below_pct": 80, "yield_window": 5}
        self.assertTrue(any("ติดกัน 3" in (m["text"] or "") for m in ns.trend_messages(data, ["FAIL", "FAIL", "FAIL", "PASS", "PASS"])))
        self.assertFalse(ns.trend_messages({**data, "yield_below_pct": 0}, ["FAIL", "FAIL", "PASS"]))
        low = ns.trend_messages(data, ["FAIL", "PASS", "FAIL", "PASS", "PASS"])  # 60% < 80%
        self.assertTrue(any(m.get("set_alerted") for m in low))
        # Already alerted: silent until it recovers, then re-armed without a message.
        self.assertFalse([m for m in ns.trend_messages({**data, "yield_alerted": True}, ["FAIL", "PASS", "FAIL", "PASS", "PASS"]) if m.get("text")])
        back = ns.trend_messages({**data, "yield_alerted": True}, ["PASS"] * 5)
        self.assertEqual(back, [{"text": None, "set_alerted": False}])

    def test_settings_validate_and_mask(self):
        with self.assertRaises(ns.NotifyError):
            ns.update({"telegram_token": "not a token"}, env_path=self.env)
        with self.assertRaises(ns.NotifyError):
            ns.update({"telegram_chat_id": "hello world"}, env_path=self.env)
        out = ns.update({"enabled": True, "telegram_token": "123456789:" + "A" * 35, "telegram_chat_id": "-1001234567"}, env_path=self.env)
        self.assertTrue(out["enabled"] and out["telegram_token_set"])
        self.assertNotIn("A" * 35, json.dumps(out))
        self.assertIn("TELEGRAM_BOT_TOKEN=", self.env.read_text())

    def test_send_goes_to_telegram_and_webhook(self):
        ns.update({"telegram_token": "123456789:" + "B" * 35, "telegram_chat_id": "42", "webhook_url": "https://hooks.example.com/x"}, env_path=self.env)
        ok = MagicMock(status_code=200, headers={"content-type": "application/json"})
        with patch.object(ns.httpx, "post", return_value=ok) as post:
            self.assertEqual(ns.send_test(), [])
        urls = [c.args[0] for c in post.call_args_list]
        self.assertTrue(any("api.telegram.org/bot123456789" in u and u.endswith("/sendMessage") for u in urls))
        self.assertIn("https://hooks.example.com/x", urls)

    def test_nothing_configured_is_reported(self):
        self.assertTrue(ns.send_test())


if __name__ == "__main__":
    unittest.main()


class ShutdownTests(unittest.TestCase):
    def test_stop_signal_ends_live_streams_and_reaches_the_server(self):
        import signal

        from app.core import shutdown

        saved = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
        calls = []
        try:
            signal.signal(signal.SIGTERM, lambda s, f: calls.append(s))  # stands in for uvicorn
            shutdown._installed = False
            shutdown.install()
            cam = CameraService()
            cam._running = True
            cam._latest_jpeg, cam._latest_timestamp = b"A", 1.0

            async def run():
                g = cam.generate_mjpeg_stream(max_fps=200, client="c")
                await anext(g)
                signal.raise_signal(signal.SIGTERM)
                with self.assertRaises(StopAsyncIteration):
                    await asyncio.wait_for(anext(g), 1)

            asyncio.run(run())
            self.assertTrue(shutdown.shutting_down.is_set())
            self.assertEqual(calls, [signal.SIGTERM])  # uvicorn still gets its signal
        finally:
            for s, h in saved.items():
                signal.signal(s, h)
            shutdown.shutting_down.clear()
            shutdown._installed = False


class SendHistoryTests(unittest.TestCase):
    def test_history_goes_as_a_csv_file_with_the_summary(self):
        import os

        cfg = ns.CONFIG_FILE.with_name("notify.hist.json")
        env = ns.CONFIG_FILE.with_name("env.hist")
        with patch.object(ns, "CONFIG_FILE", cfg):
            try:
                ns.update({"telegram_token": "123456789:" + "C" * 35, "telegram_chat_id": "42"}, env_path=env)
                ok = MagicMock(status_code=200, headers={"content-type": "application/json"})
                with patch.object(ns.httpx, "post", return_value=ok) as post:
                    self.assertEqual(ns.send_history(), [])
                call = post.call_args
                self.assertTrue(call.args[0].endswith("/sendDocument"))
                name, content, mime = call.kwargs["files"]["document"]
                self.assertTrue(name.endswith(".csv"))
                self.assertIn(b"Run ID", content)
                self.assertIn("Yield", call.kwargs["data"]["caption"])
                # Needs the station password.
                self.assertEqual(TestClient(app).post("/api/system/notify/send-history").status_code, 403)
            finally:
                cfg.unlink(missing_ok=True)
                env.unlink(missing_ok=True)
                os.environ.pop(ns.TOKEN_VAR, None)

    def test_agent_knows_about_telegram(self):
        from app.services import agent_service

        self.assertIn("get_notifications", agent_service.TOOLS)
        self.assertIn("ส่งเข้า Telegram", agent_service.SYSTEM_PROMPT)
        self.assertIn("telegram_ready", agent_service.get_notifications())
