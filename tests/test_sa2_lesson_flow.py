"""sa2 经验流转与跨轮依赖（S7 / S10）的回归测试。

只新增测试，不改实现；所有写操作落在 `tempfile.TemporaryDirectory()`；
不碰网络，不读写真实 `~/xm-runs`。

与题面的对应关系：
  A1 交付门判红 → 经验真的写进 jsonl（origin=delivery_gate），
     并被重做最后一阶段的 feedback 读到（stats.injected +1），账本 redo_from_delivery 恰 1 条
  A2 lessons.add 按 id 去重：同 text+when 连写两次仍 1 行、返回同一个 id
  B3 Backlog.pick() 跳过前置未完成的目标，waiting() 列出被挡住的
  B4 依赖关系跨实例持久化（第二个 Backlog 读同一文件）
  B5 source="self" 且 approved=False 的目标仍不可领取（原有红线不被依赖逻辑破坏）

行为来源（读实现确认，不是按印象写）：
  - `sa2/loop/pdca.py` 的 `run()`：交付门红时先 `lessonbook.add(..., origin="delivery_gate")`，
    再回退最后一阶段一次并记 `redo_from_delivery`；`_feedback()` 按 failure_kind
    `match()` 到刚写的经验并 `bump(..., "injected")`。
  - `sa2/memory/lessons.py` 的 `add()`：同 id 直接返回已存在的那一行，不追加。
  - `sa2/autonomy/backlog.py` 的 `pick()`/`waiting()`：按 `depends_on` 与 `done_ids()` 判。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sa2.autonomy.backlog import Backlog, Goal
from sa2.core.gate import Declaration
from sa2.core.judge import Judge
from sa2.core.ledger import Ledger
from sa2.forge import criteria as fc
from sa2.forge import dims as fd
from sa2.forge.org import OrgPlan, Role, Stage
from sa2.knowledge import load
from sa2.loop.pdca import PDCA
from sa2.memory import lessons

# 阶段门的标题：生产方每次都写它，所以阶段门恒绿。
STAGE_HEADING = "## 草稿"
# 交付门的标题：生产方从不写它，所以交付门恒红。
DELIVERY_HEADING = "## 交付结论"
DEADLINE_FIX = "按交付门拒收原因修最后一阶段，而不是整篇重写"


def make_judge() -> Judge:
    """真实 Judge + 真实判据（都过三反例自测），两条 sections 判据。"""
    judge = Judge(authority=("leader",))
    for crit in (
        fc.tested(fc.propose_sections("起草齐全", [STAGE_HEADING], ("correctness",))),
        fc.tested(fc.propose_sections("交付齐全", [DELIVERY_HEADING], ("correctness",))),
    ):
        judge.register(crit, proposer="leader")
    return judge


def make_plan() -> OrgPlan:
    """单阶段：它必须先在阶段门通过（进入 before），交付门回退才有得重做。"""
    role = Role(name="执笔", kind="executor", duty="写草稿", criteria="章节齐全", budget=50)
    stage = Stage(name="起草", output="草稿", roles=("执笔",),
                  gate_criteria=("起草齐全",))
    return OrgPlan(goal="写一份带交付结论的稿子", roles=(role,), stages=(stage,))


def make_decl() -> Declaration:
    return Declaration(goal="写一份带交付结论的稿子", dims=("correctness",),
                       criteria=("交付齐全",), budget_tokens=100_000)


class DeliveryGateLessonTest(unittest.TestCase):
    """A1：交付门失败是一次失败，必须进经验库，且当场被重做的 feedback 读到。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.lesson_path = self.root / "lessons.jsonl"
        self.feedback_seen: list[str] = []

    def tearDown(self):
        self.tmp.cleanup()

    def _produce(self, role, stage, upstream, attempt, feedback="", requirements=""):
        # 每次产出都只有阶段门要求的章节，永远缺交付门要求的章节 → 交付门恒红
        self.feedback_seen.append(feedback)
        return f"{STAGE_HEADING}\n正文内容"

    def test_delivery_gate_failure_writes_lesson_and_injects_it(self):
        report = PDCA(make_judge(), Ledger(self.root / "ledger.jsonl"), make_plan(),
                      self._produce, fd.VOCAB, lesson_path=self.lesson_path).run(make_decl())

        # 阶段门恒绿、交付门恒红：整体必须判红
        self.assertFalse(report["passed"], report)

        # ① 文件恰 1 行：交付门只写一条经验，重做没有再写第二条
        lines = [ln for ln in self.lesson_path.read_text(encoding="utf-8").splitlines()
                 if ln.strip()]
        self.assertEqual(len(lines), 1, lines)

        rows = lessons.all(self.lesson_path)
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]

        # ② 来源与正文
        self.assertEqual(row["origin"], "delivery_gate")
        self.assertTrue(row["text"].strip(), "经验正文不能为空")
        self.assertEqual(row["fix"], DEADLINE_FIX)

        # ③ when 的键与值都必须落在 vocab events 的枚举里（不许现编条件）
        events = load("vocab")["events"]
        self.assertTrue(row["when"], "when 不能为空")
        for key, value in row["when"].items():
            self.assertIn(key, events, f"when 的键未登记：{key}")
            self.assertIn(value, events[key], f"when.{key} 的值不在枚举里：{value!r}")

        # ④ 当场被重做那一阶段的 feedback 读到：injected +1，且对策真的进了 feedback
        self.assertGreaterEqual(row["stats"]["injected"], 1, row)
        self.assertGreaterEqual(len(self.feedback_seen), 2,
                                "交付门回退应产生第二次派活")
        self.assertIn(DEADLINE_FIX, self.feedback_seen[1],
                      "重做的 feedback 没带上刚写的经验")

        # ⑤ 账本里恰好一条交付门回退
        self.assertEqual(Ledger(self.root / "ledger.jsonl").count("redo_from_delivery"), 1)


class LessonDedupTest(unittest.TestCase):
    """A2：add 按 id 去重，同一条经验不重复追加。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "lessons.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_text_and_when_is_not_appended_twice(self):
        first = lessons.add(self.path, text="同一句",
                            when={"failure_kind": "missing_heading"}, fix="x")
        second = lessons.add(self.path, text="同一句",
                             when={"failure_kind": "missing_heading"}, fix="x")

        self.assertEqual(first["id"], second["id"], "同 text+when 应算出同一个 id")
        lines = [ln for ln in self.path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1, "重复的经验被追加了")
        self.assertEqual(len(lessons.all(self.path)), 1)


def goal_a(**overrides) -> Goal:
    kw = dict(text="目标 A", dims=("correctness",), criteria=("判据甲",),
              budget_tokens=1000)
    kw.update(overrides)
    return Goal(**kw)


def goal_b(a: Goal) -> Goal:
    """B 依赖 A：A 没 done，B 就不该被领取。"""
    return Goal(text="目标 B", dims=("correctness",), criteria=("判据乙",),
                budget_tokens=1000, depends_on=(a.gid(),))


class BacklogDependencyTest(unittest.TestCase):
    """B3/B4/B5：跨轮依赖、持久化、以及「自提未批准不可领取」的红线。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "backlog.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_pick_skips_blocked_goal_and_waiting_lists_it(self):
        backlog = Backlog(self.path)
        a = backlog.add(goal_a())
        b = backlog.add(goal_b(a))

        picked = backlog.pick()
        self.assertIsNotNone(picked)
        self.assertEqual(picked.gid(), a.gid(), "无依赖的 A 应可领取")
        self.assertEqual([g.gid() for g in backlog.waiting()], [b.gid()],
                         "waiting() 只该列出被前置挡住的 B")

        backlog.mark(a, "done")

        picked = backlog.pick()
        self.assertIsNotNone(picked)
        self.assertEqual(picked.gid(), b.gid(), "A 完成后 B 应可领取")
        self.assertEqual(backlog.waiting(), [])

    def test_dependency_survives_a_second_backlog_instance(self):
        first = Backlog(self.path)
        a = first.add(goal_a())
        b = first.add(goal_b(a))

        second = Backlog(self.path)
        self.assertEqual([g.gid() for g in second.waiting()], [b.gid()],
                         "新实例读同一文件后依赖丢了")
        self.assertEqual(second.pick().gid(), a.gid())

        second.mark(a, "done")

        third = Backlog(self.path)
        self.assertEqual(third.pick().gid(), b.gid(), "A 完成后 B 仍被挡住")
        self.assertEqual(third.waiting(), [])

    def test_unapproved_self_goal_cannot_be_picked(self):
        backlog = Backlog(self.path)
        a = backlog.add(goal_a(source="self", approved=False))
        b = backlog.add(goal_b(a))

        self.assertIsNone(backlog.pick(),
                          "self 且未批准的 A 不可领取，前置未完成的 B 也不可领取")
        self.assertEqual([g.gid() for g in backlog.waiting()], [b.gid()],
                         "B 仍应作为被挡住的目标出现")


if __name__ == "__main__":
    unittest.main()