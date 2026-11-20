"""sa2 经验闭环（A/B/C）与体量/JSON API 配置（D）的回归测试。

只新增测试，不改实现；所有写操作落在 `tempfile.TemporaryDirectory()`；
第 9 条只读 `sources.json` 配置，不发任何网络请求。

与题面的对应关系：
  A1 classify 三态 · A2 bump 回写/未知 id/非法字段
  B3 被拒时按 failure_kind 注入经验并落 lesson 事件、injected +1
  B4 阶段通过时把注入过的经验 ok +1（red → green 同一夹具）
  C5 candidates 的 support/成功率门槛 · C6 write 幂等
  D7 check_min_chars 三例 · D8 json_api 字段映射三例 · D9 crossref 源配置
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sa2 import fetch, parsers
from sa2.core.gate import Declaration, check_min_chars
from sa2.core.judge import Judge
from sa2.core.ledger import Ledger
from sa2.forge import criteria as fc
from sa2.forge import dims as fd
from sa2.forge.org import OrgPlan, Role, Stage
from sa2.loop.pdca import PDCA
from sa2.memory import evolution, lessons

HEADING = "## 起草要点"
KEYWORD = "关键词甲"
FIX = "补上缺失章节再交"


def make_judge() -> Judge:
    """真实 Judge + 真实判据：阶段门 = 章节 + 关键词。"""
    judge = Judge(authority=("leader",))
    crits = (
        fc.tested(fc.propose_sections("起草齐全", [HEADING], ("correctness",))),
        fc.tested(fc.propose_content("起草要素", [KEYWORD], ("correctness",))),
    )
    for crit in crits:
        judge.register(crit, proposer="leader")
    return judge


def make_plan() -> OrgPlan:
    role = Role(name="执行", kind="executor", duty="写正文", criteria="齐全", budget=50)
    stage = Stage(name="起草", output="草稿", roles=("执行",),
                  gate_criteria=("起草齐全", "起草要素"))
    return OrgPlan(goal="写一段话", roles=(role,), stages=(stage,))


def make_decl() -> Declaration:
    return Declaration(goal="写一段话", dims=("correctness",),
                       criteria=("起草齐全", "起草要素"), budget_tokens=100_000)


class ClassifyTest(unittest.TestCase):
    """A1：问题文本 → failure_kind。"""

    def test_three_categories(self):
        self.assertEqual(
            lessons.classify(["命令退出码 1：章节正文过短：## 一 只有 12 字"]),
            "too_short")
        self.assertEqual(lessons.classify(["引用 1 条 < 要求 3 条"]),
                         "unsigned_reference")
        # 空问题与无匹配文本都落兜底类，不是抛异常
        self.assertEqual(lessons.classify([]), "criteria_rejected")
        self.assertEqual(lessons.classify(["完全不相干的一句话"]), "criteria_rejected")


class BumpTest(unittest.TestCase):
    """A2：bump 只改命中行，返回改到的条数。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "lessons.jsonl"
        self.lesson = lessons.add(self.path, "正文过短就先补够再交",
                                  {"failure_kind": "too_short"}, fix="补够再交")

    def tearDown(self):
        self.tmp.cleanup()

    def test_bump_injected_from_zero_to_one(self):
        self.assertEqual(lessons.bump(self.path, [self.lesson["id"]], "injected"), 1)
        stored = lessons.all(self.path)[0]
        self.assertEqual(stored["stats"]["injected"], 1)

    def test_unknown_id_and_illegal_field_return_zero(self):
        self.assertEqual(lessons.bump(self.path, ["Lnope"], "injected"), 0)
        self.assertEqual(lessons.bump(self.path, [self.lesson["id"]], "hits"), 0)
        # 两次都没写回：统计保持为 0
        self.assertEqual(lessons.all(self.path)[0]["stats"]["injected"], 0)


class PdcaLessonTest(unittest.TestCase):
    """B3/B4：PDCA 真的把经验注入 feedback 并回写统计。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.lesson_path = self.root / "lessons.jsonl"
        self.lesson = lessons.add(
            self.lesson_path, "遇到缺章节时先按结构补齐再交",
            {"failure_kind": "missing_heading"}, fix=FIX)
        self.seen: list[dict] = []

    def tearDown(self):
        self.tmp.cleanup()

    def _pdca(self, produce, attempts: int = 2) -> PDCA:
        return PDCA(make_judge(), Ledger(self.root / "ledger.jsonl"), make_plan(),
                    produce, fd.VOCAB, max_stage_attempts=attempts,
                    lesson_path=self.lesson_path)

    def _run(self, produce, attempts: int = 2) -> dict:
        return self._pdca(produce, attempts).run(make_decl())

    def _stored(self) -> dict:
        rows = [row for row in lessons.all(self.lesson_path)
                if row["id"] == self.lesson["id"]]
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_rejection_injects_lesson_fix_and_records_event(self):
        """B3：第一次被拒后，第二次派活的 feedback 带上 fix；injected 从 0 变 1。"""

        def produce(role, stage, upstream, attempt, feedback="", requirements=""):
            self.seen.append({"stage": stage, "attempt": attempt, "feedback": feedback})
            if attempt == 1:
                # 章节与关键词都缺 → classify 命中 missing_heading
                return "只有正文，没有章节标题"
            # 章节补上、关键词仍缺 → 第二次拒收归到 criteria_rejected，不再注入同一条经验
            return f"{HEADING}\n正文"

        report = self._run(produce)

        self.assertFalse(report["passed"], report)
        retries = [item for item in self.seen
                   if item["stage"] == "起草" and item["attempt"] == 2]
        self.assertEqual(len(retries), 1)
        self.assertIn(FIX, retries[0]["feedback"], "重做提示里没带经验对策")

        events = [e for e in Ledger(self.root / "ledger.jsonl").read()
                  if e["kind"] == "lesson"]
        self.assertEqual(len(events), 1, events)
        self.assertIn(self.lesson["id"], events[0]["payload"]["ids"])
        self.assertEqual(self._stored()["stats"]["injected"], 1)

    def test_stage_ok_counts_lesson_as_successful(self):
        """B4：同一夹具第二次通过阶段门 → 注入过的经验 ok +1。"""

        def produce(role, stage, upstream, attempt, feedback="", requirements=""):
            self.seen.append({"stage": stage, "attempt": attempt, "feedback": feedback})
            if attempt == 1:
                return "只有正文，没有章节标题"
            return f"{HEADING}\n正文\n{KEYWORD}"

        report = self._run(produce)

        self.assertTrue(report["passed"], report)
        stored = self._stored()
        self.assertEqual(stored["stats"]["injected"], 1)
        self.assertEqual(stored["stats"]["ok"], 1, "stage_ok 没把注入过的经验回写 ok")


class EvolutionTest(unittest.TestCase):
    """C5/C6：经验够格才产候选；候选写入幂等。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _lessons(self, ok: int, name: str = "lessons.jsonl") -> list[dict]:
        path = self.root / name
        for text in ("缺章节时先补齐", "缺章节时对照结构逐条检查"):
            lessons.add(path, text, {"failure_kind": "missing_heading"}, fix="补齐")
        rows = lessons.all(path)
        for row in rows:
            row["stats"] = {"injected": 2, "ok": ok, "bad": 0}
        return rows

    def test_candidates_require_support_and_success_rate(self):
        found = evolution.candidates(self._lessons(ok=2, name="ok.jsonl"))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["status"], "proposed")
        self.assertEqual(found[0]["proposal"]["kind"], "prompt_note")
        self.assertEqual(found[0]["support"], 2)
        # 成功率降到 0：同样 2 条支持经验也不再出候选
        self.assertEqual(evolution.candidates(self._lessons(ok=0, name="bad.jsonl")), [])

    def test_write_appends_once_per_candidate(self):
        found = evolution.candidates(self._lessons(ok=2))
        out = self.root / "candidates.jsonl"
        self.assertEqual(evolution.write(out, found), 1)
        self.assertEqual(len(out.read_text(encoding="utf-8").splitlines()), 1)
        self.assertEqual(evolution.write(out, found), 0, "同样的候选被重复写入")
        self.assertEqual(len(out.read_text(encoding="utf-8").splitlines()), 1)


class MinCharsTest(unittest.TestCase):
    """D7：交付体量门。"""

    def test_min_chars(self):
        problems = check_min_chars("短", {"min": 10})
        self.assertEqual(len(problems), 1)
        self.assertIn("只有 1 字", problems[0], "问题里要带实际字数")
        self.assertIn("要求 10 字", problems[0])
        self.assertEqual(check_min_chars("足够长的一段正文", {"min": 3}), [])
        self.assertEqual(check_min_chars("短", {}), [])


SAMPLE = json.dumps({
    "message": {"items": [{
        "DOI": "10.1/abc",
        "title": ["标题甲", "副标题"],
        "created": {"date-parts": [[2024, 5, 1]]},
        "URL": "https://doi.org/10.1/abc",
        "abstract": "这是摘要",
    }]},
}, ensure_ascii=False)

FIELDS = {"fields": {
    "items": "message.items", "id": "DOI", "title": "title.0",
    "published": "created.date-parts.0.0", "url": "URL", "summary": "abstract",
}}


class JsonApiTest(unittest.TestCase):
    """D8：通用 JSON API 解析器只认 fields 映射。"""

    def test_fields_mapping(self):
        entries = parsers.parse("json_api", SAMPLE, FIELDS)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "标题甲")       # title 列表取第 0 个
        self.assertEqual(entries[0]["published"], "2024")      # date-parts 取年份
        self.assertEqual(entries[0]["id"], "10.1/abc")
        self.assertEqual(entries[0]["url"], "https://doi.org/10.1/abc")
        self.assertEqual(entries[0]["summary"], "这是摘要")

    def test_empty_items_raises(self):
        empty = json.dumps({"message": {"items": []}})
        with self.assertRaises(parsers.ParseError):
            parsers.parse("json_api", empty, FIELDS)

    def test_missing_fields_raises(self):
        with self.assertRaises(parsers.ParseError):
            parsers.parse("json_api", SAMPLE)


class FetchConfigTest(unittest.TestCase):
    """D9：只读源配置，不取数。"""

    def test_crossref_registered_as_json_api(self):
        self.assertIn("crossref", fetch.source_names())
        cfg = fetch.config("crossref")
        self.assertEqual(cfg["parser"], "json_api")
        self.assertEqual(cfg["fields"]["items"], "message.items")


if __name__ == "__main__":
    unittest.main()