"""引用可溯源判据的验收。"""
import os
import tempfile
import unittest
from pathlib import Path

from xm.grounding import check_refs
from xm.kb import KnowledgeBase


class GroundingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kb_path = Path(self.tmp.name) / "kb.jsonl"
        kb = KnowledgeBase(self.kb_path)
        self.fact = kb.add("强化学习靠奖励信号学习策略", "rl", ["http://arxiv.org/abs/1"], "arxiv")
        self.old = os.environ.get("XM_KB_PATH")
        os.environ["XM_KB_PATH"] = str(self.kb_path)

    def tearDown(self):
        if self.old is None:
            os.environ.pop("XM_KB_PATH", None)
        else:
            os.environ["XM_KB_PATH"] = self.old
        self.tmp.cleanup()

    def _text(self, n=3, ref=None):
        r = ref or self.fact.key
        return " ".join(f"结论{i}[ref:{r}]" for i in range(n))

    def test_valid_refs_pass(self):
        result = check_refs(self._text())
        self.assertTrue(result["ok"])
        self.assertEqual(result["refs"], 3)

    def test_hallucinated_ref_fails(self):
        result = check_refs(self._text(ref="0" * 16))
        self.assertFalse(result["ok"])
        self.assertTrue(result["missing"])

    def test_too_few_refs_fails(self):
        self.assertFalse(check_refs(self._text(n=2))["ok"])

    def test_empty_text_fails(self):
        self.assertFalse(check_refs("")["ok"])


if __name__ == "__main__":
    unittest.main()