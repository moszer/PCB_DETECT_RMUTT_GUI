"""Station agent: read-only tools, compact results, the tool loop, navigation and saved history."""
import asyncio
import json
import os
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.services import agent_service


class ToolTests(unittest.TestCase):
    def test_tools_are_read_only_plus_navigate(self):
        names = {d["name"] for d in agent_service.DECLARATIONS}
        self.assertEqual(names, set(agent_service.TOOLS))
        for forbidden in ("move", "jog", "home", "start", "stop", "delete", "update", "save"):
            self.assertFalse(any(forbidden in n for n in names), forbidden)

    def test_results_are_compact_and_errors_are_returned(self):
        stats = agent_service.run_tool("get_statistics", {})
        self.assertIn("board_yield_rate", stats)
        self.assertLess(len(json.dumps(agent_service.run_tool("list_scan_runs", {"limit": 50}), default=str)), 30_000)
        self.assertIn("error", agent_service.run_tool("get_scan_run", {"run_id": "nope"}))
        self.assertFalse(agent_service.run_tool("navigate", {"page": "nowhere"})["ok"])
        from app.config import settings

        dumped = json.dumps(agent_service.run_tool("get_settings", {}))
        self.assertNotIn("operator_passcode", dumped)
        self.assertNotIn(settings.operator_passcode, dumped)


class AgentLoopTests(unittest.TestCase):
    def test_calls_tools_then_answers_and_navigates(self):
        requests = []

        def handler(request):
            body = json.loads(request.content)
            requests.append(body)
            if len(requests) == 1:  # the model asks for two tools
                return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [
                    {"functionCall": {"name": "get_statistics", "args": {}}, "thoughtSignature": "sig"},
                    {"functionCall": {"name": "navigate", "args": {"page": "history"}}}]}}]})
            return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": "yield 63.5%"}]}}]})

        real = httpx.AsyncClient
        with patch.dict(os.environ, {"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "k", "GEMINI_MODELS": "m1"}), \
                patch("app.services.agent_service.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)):
            async def run():
                return [json.loads(l) async for l in agent_service.run_agent([{"role": "user", "content": "yield?"}], "aoi")]

            events = asyncio.run(run())
        kinds = [e["type"] for e in events]
        self.assertEqual(kinds, ["tool", "tool", "navigate", "text"])
        self.assertEqual(events[-1]["text"], "yield 63.5%")
        second = requests[1]["contents"]
        self.assertEqual(second[1]["parts"][0]["thoughtSignature"], "sig")  # model turn replayed verbatim
        self.assertIn("board_yield_rate", json.dumps(second[2]["parts"][0]["functionResponse"]["response"]))
        self.assertIn("aoi", requests[0]["systemInstruction"]["parts"][0]["text"])


class AgentEndpointTests(unittest.TestCase):
    def test_answer_is_saved_and_cleared(self):
        client = TestClient(app)
        client.delete("/api/chat/agent/history")

        async def fake(history, page):
            yield json.dumps({"type": "tool", "name": "get_statistics", "label": "x", "args": {}}) + "\n"
            yield json.dumps({"type": "text", "text": "ok"}) + "\n"

        with patch.object(agent_service, "run_agent", fake):
            res = client.post("/api/chat/agent", json={"messages": [{"role": "user", "content": "q"}], "page": "aoi"})
        self.assertEqual([json.loads(l)["type"] for l in res.text.strip().split("\n")], ["tool", "text"])
        self.assertEqual([m["content"] for m in client.get("/api/chat/agent/history").json()["messages"]], ["q", "ok"])
        client.delete("/api/chat/agent/history")
        self.assertEqual(client.get("/api/chat/agent/history").json()["messages"], [])


if __name__ == "__main__":
    unittest.main()


class AgentFallbackTests(unittest.TestCase):
    def test_busy_model_mid_turn_restarts_on_the_next_model(self):
        calls = []

        def handler(request):
            model = request.url.path.split("/")[-1].split(":")[0]
            calls.append(model)
            if model == "m1" and len(calls) == 1:
                return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"functionCall": {"name": "get_statistics", "args": {}}}]}}]})
            if model == "m1":
                return httpx.Response(503, json={"error": {"message": "high demand"}})
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "done"}]}}]})

        real = httpx.AsyncClient
        with patch.dict(os.environ, {"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "k", "GEMINI_MODELS": "m1,m2"}), \
                patch.object(agent_service, "RETRY_DELAYS_SEC", (0, 0)), \
                patch("app.services.agent_service.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)):
            async def run():
                return [json.loads(l) async for l in agent_service.run_agent([{"role": "user", "content": "q"}], None)]

            events = asyncio.run(run())
        self.assertEqual(events[-1], {"type": "text", "text": "done", "model": "m2"})
        self.assertEqual(calls, ["m1", "m1", "m1", "m1", "m2"])


class HeartbeatTests(unittest.TestCase):
    def test_pings_while_waiting_then_passes_lines_through(self):
        from app.routers.chat import with_heartbeat

        async def slow():
            await asyncio.sleep(0.25)
            yield "a\n"
            yield "b\n"

        async def run():
            return [l async for l in with_heartbeat(slow(), interval=0.1)]

        out = asyncio.run(run())
        self.assertGreaterEqual(out.count('{"type": "ping"}\n'), 1)
        self.assertEqual([l for l in out if "ping" not in l], ["a\n", "b\n"])


class RetiredModelTests(unittest.TestCase):
    """A model that is still listed but answers 404 ('no longer available to new users') is skipped."""

    def setUp(self):
        from app.services import chat_service

        self.chat_service = chat_service
        chat_service._dead_models.clear()
        self.addCleanup(chat_service._dead_models.clear)

    def _handler(self, calls):
        def handler(request):
            model = request.url.path.split("/")[-1].split(":")[0]
            calls.append(model)
            if model == "old-model":
                return httpx.Response(404, json={"error": {"message": "no longer available to new users"}})
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

        return handler

    def test_agent_skips_a_404_model_and_remembers_it(self):
        calls = []
        real = httpx.AsyncClient
        env = {"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "k", "GEMINI_MODELS": "old-model,new-model"}
        with patch.dict(os.environ, env), \
                patch("app.services.agent_service.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(self._handler(calls)), **kw)):
            async def run():
                return [json.loads(l) async for l in agent_service.run_agent([{"role": "user", "content": "q"}], None)]

            first = asyncio.run(run())
            self.assertEqual(first[-1]["text"], "ok")
            self.assertEqual(calls, ["old-model", "new-model"])
            calls.clear()
            asyncio.run(run())
            self.assertEqual(calls, ["new-model"])  # the dead model is not tried again

    def test_board_chat_skips_a_404_model(self):
        calls = []
        real = httpx.AsyncClient

        def handler(request):
            model = request.url.path.split("/")[-1].split(":")[0]
            calls.append(model)
            if model == "old-model":
                return httpx.Response(404, json={"error": {"message": "gone"}})
            return httpx.Response(200, text='data: {"candidates":[{"content":{"parts":[{"text":"hi"}]}}]}\n\n')

        env = {"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "k", "GEMINI_MODELS": "old-model,new-model"}
        with patch.dict(os.environ, env), \
                patch("app.services.chat_service.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)):
            async def run():
                return "".join([x async for x in self.chat_service.stream_reply([{"role": "user", "content": "q"}])])

            self.assertEqual(asyncio.run(run()), "hi")
        self.assertEqual(calls, ["old-model", "new-model"])


class AllBusyTests(unittest.TestCase):
    def test_goes_round_all_models_again_before_giving_up(self):
        calls = []

        def handler(request):
            calls.append(request.url.path.split("/")[-1].split(":")[0])
            if len(calls) <= 4:  # first pass: both models busy (2 tries each)
                return httpx.Response(503, json={"error": {"message": "high demand"}})
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "later"}]}}]})

        real = httpx.AsyncClient
        with patch.dict(os.environ, {"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "k", "GEMINI_MODELS": "m1,m2"}), \
                patch.object(agent_service, "RETRY_DELAYS_SEC", (0,)), patch.object(agent_service, "ROUND_PAUSE_SEC", 0), \
                patch("app.services.agent_service.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)):
            async def run():
                return [json.loads(l) async for l in agent_service.run_agent([{"role": "user", "content": "q"}], None)]

            events = asyncio.run(run())
        self.assertEqual(events[-1]["text"], "later")
        self.assertEqual(calls, ["m1", "m1", "m2", "m2", "m1"])


class PartMarkingsToolTests(unittest.TestCase):
    def test_reads_only_the_asked_classes_and_merges_part_numbers(self):
        import cv2
        import numpy as np

        from app.config import UPLOADS_DIR

        img = np.full((400, 600, 3), 40, np.uint8)
        cv2.putText(img, "LM317T", (200, 215), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (225, 225, 225), 3)
        path = UPLOADS_DIR / "test_agent_markings.png"
        cv2.imwrite(str(path), img)
        self.addCleanup(path.unlink, missing_ok=True)
        ic_box = [140, 130, 460, 270]
        report = {"results": [
            {"point_index": 0, "name": "จุด 1", "image_path": str(path), "detections": [
                {"label": "ic", "box": ic_box}, {"label": "resistor", "box": [10, 10, 60, 40]}]},
            {"point_index": 1, "name": "จุด 2", "image_path": str(path), "detections": [{"label": "ic", "box": ic_box}]},
        ]}
        with patch("app.routers.history.get_run_details", return_value=report):
            res = agent_service.run_tool("read_part_markings", {"run_id": "r", "labels": ["ic"]})
        self.assertEqual(res["with_text"], 2)  # the resistor was not read
        self.assertEqual({p["class"] for p in res["parts"]}, {"ic"})
        top = res["likely_part_numbers"][0]
        self.assertEqual((top["part_number"], top["count"], top["points"]), ("LM317T", 2, [1, 2]))
        self.assertIn("read_part_markings", {d["name"] for d in agent_service.DECLARATIONS})


class BoardToolTests(unittest.TestCase):
    def test_list_and_detail_by_name(self):
        from app.services import point_set_store

        board = point_set_store.create_set("บอร์ดทดสอบ agent", [
            {"name": "จุด 1", "x_mm": 10, "y_mm": 10, "zoom": 1,
             "expected_components": [{"id": "P1", "name": "ic", "bbox": [0, 0, .1, .1]}, {"id": "P2", "name": "ic", "bbox": [.2, .2, .3, .3]}]},
            {"name": "จุด 2", "x_mm": 15, "y_mm": 20, "zoom": 2}])
        self.addCleanup(point_set_store.delete_set, board["id"])
        listed = agent_service.run_tool("list_boards", {})
        self.assertIn(("บอร์ดทดสอบ agent", 2, 2), [(b["name"], b["points"], b["taught_parts"]) for b in listed])
        detail = agent_service.run_tool("get_board", {"name": "ทดสอบ agent"})
        self.assertEqual((detail["point_count"], detail["untaught_points"], detail["parts_by_class"]), (2, 1, {"ic": 2}))
        self.assertEqual(detail["points"][1]["zoom"], 2)
        self.assertIn("error", agent_service.run_tool("get_board", {"name": "ไม่มีจริง"}))


class QuotaAndTimeoutTests(unittest.TestCase):
    """The 2026-10 failure: two models out of quota (429), the third hanging (read timeout).
    The turn must go on to the model that still answers, and skip the bad ones next time."""

    QUOTA = {"error": {"code": 429, "message": "You exceeded your current quota, please check your plan and billing details.",
                       "status": "RESOURCE_EXHAUSTED", "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"}]}}

    def setUp(self):
        from app.services import chat_service

        self.chat_service = chat_service
        for store in (chat_service._dead_models, chat_service._resting):
            store.clear()
            self.addCleanup(store.clear)

    def _handler(self, calls, stream=False):
        def handler(request):
            model = request.url.path.split("/")[-1].split(":")[0]
            calls.append(model)
            if model in ("quota-a", "quota-b"):
                return httpx.Response(429, json=self.QUOTA)
            if model == "hangs":
                raise httpx.ReadTimeout("no answer", request=request)
            if stream:
                return httpx.Response(200, text='data: {"candidates":[{"content":{"parts":[{"text":"hi"}]}}]}\n\n')
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

        return handler

    def _env(self):
        return {"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "k", "GEMINI_MODELS": "quota-a,quota-b,hangs,works"}

    def test_agent_falls_through_quota_and_timeout(self):
        calls = []
        real = httpx.AsyncClient
        with patch.dict(os.environ, self._env()), \
                patch("app.services.agent_service.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(self._handler(calls)), **kw)):
            async def run():
                return [json.loads(l) async for l in agent_service.run_agent([{"role": "user", "content": "q"}], None)]

            events = asyncio.run(run())
            self.assertEqual(events[-1], {"type": "text", "text": "ok", "model": "works"})
            self.assertEqual(calls, ["quota-a", "quota-b", "hangs", "works"])  # quota is not retried
            labels = [e["label"] for e in events if e.get("name") == "retry"]
            self.assertEqual(labels, ["quota-a โควต้าหมด — เปลี่ยนรุ่น AI แล้วลองใหม่",
                                      "quota-b โควต้าหมด — เปลี่ยนรุ่น AI แล้วลองใหม่",
                                      "hangs ไม่ตอบ — เปลี่ยนรุ่น AI แล้วลองใหม่"])
            calls.clear()
            asyncio.run(run())
            self.assertEqual(calls, ["works"])  # the resting models are skipped

    def test_board_chat_falls_through_quota_and_timeout(self):
        calls = []
        real = httpx.AsyncClient
        with patch.dict(os.environ, self._env()), \
                patch("app.services.chat_service.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(self._handler(calls, stream=True)), **kw)):
            async def run():
                return [p async for p in self.chat_service._stream_gemini([{"role": "user", "content": "q"}])]

            self.assertEqual("".join(asyncio.run(run())), "hi")
            self.assertEqual(calls, ["quota-a", "quota-b", "hangs", "works"])

    def test_quota_rest_uses_the_retry_delay(self):
        raw = json.dumps(self.QUOTA)
        self.assertEqual(self.chat_service.quota_rest(429, raw), 60.0)  # 37 s, at least a minute
        self.assertIsNone(self.chat_service.quota_rest(429, '{"error":{"message":"Resource has been exhausted, try later"}}'))
        self.assertIsNone(self.chat_service.quota_rest(503, raw))

    def test_all_resting_still_leaves_something_to_try(self):
        with patch.dict(os.environ, {"GEMINI_MODELS": "a,b"}):
            self.chat_service.rest("a", 600, "test")
            self.chat_service.rest("b", 600, "test")
            self.assertEqual(self.chat_service.gemini_models(), ["a", "b"])
