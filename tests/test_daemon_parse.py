"""daemon 的代码块解析：截断的回复不该被当成「没给内容」。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xm.daemon import Daemon, DaemonConfig
from xm.ledger import Ledger


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        out = root / "out"
        out.mkdir()
        self.daemon = Daemon(
            Ledger(root / "ledger.jsonl"), lambda m: "x",
            DaemonConfig(spec="写文档", target_file=str(out / "doc.md"), tests=[],
                         artifacts_root=str(out),
                         verify_cmd=[sys.executable, "-c", "pass"]),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_closed_fence(self):
        got = self.daemon._parse("```markdown\n# 标题\n正文\n```")
        self.assertEqual(got.strip(), "# 标题\n正文")

    def test_unterminated_fence_is_still_content(self):
        """被 max_tokens 截断（没有闭合 ```）时，拿到的正文不能白丢。"""
        got = self.daemon._parse("```markdown\n# 标题\n正文写到一半")
        self.assertIsNotNone(got)
        self.assertIn("正文写到一半", got)

    def test_no_fence_is_none(self):
        self.assertIsNone(self.daemon._parse("我直接说结论：这样不行"))

    def test_picks_longest_block(self):
        text = "```markdown\n短\n```\n\n```markdown\n更长的正文\n```"
        self.assertIn("更长的正文", self.daemon._parse(text))


if __name__ == "__main__":
    unittest.main()