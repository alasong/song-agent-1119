"""手的边界：只走白名单、失败要大声、取回必须落成证据（时间由系统打戳）。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sa2.core.evidence import EvidenceBook, citation_problems
from sa2.fetch import FetchError, arxiv, parse_atom, query_url, record

ATOM = """<?xml version="1.0"?><feed>
<entry><id>http://arxiv.org/abs/2611.00001v1</id><published>2026-11-18T00:00:00Z</published>
<title>Piccolo: Co-Evolving Decision Models</title>
<summary>We study recursive self improvement.</summary>
<link href="http://arxiv.org/abs/2611.00001v1"/></entry>
<entry><id>http://arxiv.org/abs/2611.00002v1</id><published>2026-11-17T00:00:00Z</published>
<title>BaseRSI</title><summary>Another one.</summary>
<link href="http://arxiv.org/abs/2611.00002v1"/></entry>
</feed>"""


class ParseTest(unittest.TestCase):
    def test_entries_are_parsed(self):
        got = parse_atom(ATOM)
        self.assertEqual([e["arxiv_id"] for e in got], ["2611.00001v1", "2611.00002v1"])
        self.assertEqual(got[0]["published"], "2026-11-18")
        self.assertIn("Piccolo", got[0]["title"])

    def test_empty_feed_is_a_failure_not_zero_results(self):
        with self.assertRaises(FetchError):
            parse_atom("<feed></feed>")


class BoundaryTest(unittest.TestCase):
    def test_query_url_is_https_arxiv(self):
        url = query_url('all:"recursive self-improvement"', 3)
        self.assertTrue(url.startswith("https://export.arxiv.org/api/query?"))

    def test_empty_query_is_refused(self):
        with self.assertRaises(FetchError):
            arxiv("   ")

    def test_network_failure_is_loud(self):
        def boom(url, timeout):
            raise ConnectionResetError("断了")
        with self.assertRaises(FetchError):
            arxiv("x", 2, transport=boom)

    def test_success_path_uses_injected_transport(self):
        got = arxiv("x", 2, transport=lambda url, timeout: ATOM)
        self.assertEqual(len(got), 2)


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.book = EvidenceBook(Path(self.tmp.name) / "evidence.jsonl")
        self.root = Path(self.tmp.name) / "content"

    def tearDown(self):
        self.tmp.cleanup()

    def test_entries_become_citable_evidence(self):
        evs = record(parse_atom(ATOM), self.book, self.root, "leader")
        self.assertEqual([e.evidence_id for e in evs], ["S1", "S2"])
        self.assertEqual(len(self.book.all()), 2)
        self.assertEqual(citation_problems("见 [S1] 与 [S2]", self.book), [])

    def test_recorded_evidence_carries_system_timestamp(self):
        ev = record(parse_atom(ATOM), self.book, self.root, "leader")[0]
        self.assertRegex(ev.fetched_at, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
        self.assertTrue(Path(ev.content_path).is_file())


if __name__ == "__main__":
    unittest.main()
