"""证据原语的底线：没有内容就没有证据，记录被改过就进不来，引用必须对得上台账。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sa2.core.evidence import (Evidence, EvidenceBook, EvidenceError,
                               citation_problems, digest_of, markers, stamp)

TODAY = date(2026, 11, 20)


class StampTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "evidence-content"

    def tearDown(self):
        self.tmp.cleanup()

    def test_stamp_writes_content_addressed_file(self):
        ev = stamp("https://arxiv.org/abs/2505.03335", "摘要正文", "leader", "S1",
                   self.root, now=datetime(2026, 11, 1, 9, 0, 0))
        self.assertEqual(ev.digest, digest_of("摘要正文"))
        self.assertEqual(Path(ev.content_path).name, f"{ev.digest}.txt")
        self.assertEqual(Path(ev.content_path).read_text(encoding="utf-8"), "摘要正文")
        self.assertTrue(ev.fetched_at.startswith("2026-11-01"), "时间由系统打戳")

    def test_stamp_without_uri_is_refused(self):
        with self.assertRaises(EvidenceError):
            stamp("  ", "正文", "leader", "S1", self.root)


class BookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "content"
        self.book = EvidenceBook(Path(self.tmp.name) / "evidence.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, eid="S1", content="取回的数据", when=datetime(2026, 11, 1, 9, 0, 0)) -> Evidence:
        return stamp("https://example.org/x", content, "leader", eid, self.root, now=when)

    def test_add_then_read_back(self):
        ev = self.book.add(self.make())
        self.assertEqual([e.evidence_id for e in self.book.all()], ["S1"])
        self.assertEqual(self.book.get("S1"), ev)

    def test_content_must_exist_on_disk(self):
        ev = self.make()
        Path(ev.content_path).unlink()
        with self.assertRaises(EvidenceError) as ctx:
            self.book.add(ev)
        self.assertIn("没有落盘内容", str(ctx.exception))
        self.assertEqual(self.book.all(), [], "被拒的证据不许留下半条记录")

    def test_tampered_content_is_refused(self):
        ev = self.make()
        Path(ev.content_path).write_text("换掉的内容", encoding="utf-8")
        with self.assertRaises(EvidenceError) as ctx:
            self.book.add(ev)
        self.assertIn("digest 不符", str(ctx.exception))

    def test_duplicate_id_is_refused(self):
        self.book.add(self.make(eid="S1"))
        with self.assertRaises(EvidenceError) as ctx:
            self.book.add(self.make(eid="S1", content="另一次取回"))
        self.assertIn("重复", str(ctx.exception))

    def test_bad_timestamp_is_refused(self):
        ev = Evidence(evidence_id="S9", uri="u", fetched_at="昨天", content_path="x",
                      digest="0", verifier="leader")
        with self.assertRaises(EvidenceError):
            self.book.add(ev)


class CitationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "content"
        self.book = EvidenceBook(Path(self.tmp.name) / "evidence.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, eid="S1", when=datetime(2026, 11, 1, 9, 0, 0), content="数据"):
        self.book.add(stamp("https://example.org/x", content, "leader", eid,
                            self.root, now=when))

    def check(self, text: str) -> list[str]:
        return citation_problems(text, self.book, today=TODAY)

    def test_fresh_citation_passes(self):
        self.add()
        self.assertEqual(self.check("## 一、进展\n见 [S1]，数据取于 11 月。"), [])

    def test_unknown_citation_is_red(self):
        problems = self.check("## 一、进展\n见 [S7]。")
        self.assertTrue(any("不在证据台账里" in p for p in problems), problems)

    def test_stale_citation_is_red_with_reading(self):
        self.add(when=datetime(2025, 5, 6, 9, 0, 0))
        problems = self.check("## 一、进展\n见 [S1]。")
        self.assertTrue(any("563 天" in p for p in problems), problems)

    def test_future_citation_is_red(self):
        self.add(when=datetime(2027, 1, 1, 9, 0, 0))
        problems = self.check("## 一、进展\n见 [S1]。")
        self.assertTrue(any("编的" in p for p in problems), problems)

    def test_no_citation_is_not_judged(self):
        self.assertEqual(self.check("## 一、方案\n先跑基线。"), [],
                         "没有引用不判红——要不要引用是声明的判据，不是台账的事")

    def test_unused_evidence_is_not_a_problem(self):
        self.add("S1")
        self.add("S2", content="另一份")
        self.assertEqual(self.check("## 一、进展\n见 [S1]。"), [],
                         "台账里多出来的证据不逼着正文引用")

    def test_markers_are_ordered_and_deduped(self):
        self.assertEqual(markers("[S2] 和 [S1]，又见 [S2]"), ["S2", "S1"])


if __name__ == "__main__":
    unittest.main()