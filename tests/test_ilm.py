"""Acceptance tests for the ilm plugin core and its MCP server.

Run from the repository root:  python -m unittest discover -s tests -v
Only the standard library is required, except the PDF tests (need `pypdf`).
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

import ilm_core  # noqa: E402

RU_TEXT = (
    "Глава 1. Петли обратной связи\n\n"
    "Усиливающая обратная связь разгоняет рост: чем больше клиентов, тем больше рекомендаций. "
    "Автор приводит пример пивной игры, где каждый участник заказывает больше, чем нужно.\n\n"
    "Глава 2. Ментальные модели\n\n"
    "Ментальные модели определяют, что мы замечаем. Лестница умозаключений показывает, "
    "как человек от наблюдения переходит к выводу и действию, не проверяя допущения.\n\n"
) * 6


def make_txt(d):
    p = Path(d) / "book.txt"
    p.write_text(RU_TEXT, encoding="utf-8")
    return p


def make_fb2(d):
    p = Path(d) / "book.fb2"
    p.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
        "<description><title-info><book-title>Тестовая книга</book-title></title-info></description>"
        "<body><section><title><p>Глава о рычаге</p></title>"
        "<p>Точка рычага — это место, где малое усилие даёт большое изменение системы.</p>"
        "</section></body></FictionBook>",
        encoding="utf-8",
    )
    return p


def make_epub(d):
    p = Path(d) / "book.epub"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles></container>",
        )
        z.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Epub Sample</dc:title></metadata>'
            '<manifest><item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>',
        )
        z.writestr(
            "OEBPS/ch1.xhtml",
            "<html><head><title>x</title><style>p{color:red}</style></head><body>"
            "<h1>Chapter One: Habits</h1><p>A habit loop has a cue, a routine and a reward.</p></body></html>",
        )
        z.writestr(
            "OEBPS/ch2.xhtml",
            "<html><body><h1>Chapter Two: Keystone</h1><p>Keystone habits trigger other changes.</p></body></html>",
        )
    return p


def make_docx(d):
    p = Path(d) / "book.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Первый абзац про делегирование.</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>Второй абзац </w:t></w:r><w:r><w:t>про доверие.</w:t></w:r></w:p></w:body></w:document>",
        )
    return p


def make_pdf(d, pages):
    """Hand-built PDF, one text line per page ('' = page without text)."""
    objs = []
    n = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objs.append("<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, line in enumerate(pages):
        lines = line if isinstance(line, list) else ([line] if line else [])
        stream = "BT /F1 12 Tf 72 720 Td " + " 0 -20 Td ".join(f"({x}) Tj" for x in lines) + " ET" if lines else ""
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>"
        )
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    p = Path(d) / ("scan.pdf" if not any(pages) else "book.pdf")
    p.write_bytes(out)
    return p


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.store = ilm_core.Store(os.path.join(self.dir, "data"))

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def all_text(self):
        out, start = [], 0
        while True:
            r = self.store.read_chunks(start=start, count=50)
            if not r["chunks"]:
                return out
            out.extend(r["chunks"])
            start = r["chunks"][-1]["seq"] + 1


class IngestTests(Base):
    def test_txt(self):
        r = self.store.load_source(str(make_txt(self.dir)))
        self.assertTrue(r["loaded"])
        self.assertGreater(r["chunks"], 1)
        chunks = self.all_text()
        self.assertEqual(len(chunks), r["chunks"])
        self.assertIn("пивной игры", " ".join(c["text"] for c in chunks))
        self.assertTrue(all(c["location"] for c in chunks))

    def test_fb2_title_and_section(self):
        r = self.store.load_source(str(make_fb2(self.dir)))
        self.assertEqual(r["title"], "Тестовая книга")
        chunks = self.all_text()
        self.assertIn("Точка рычага", chunks[0]["text"])
        self.assertIn("Глава о рычаге", chunks[0]["location"])

    def test_epub_chapters_in_reading_order(self):
        r = self.store.load_source(str(make_epub(self.dir)))
        self.assertEqual(r["title"], "Epub Sample")
        chunks = self.all_text()
        text = " ".join(c["text"] for c in chunks)
        self.assertLess(text.index("habit loop"), text.index("Keystone habits"))
        self.assertNotIn("color:red", text)
        self.assertIn("Chapter One", chunks[0]["location"])

    def test_docx(self):
        self.store.load_source(str(make_docx(self.dir)))
        text = " ".join(c["text"] for c in self.all_text())
        self.assertIn("делегирование", text)
        self.assertIn("Второй абзац про доверие.", text)

    def test_pdf_pages_as_location(self):
        self.store.load_source(str(make_pdf(self.dir, ["Leverage points matter", "Second page about delays"])))
        chunks = self.all_text()
        self.assertIn("Leverage points", " ".join(c["text"] for c in chunks))
        self.assertRegex(chunks[0]["location"], r"1")

    def test_pdf_running_header_and_page_numbers_are_dropped(self):
        words = ["delays", "leverage", "feedback", "growth", "limits", "vision", "models", "teams"]
        pages = [["My Running Header", str(n), f"A page that talks about {w} in systems."]
                 for n, w in enumerate(words, 1)]
        self.store.load_source(str(make_pdf(self.dir, pages)))
        text = " ".join(c["text"] for c in self.all_text())
        self.assertNotIn("Running Header", text)
        self.assertIn("A page that talks about teams in systems.", text)

    def test_pdf_without_text_layer_is_refused(self):
        with self.assertRaises(ilm_core.IlmError) as cm:
            self.store.load_source(str(make_pdf(self.dir, ["", ""])))
        self.assertIn("text", str(cm.exception).lower())

    def test_youtube_uses_captions_with_timestamps(self):
        calls = []

        def fake(video_id):
            calls.append(video_id)
            return [
                {"start": 0.0, "text": "Welcome to the talk about deep work."},
                {"start": 125.0, "text": "Shallow work is easy to replicate."},
            ] * 40

        orig = ilm_core.fetch_youtube_transcript
        ilm_core.fetch_youtube_transcript = fake
        try:
            r = self.store.load_source("https://www.youtube.com/watch?v=abc123XYZ_-", title="Deep Work talk")
        finally:
            ilm_core.fetch_youtube_transcript = orig
        self.assertEqual(calls, ["abc123XYZ_-"])
        self.assertEqual(r["title"], "Deep Work talk")
        chunks = self.all_text()
        self.assertRegex(chunks[0]["location"], r"^\d{2}:\d{2}")

    def test_missing_and_unsupported_sources(self):
        with self.assertRaises(ilm_core.IlmError):
            self.store.load_source(os.path.join(self.dir, "nope.txt"))
        bad = Path(self.dir) / "book.xyz"
        bad.write_text("x")
        with self.assertRaises(ilm_core.IlmError):
            self.store.load_source(str(bad))


class MappingAndProgressTests(Base):
    def setUp(self):
        super().setUp()
        self.store.load_source(str(make_txt(self.dir)))

    def _map(self):
        return self.store.save_concepts(
            [
                {
                    "name": "Усиливающая петля",
                    "summary": "Рост, который подпитывает сам себя через обратную связь.",
                    "chapter": "Глава 1. Петли обратной связи",
                    "location": "фрагмент 1",
                    "author_example": "Пивная игра",
                },
                {
                    "name": "Лестница умозаключений",
                    "summary": "Путь от наблюдения к действию через непроверенные допущения.",
                    "chapter": "Глава 2. Ментальные модели",
                    "location": "фрагмент 2",
                    "author_example": "",
                },
            ],
            mapped_upto=2,
        )

    def test_mapping_pointer_moves(self):
        first = self.store.read_chunks(count=2)
        self.assertEqual(first["chunks"][0]["seq"], 0)
        r = self._map()
        self.assertEqual(len(r["concept_ids"]), 2)
        nxt = self.store.read_chunks(count=2)
        self.assertEqual(nxt["chunks"][0]["seq"], 2)
        st = self.store.status()
        self.assertEqual(st["book"]["mapped_chunks"], 2)
        self.assertFalse(st["book"]["mapping_complete"])

    def test_search_matches_russian_word_forms_and_concepts(self):
        self._map()
        r = self.store.search("обратной связи усиливают рост")
        self.assertTrue(r["passages"])
        self.assertIn("обратная связь", r["passages"][0]["text"])
        self.assertTrue(r["passages"][0]["location"])
        self.assertIn("Усиливающая петля", [c["name"] for c in r["concepts"]])

    def test_use_when_is_searchable_and_past_situations_come_back(self):
        ids = self.store.save_concepts([{
            "name": "Латание дыр", "summary": "Симптоматическое решение мешает настоящему.",
            "use_when": "скидки дедлайн аврал переработки повторяющийся кризис",
        }])["concept_ids"]
        self.assertEqual(self.store.status()["book"]["mapped_chunks"], 0)
        found = self.store.search("аврал перед дедлайном")["concepts"]
        self.assertEqual(found[0]["name"], "Латание дыр")
        self.assertIn("аврал", found[0]["use_when"])
        self.assertEqual(found[0]["user_situations"], [])
        self.store.mark(ids[0], "met", situation="скидки в конце месяца")
        found = self.store.search("аврал перед дедлайном")["concepts"]
        self.assertEqual(found[0]["user_situations"], ["скидки в конце месяца"])

    def test_same_idea_in_another_letter_case_is_not_duplicated(self):
        a = self.store.save_concepts([{"name": "Усиливающая петля", "summary": "с"}])["concept_ids"]
        b = self.store.save_concepts([{"name": "усиливающая ПЕТЛЯ", "summary": "с"}], mapped_upto=None)["concept_ids"]
        self.assertEqual(a, b)
        self.assertEqual(self.store.progress()["counts"]["new"], 1)

    def test_same_note_is_stored_once(self):
        self.store.remember("Любит рыбалку")
        self.store.remember("Любит рыбалку")
        self.assertEqual(self.store.status()["about_user"], ["Любит рыбалку"])

    def test_search_without_match_returns_empty_not_error(self):
        r = self.store.search("квантовая хромодинамика")
        self.assertEqual(r["passages"], [])

    def test_mark_met_then_applied_and_followup(self):
        ids = self._map()["concept_ids"]
        self.store.mark(ids[0], "met", situation="разговор с начальником о нагрузке")
        st = self.store.status()
        self.assertEqual(st["follow_up"]["concept"], "Усиливающая петля")
        self.assertIn("начальником", st["follow_up"]["situation"])
        self.store.mark(ids[0], "applied")
        p = self.store.progress()
        self.assertEqual(p["counts"], {"applied": 1, "met": 0, "new": 1})
        self.assertIsNone(self.store.status()["follow_up"])
        with self.assertRaises(ilm_core.IlmError):
            self.store.mark(ids[0], "done")
        with self.assertRaises(ilm_core.IlmError):
            self.store.mark(99999, "met")

    def test_profile_notes_survive_reopen(self):
        self.store.remember("Работает руководителем отдела продаж, двое детей")
        self.store.close()
        self.store = ilm_core.Store(os.path.join(self.dir, "data"))
        self.assertIn("двое детей", " ".join(self.store.status()["about_user"]))


class SwitchBookTests(Base):
    def test_switch_needs_confirmation_and_keeps_progress(self):
        txt = str(make_txt(self.dir))
        self.store.load_source(txt, title="Первая")
        ids = self.store.save_concepts(
            [{"name": "Идея А", "summary": "с", "chapter": "1", "location": "1", "author_example": ""}],
            mapped_upto=1,
        )["concept_ids"]
        self.store.mark(ids[0], "applied")
        self.store.remember("Живёт в Ташкенте")

        r = self.store.load_source(str(make_fb2(self.dir)))
        self.assertFalse(r["loaded"])
        self.assertTrue(r["needs_confirmation"])
        self.assertEqual(self.store.status()["book"]["title"], "Первая")

        r = self.store.load_source(str(make_fb2(self.dir)), confirm_switch=True)
        self.assertTrue(r["loaded"])
        st = self.store.status()
        self.assertEqual(st["book"]["title"], "Тестовая книга")
        self.assertEqual(self.store.progress()["counts"], {"applied": 0, "met": 0, "new": 0})
        self.assertIn("Ташкенте", " ".join(st["about_user"]))

        books = self.store.books()["books"]
        self.assertEqual(len(books), 2)
        first = [b for b in books if b["title"] == "Первая"][0]
        self.store.switch_book(first["id"])
        self.assertEqual(self.store.status()["book"]["title"], "Первая")
        self.assertEqual(self.store.progress()["counts"]["applied"], 1)

    def test_reloading_same_source_does_not_duplicate(self):
        txt = str(make_txt(self.dir))
        self.store.load_source(txt)
        self.store.load_source(str(make_fb2(self.dir)), confirm_switch=True)
        r = self.store.load_source(txt, confirm_switch=True)
        self.assertTrue(r["loaded"])
        self.assertEqual(len(self.store.books()["books"]), 2)

    def test_confirmation_must_be_a_real_true(self):
        import ilm_server
        self.store.load_source(str(make_txt(self.dir)), title="Первая")
        r = ilm_server.call_tool(self.store, "ilm_load_source",
                                 {"source": str(make_fb2(self.dir)), "confirm_switch": "false"})
        self.assertTrue(r["needs_confirmation"])
        with self.assertRaises(ilm_core.IlmError):
            ilm_server.call_tool(self.store, "ilm_delete_all", {"confirm": "false"})
        self.assertEqual(self.store.status()["book"]["title"], "Первая")

    def test_delete_all_leaves_no_text_in_the_file(self):
        self.store.load_source(str(make_txt(self.dir)))
        self.store.remember("секретная заметка о человеке")
        self.store.delete_all(confirm=True)
        self.store.close()
        raw = Path(self.dir, "data", "ilm.db").read_bytes()
        self.store = ilm_core.Store(os.path.join(self.dir, "data"))
        self.assertNotIn("секретная заметка".encode("utf-8"), raw)
        self.assertNotIn("пивной игры".encode("utf-8"), raw)

    def test_plain_sentence_is_not_taken_for_a_chapter_heading(self):
        p = Path(self.dir) / "plain.txt"
        p.write_text("Часть сотрудников уходит уже в первый месяц.\n\nPart of me wanted to quit.\n", encoding="utf-8")
        self.store.load_source(str(p))
        self.assertEqual([c["location"] for c in self.all_text()], ["fragment 1"])

    def test_delete_all_requires_confirmation(self):
        self.store.load_source(str(make_txt(self.dir)))
        self.store.remember("заметка")
        with self.assertRaises(ilm_core.IlmError):
            self.store.delete_all(confirm=False)
        self.store.delete_all(confirm=True)
        st = self.store.status()
        self.assertIsNone(st["book"])
        self.assertEqual(st["about_user"], [])


class VocabularyTests(Base):
    """The book as a working language: the whole glossary comes once, with the status."""

    def setUp(self):
        super().setUp()
        self.loaded = self.store.load_source(str(make_txt(self.dir)))
        self.ids = self.store.save_concepts([
            {"name": "Подмена проблемы", "summary": "Симптоматическое решение мешает настоящему и создаёт зависимость.",
             "gloss": "лечим симптом, корень остаётся", "use_when": "заплатка, повторяющаяся ошибка"},
            {"name": "Пределы роста", "summary": "Рост упирается в ограничивающий фактор."},
        ])["concept_ids"]

    def test_status_carries_the_whole_vocabulary(self):
        voc = self.store.status()["vocabulary"]
        self.assertEqual([v["term"] for v in voc], ["Подмена проблемы", "Пределы роста"])
        first = voc[0]
        self.assertEqual(first["id"], self.ids[0])
        self.assertEqual(first["means"], "лечим симптом, корень остаётся")
        self.assertEqual(first["when"], "заплатка, повторяющаяся ошибка")
        self.assertFalse(first["known"])
        self.assertEqual(voc[1]["means"], "Рост упирается в ограничивающий фактор.")   # no gloss: falls back

    def test_dropping_ideas_and_filling_a_missing_gloss(self):
        self.store.used([self.ids[1]], situation="рост остановился")
        self.assertEqual(self.store.drop_concepts([self.ids[0], 99999]), {"dropped": 1})
        voc = self.store.status()["vocabulary"]
        self.assertEqual([v["term"] for v in voc], ["Пределы роста"])
        again = self.store.save_concepts([{"name": "пределы роста", "summary": "другое", "gloss": "давить сильнее бесполезно"}])
        self.assertEqual(again["concept_ids"], [self.ids[1]])
        v = self.store.status()["vocabulary"][0]
        self.assertEqual(v["means"], "давить сильнее бесполезно")
        self.assertTrue(v["known"])                       # history survives the fill-in
        self.store.save_concepts([{"name": "Пределы роста", "summary": "с", "gloss": "не затирает"}])
        self.assertEqual(self.store.status()["vocabulary"][0]["means"], "давить сильнее бесполезно")

    def test_long_meaning_is_cut_at_a_word_border(self):
        self.store.save_concepts([{"name": "Длинная", "summary": "слово " * 80}])
        means = self.store.status()["vocabulary"][-1]["means"]
        self.assertLessEqual(len(means), 241)
        self.assertTrue(means.endswith("слово…"))

    def test_used_marks_several_terms_in_one_call(self):
        r = self.store.used(self.ids, situation="третья заплатка часовых поясов")
        self.assertEqual(r["marked"], 2)
        self.assertEqual(self.store.progress()["counts"], {"applied": 0, "met": 2, "new": 0})
        self.assertTrue(all(v["known"] for v in self.store.status()["vocabulary"]))
        self.assertEqual(self.store.search("заплатка")["concepts"][0]["user_situations"],
                         ["третья заплатка часовых поясов"])
        with self.assertRaises(ilm_core.IlmError):
            self.store.used([self.ids[0], 99999])

    def test_load_reports_what_full_mapping_will_cost(self):
        m = self.loaded["mapping"]
        self.assertEqual(m["fragments"], self.loaded["chunks"])
        self.assertGreater(m["approx_tokens"], 0)
        self.assertGreaterEqual(m["portions"], 1)

    def test_database_from_an_older_version_still_opens(self):
        import sqlite3
        d = os.path.join(self.dir, "old")
        os.makedirs(d)
        db = sqlite3.connect(os.path.join(d, "ilm.db"))
        db.execute("CREATE TABLE concepts(id INTEGER PRIMARY KEY, book_id INTEGER, name TEXT, summary TEXT, "
                   "chapter TEXT, location TEXT, author_example TEXT, status TEXT DEFAULT 'new', "
                   "met_count INTEGER DEFAULT 0)")
        db.execute("INSERT INTO concepts(book_id,name,summary) VALUES(1,'Старая идея','суть')")
        db.commit()
        db.close()
        old = ilm_core.Store(d)
        try:
            old.load_source(str(make_txt(self.dir)))
            self.assertEqual(old.status()["vocabulary"][0]["term"], "Старая идея")
            old.save_concepts([{"name": "Новая", "summary": "с", "gloss": "коротко"}])
            self.assertEqual(old.search("старая")["concepts"][0]["use_when"], "")
        finally:
            old.close()


class ProtocolTests(unittest.TestCase):
    def test_stdio_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, ILM_DATA_DIR=os.path.join(d, "data"))
            msgs = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                            "clientInfo": {"name": "t", "version": "0"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "ilm_remember", "arguments": {"note": "Любит рыбалку"}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                 "params": {"name": "ilm_status", "arguments": {}}},
                {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                 "params": {"name": "ilm_load_source", "arguments": {"source": "C:/nope/none.pdf"}}},
                {"jsonrpc": "2.0", "id": 6, "method": "no/such"},
                123,
                {"jsonrpc": "2.0", "id": 7, "method": "initialize", "params": [1, 2]},
                {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                 "params": {"name": "ilm_search", "arguments": {"query": "x", "limit": None}}},
                {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "ilm_guide", "arguments": {}}},
            ]
            data = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in msgs).encode("utf-8")
            p = subprocess.run([sys.executable, str(ROOT / "server" / "ilm_server.py")],
                               input=data, capture_output=True, env=env, timeout=60)
            lines = [json.loads(x) for x in p.stdout.decode("utf-8").splitlines() if x.strip()]
            by_id = {m["id"]: m for m in lines}
            self.assertEqual(set(by_id), {1, 2, 3, 4, 5, 6, 7, 8, 9})
            self.assertIn("result", by_id[7])
            self.assertNotIn("internal error", by_id[8]["result"]["content"][0]["text"])
            self.assertEqual(by_id[1]["result"]["protocolVersion"], "2025-06-18")
            self.assertIn("tools", by_id[1]["result"]["capabilities"])
            self.assertTrue(by_id[1]["result"]["instructions"])
            names = {t["name"] for t in by_id[2]["result"]["tools"]}
            self.assertLessEqual(
                {"ilm_status", "ilm_load_source", "ilm_read_chunks", "ilm_save_concepts", "ilm_search",
                 "ilm_mark", "ilm_progress", "ilm_remember", "ilm_books", "ilm_switch_book", "ilm_delete_all"},
                names,
            )
            for t in by_id[2]["result"]["tools"]:
                self.assertEqual(t["inputSchema"]["type"], "object")
            # Rules must reach clients that have no skills (Codex, Cursor, chat apps): through the server itself.
            self.assertIn("ilm_guide", names)
            self.assertIn("ilm_used", names)
            self.assertLessEqual(len(by_id[1]["result"]["instructions"]), 2000)
            self.assertIn("ilm_guide", by_id[1]["result"]["instructions"])
            self.assertIn("ilm_guide", json.loads(by_id[4]["result"]["content"][0]["text"])["rules"])
            guide = by_id[9]["result"]["content"][0]["text"]
            self.assertFalse(by_id[9]["result"]["isError"])
            self.assertFalse(guide.lstrip().startswith("---"))
            self.assertIn("decision", guide.lower())
            self.assertGreater(len(guide), 3000)
            self.assertIn("Любит рыбалку", by_id[4]["result"]["content"][0]["text"])
            self.assertTrue(by_id[5]["result"]["isError"])
            self.assertEqual(by_id[6]["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
