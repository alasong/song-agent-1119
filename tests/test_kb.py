"""知识底座验收（G4 的机检基础）。"""
import tempfile
import unittest
from pathlib import Path

from xm.kb import KnowledgeBase, KnowledgeError


class KnowledgeBaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "kb.jsonl"
        self.kb = KnowledgeBase(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_rejects_fact_without_evidence(self):
        with self.assertRaises(KnowledgeError):
            self.kb.add("不加证据的结论", "demo", [], "src")

    def test_add_and_search(self):
        self.kb.add("Python 的 GIL 限制了多线程并行", "lang", ["docs:cpython/gil"], "doc")
        hits = self.kb.search("GIL")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].domain, "lang")

    def test_search_filters_by_domain(self):
        self.kb.add("事实 A", "domain-a", ["e1"], "s")
        self.kb.add("事实 A", "domain-b", ["e2"], "s")
        self.assertEqual(len(self.kb.search("事实", domain="domain-a")), 1)
        self.assertEqual(len(self.kb.search("事实")), 2)

    def test_dedupe_by_content(self):
        f1 = self.kb.add("同一事实", "d", ["e"], "s")
        f2 = self.kb.add("同一事实", "d", ["e2"], "s2")
        self.assertEqual(f1.key, f2.key)
        self.assertEqual(self.kb.count(), 1)

    def test_persisted_across_instances(self):
        self.kb.add("持久事实", "d", ["e"], "s")
        again = KnowledgeBase(self.path)
        self.assertEqual(again.count(), 1)
        self.assertEqual(len(again.search("持久")), 1)

    def test_domains_listed(self):
        self.kb.add("x", "b", ["e"], "s")
        self.kb.add("y", "a", ["e"], "s")
        self.assertEqual(self.kb.domains(), ["a", "b"])


if __name__ == "__main__":
    unittest.main()