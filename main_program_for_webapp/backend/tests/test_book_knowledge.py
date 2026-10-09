"""Book retrieval keeps page citations and avoids personal front/back matter."""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from app.services import agent_service, book_knowledge


class _Page:
    def __init__(self, text):
        self.text = text

    def extract_text(self):
        return self.text


class BookKnowledgeTests(unittest.TestCase):
    def setUp(self):
        book_knowledge._cache = None
        self.addCleanup(setattr, book_knowledge, "_cache", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "book.pdf"
        self.path.write_bytes(b"pdf fixture")
        pages = [_Page("private student ID 123456789 address") for _ in range(97)]
        pages[6] = _Page("สารบัญ บทที่ 1 บทนำ บทที่ 3 วิธีดำเนินงาน บทที่ 4 ผลการดำเนินงาน")
        pages[7] = _Page("สารบัญ บทที่ 5 สรุปและข้อเสนอแนะ")
        pages[63] = _Page("ชุดข้อมูลหลักมีภาพทั้งหมด 652 ภาพ แบ่งเป็น Train Validation Test")
        pages[81] = _Page("Accuracy ระดับบอร์ด ≥ 90% ผล รอผลจริง")
        pages[83] = _Page("บทที่ 5 สรุป ระบบตรวจ PCB ด้วยปัญญาประดิษฐ์")
        self.reader = type("Reader", (), {"pages": pages})()
        self.patches = [patch.object(book_knowledge, "_book_path", return_value=self.path),
                        patch("pypdf.PdfReader", return_value=self.reader)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_search_finds_number_and_cites_pdf_page(self):
        result = agent_service.run_tool("search_project_book", {"query": "ชุดข้อมูลหลักมีภาพทั้งหมดกี่ภาพ"})
        self.assertEqual(result["results"][0]["pdf_page"], 64)
        self.assertEqual(result["results"][0]["citation"], "PDF หน้า 64")
        self.assertIn("652", result["results"][0]["text"])
        self.assertNotIn("student ID", str(result))

    def test_page_read_and_overview_preserve_unmeasured_result(self):
        page = agent_service.run_tool("read_project_book_page", {"pdf_page": 82})
        self.assertIn("รอผลจริง", page["text"])
        self.assertEqual(page["book_page"], 70)
        self.assertIn("error", agent_service.run_tool("read_project_book_page", {"pdf_page": 95}))
        overview = agent_service.run_tool("get_project_book_overview", {})
        self.assertEqual(overview["contents"][0]["pdf_page"], 7)
        self.assertIn("รอผลจริง", overview["note"])

    def test_missing_pdf_returns_actionable_error(self):
        with patch.object(book_knowledge, "_book_path", return_value=self.path.with_name("missing.pdf")), \
                patch.object(book_knowledge, "BUNDLED_INDEX_PATH", self.path.with_name("missing.json")):
            result = agent_service.run_tool("search_project_book", {"query": "โมเดล"})
        self.assertIn("error", result)
        self.assertIn("project_book.pdf", result["error"])

    def test_bundled_text_works_without_station_pdf(self):
        bundled = self.path.with_name("pages.json")
        bundled.write_text(json.dumps({"pages": [
            {"pdf_page": 64, "text": "ชุดข้อมูลหลักมีภาพทั้งหมด 652 ภาพ แบ่งเป็น Train Validation Test"}
        ]}, ensure_ascii=False), encoding="utf-8")
        with patch.object(book_knowledge, "_book_path", return_value=self.path.with_name("missing.pdf")), \
                patch.object(book_knowledge, "BUNDLED_INDEX_PATH", bundled):
            result = agent_service.run_tool("search_project_book", {"query": "ชุดข้อมูลหลักมีภาพทั้งหมด"})
            status = book_knowledge.book_status()
        self.assertEqual(result["results"][0]["citation"], "PDF หน้า 64")
        self.assertEqual(status["source"], "bundled_text")

    def test_agent_receives_book_excerpts_and_page_numbers(self):
        requests = []

        def handler(request):
            body = json.loads(request.content)
            requests.append(body)
            if len(requests) == 1:
                return httpx.Response(200, json={"candidates": [{"content": {"parts": [
                    {"functionCall": {"name": "search_project_book", "args": {"query": "ชุดข้อมูลหลักมีภาพทั้งหมด"}}}
                ]}}]})
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [
                {"text": "ชุดข้อมูลหลักมี 652 ภาพ (PDF หน้า 64)"}
            ]}}]})

        real_client = httpx.AsyncClient
        with patch.dict(os.environ, {"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "test-key", "GEMINI_MODELS": "test-model"}), \
                patch("app.services.agent_service.httpx.AsyncClient",
                      lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs)):
            events = asyncio.run(_collect_agent())

        self.assertEqual([event["type"] for event in events], ["tool", "text"])
        self.assertIn("PDF หน้า 64", events[-1]["text"])
        self.assertIn("PDF หน้า 64", json.dumps(requests[1], ensure_ascii=False))
        self.assertIn("search_project_book", requests[0]["systemInstruction"]["parts"][0]["text"])

    def test_agent_stops_when_book_source_is_missing(self):
        requests = []

        def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [
                {"functionCall": {"name": "get_project_book_overview", "args": {}}}
            ]}}]})

        real_client = httpx.AsyncClient
        with patch.dict(os.environ, {"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "test-key", "GEMINI_MODELS": "test-model"}), \
                patch("app.services.agent_service.httpx.AsyncClient",
                      lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs)), \
                patch.dict(agent_service.TOOLS, {"get_project_book_overview": lambda: {"error": "ไม่พบข้อมูลเล่ม"}}):
            events = asyncio.run(_collect_agent())

        self.assertEqual(len(requests), 1)
        self.assertEqual([event["type"] for event in events], ["tool", "text"])
        self.assertIn("ยังตอบจากเล่มไม่ได้", events[-1]["text"])


async def _collect_agent():
    return [json.loads(line) async for line in agent_service.run_agent(
        [{"role": "user", "content": "ในเล่ม ชุดข้อมูลหลักมีภาพกี่ภาพ"}], None)]


if __name__ == "__main__":
    unittest.main()
