"""Book retrieval covers every page, keeps page citations, and never returns personal details."""
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
        pages = [_Page(f"{n} เนื้อหาทั่วไปของเล่มหน้านี้") for n in range(97)]
        pages[0] = _Page("ระบบตรวจสอบความสมบูรณ์ของแผ่น PCB ด้วยปัญญาประดิษฐ์ PCB MISSING COMPONENT")
        pages[3] = _Page("หัวข้อปริญญานิพนธ์ อาจารย์ที่ปรึกษา ผู้ช่วยศาสตราจารย์ ดร.ปราชญ์ อัศวนรากุล")
        pages[4] = _Page("ง หัวปริญญานิพนธ์ บทคัดย่อ ปริญญานิพนธ์นี้นำเสนอระบบตรวจสอบชิ้นส่วนบนแผ่น PCB")
        pages[6] = _Page("ฉ สารบัญ หน้า บทคัดย่อ ง กิตติกรรมประกาศ จ บทที่ 1 บทนำ บทที่ 3 วิธีดำเนินงาน")
        pages[12] = _Page("1 บทที่ 1 บทนำ 1.1 หลักการ และเหตุผล")
        pages[39] = _Page("28 บทที่ 3 วิธีการดำเนินงาน การดำเนินงานพัฒนาระบบ")
        pages[63] = _Page("ชุดข้อมูลหลักมีภาพทั้งหมด 652 ภาพ แบ่งเป็น Train Validation Test")
        pages[81] = _Page("Accuracy ระดับบอร์ด ≥ 90% ผล รอผลจริง")
        pages[83] = _Page("72 บทที่ 5 สรุปและข้อเสนอแนะ ระบบตรวจ PCB ด้วยปัญญาประดิษฐ์")
        pages[86] = _Page("75 บรรณานุกรม [1] ปัญหาความผิดพลาดในกระบวนการผลิตแผ่น PCB")
        pages[90] = _Page("79")
        pages[94] = _Page("83 ประวัติผู้จัดทำปริญญานิพนธ์ ชื่อ นายทดสอบ ระบบดี รหัสนักศึกษา 116610461223-7 "
                          "สาขาวิชา/ภาควิชา วิศวกรรมอิเล็กทรอนิกส์ วัน-เดือน-ปีเกิด วันที่ 1 มกราคม 2547 "
                          "สถานที่เกิด จังหวัดทดสอบ ที่อยู่ 99/9 ต.ทดสอบ อ.เมือง 25000 โทร 081-234-5678 "
                          "อีเมล someone@example.com ประวัติการศึกษา ปวช. วิทยาลัยเทคนิคทดสอบ")
        self.reader = type("Reader", (), {"pages": pages})()
        self.patches = [patch.object(book_knowledge, "_book_path", return_value=self.path),
                        patch("pypdf.PdfReader", return_value=self.reader)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_search_finds_number_and_cites_pdf_page(self):
        result = agent_service.run_tool("search_project_book", {"query": "ชุดข้อมูลหลักมีภาพทั้งหมดกี่ภาพ"})
        self.assertEqual(result["results"][0]["pdf_page"], 64)
        self.assertEqual(result["results"][0]["citation"], "PDF หน้า 64 (หน้า 52 ในเล่ม)")
        self.assertIn("652", result["results"][0]["text"])

    def test_page_read_and_overview_preserve_unmeasured_result(self):
        page = agent_service.run_tool("read_project_book_page", {"pdf_page": 82})
        self.assertIn("รอผลจริง", page["text"])
        self.assertEqual(page["book_page"], 70)
        overview = agent_service.run_tool("get_project_book_overview", {})
        self.assertEqual(overview["contents"][0]["pdf_page"], 7)
        self.assertEqual(overview["abstract"][0]["pdf_page"], 5)
        self.assertIn("รอผลจริง", overview["note"])
        self.assertEqual([(c["chapter"], c["title"], c["pdf_from"], c["pdf_to"]) for c in overview["chapters"]],
                         [(1, "บทนำ", 13, 39), (3, "วิธีการดำเนินงาน", 40, 83), (5, "สรุปและข้อเสนอแนะ", 84, 86)])
        self.assertEqual(overview["sections"]["authors"], [95])

    def test_every_page_is_readable_with_its_printed_number(self):
        cover = agent_service.run_tool("read_project_book_page", {"pdf_page": 1})
        self.assertEqual(cover["citation"], "PDF หน้า 1 (ปก)")
        approval = agent_service.run_tool("read_project_book_page", {"pdf_page": 4})
        self.assertEqual(approval["page_label"], "ค")
        self.assertIn("อาจารย์ที่ปรึกษา", approval["text"])
        self.assertIn("บรรณานุกรม", agent_service.run_tool("read_project_book_page", {"pdf_page": 87})["text"])
        self.assertIn("หน้าว่าง", agent_service.run_tool("read_project_book_page", {"pdf_page": 91})["error"])
        self.assertIn("error", agent_service.run_tool("read_project_book_page", {"pdf_page": 98}))

    def test_reads_a_run_of_pages_at_most_ten(self):
        run = agent_service.run_tool("read_project_book_page", {"pdf_page": 13, "to_page": 30})
        self.assertEqual([p["pdf_page"] for p in run["pages"]], list(range(13, 23)))
        self.assertEqual(run["next_page"], 23)

    def test_biography_keeps_name_and_education_but_not_personal_details(self):
        bio = agent_service.run_tool("read_project_book_page", {"pdf_page": 95})["text"]
        self.assertIn("นายทดสอบ ระบบดี", bio)
        self.assertIn("วิทยาลัยเทคนิคทดสอบ", bio)
        for secret in ("116610461223", "มกราคม 2547", "จังหวัดทดสอบ", "99/9", "081-234-5678", "someone@example.com"):
            self.assertNotIn(secret, bio)
        found = agent_service.run_tool("search_project_book", {"query": "รหัสนักศึกษา ที่อยู่ ผู้จัดทำ"})
        self.assertNotIn("116610461223", json.dumps(found, ensure_ascii=False))

    def test_bundled_index_has_no_personal_details(self):
        text = book_knowledge.BUNDLED_INDEX_PATH.read_text(encoding="utf-8")
        import re
        self.assertIsNone(re.search(r"\d{12}-\d", text))
        self.assertNotIn("ที่อยู่ 1", text)
        self.assertNotIn("วัน-เดือน-ปีเกิด", text)
        pages = {p["pdf_page"] for p in json.loads(text)["pages"]}
        self.assertTrue({1, 4, 5, 7, 13, 87, 95} <= pages)

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
        self.assertEqual(result["results"][0]["citation"], "PDF หน้า 64 (หน้า 52 ในเล่ม)")
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
