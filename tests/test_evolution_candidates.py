"""经验提升成候选：只产候选不生效，判据全在数字上（支持数/注入量/成功率）。

`test_sa2_evolve_cli` 盖的是 CLI 与写入；这里打纯函数面——
退役的不算数、支持数不够不提升、没被注入过不算数，以及空候选不许建文件。
"""
import json
import tempfile
import unittest
from pathlib import Path

from sa2.memory import evolution


def lesson(text="同一类经验", when=None, injected=2, ok=2, status="active", lid="L1"):
    return {"id": lid, "text": text, "when": when or {"failure_kind": "zero_hit"},
            "stats": {"injected": injected, "ok": ok, "bad": injected - ok},
            "status": status}


class CandidatesTest(unittest.TestCase):
    def test_retired_lessons_do_not_count(self):
        rows = [lesson(lid="L1"), lesson(lid="L2"), lesson(lid="L3", status="retired")]
        found = evolution.candidates(rows, min_support=2)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["support"], 2, "退役的那条不许算进支持数")
        self.assertEqual(found[0]["status"], "proposed", "只产候选，不许自己生效")

    def test_below_min_support_raises_nothing(self):
        self.assertEqual(evolution.candidates([lesson(lid="L1")], min_support=2), [])

    def test_never_injected_is_not_promoted(self):
        rows = [lesson(lid="L1", injected=0, ok=0), lesson(lid="L2", injected=0, ok=0)]
        self.assertEqual(evolution.candidates(rows), [], "没被用过就无法证明它有用")

    def test_low_rate_is_not_promoted(self):
        rows = [lesson(lid="L1", injected=4, ok=1), lesson(lid="L2", injected=4, ok=1)]
        self.assertEqual(evolution.candidates(rows, min_rate=0.8), [])

    def test_promoted_candidate_merges_texts(self):
        rows = [lesson(text="甲", lid="L1"), lesson(text="乙", lid="L2")]
        found = evolution.candidates(rows)
        self.assertEqual(found[0]["injected"], 4)
        self.assertEqual(found[0]["proposal"]["kind"], "prompt_note")
        self.assertIn("甲", found[0]["proposal"]["text"])
        self.assertIn("乙", found[0]["proposal"]["text"])


class WriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "candidates.jsonl"

    def test_empty_candidates_do_not_create_a_file(self):
        self.assertEqual(evolution.write(self.path, []), 0)
        self.assertFalse(self.path.exists(), "空文件会让人以为「提升过一轮，结果是空的」")

    def test_existing_bad_lines_are_skipped_and_duplicates_not_rewritten(self):
        candidate = {"when": {"failure_kind": "zero_hit"}, "ids": ["L1", "L2"],
                     "status": "proposed", "proposal": {"kind": "prompt_note", "text": "甲"}}
        self.path.write_text("", encoding="utf-8")
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write("\n")
            fh.write("{坏行\n")
            fh.write(json.dumps(candidate, ensure_ascii=False) + "\n")
        self.assertEqual(evolution.write(self.path, [candidate]), 0, "同一条不许重复写")
        self.assertEqual(evolution.write(self.path, [{**candidate, "ids": ["L3"]}]), 1)


if __name__ == "__main__":
    unittest.main()