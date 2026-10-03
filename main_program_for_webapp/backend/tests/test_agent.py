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
