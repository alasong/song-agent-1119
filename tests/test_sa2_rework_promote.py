"""S9 交付门回退 / S8 候选提升 / S7 经验写入 / S12 编制额度 —— 回归测试。

只新增测试，不改实现；所有写操作落 `tempfile.TemporaryDirectory()`；不发任何网络请求。
与题面的对应关系：
  A 交付门回退（S9）  A1 回退一次且仍红不许绿 · A2 回退是替换不是叠加 · A3 只回退一次
  B 候选提升（S8）    B4 prompt_note 幂等 · B5 criterion 登记 · B6 proposer 红线 · B7 非法形态
  C 经验写入（S7）    C8 when 落在 vocab 枚举内、text 非空、injected 回写
  D 编制额度（S12）   D9 max_tokens 透传/缺省不传 · D10 8 角色 4 阶段可解析
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sa2.core.gate import Declaration
from sa2.core.judge import Judge, Unauthorized
from sa2.core.ledger import Ledger
from sa2.forge import criteria as fc
from sa2.forge import dims as fd
from sa2.forge import org as fo
from sa2.forge.org import OrgPlan, Role, Stage
from sa2.knowledge import load
from sa2.loop.pdca import PDCA
from sa2.memory import lessons
from scripts import candidate_promote

STAGE_HEADING = "## 作业"
STAGE_GATE = "阶段合格"
DELIVERY_GATE = "交付合格"


def _registered(judge: Judge, *crits) -> Judge:
    for crit in crits:
        judge.register(crit, proposer="leader")
    return judge


def _plan(gate: str) -> OrgPlan:
    """单角色单阶段的真实编制：派活次数只由「阶段 + 一次回退」决定。"""
    role = Role(name="写手", kind="executor", duty="写正文", criteria="正文完整", budget=50)
    stage = Stage(name="定稿", output="成稿", roles=("写手",), gate_criteria=(gate,))
    return OrgPlan(goal="写一份报告", roles=(role,), stages=(stage,))


def _decl(criteria) -> Declaration:
    return Declaration(goal="写一份报告", dims=("correctness",),
                       criteria=tuple(criteria), budget_tokens=100_000)


class DeliveryReworkTest(unittest.TestCase):
    """A 交付门回退（S9）：`run()` 在交付门红时回退最后一阶段，且只回退一次。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_delivery_red_falls_back_once_and_stays_red(self):
        """A1：阶段门恒绿、交付门恒红 → 派活 2 次，回退带交付门原因，仍判 False。"""
        judge = _registered(
            Judge(authority=("leader",)),
            fc.tested(fc.propose_sections(STAGE_GATE, [STAGE_HEADING], ("correctness",))),
            fc.tested(fc.propose_sections(DELIVERY_GATE, ["## 交付章"], ("correctness",))),
        )
        ledger = Ledger(self.root / "ledger.jsonl")
        seen: list[dict] = []

        def produce(role, stage, upstream, attempt, feedback="", requirements=""):
            seen.append({"role": role.name, "stage": stage, "attempt": attempt,
                         "feedback": feedback})
            # 恒缺 `## 交付章`：阶段门（sections 只要求「## 作业」）恒绿，交付门恒红。
            return f"{STAGE_HEADING}\n\n初稿正文，没有交付章节。"

        report = PDCA(judge, ledger, _plan(STAGE_GATE), produce, fd.VOCAB).run(
            _decl((STAGE_GATE, DELIVERY_GATE)))

        self.assertIs(report["passed"], False, report)
        self.assertEqual(report["dispatches"], 2, report)
        self.assertEqual(len(seen), 2, seen)
        self.assertEqual(seen[1]["attempt"], 2)
        # 回退必须带着交付门的拒收原因，否则是盲重做
        self.assertTrue(seen[1]["feedback"], "第二次派活没带 feedback")
        self.assertIn("缺章节：## 交付章", seen[1]["feedback"])
        self.assertEqual(ledger.count("redo_from_delivery"), 1)
        redo = [e for e in ledger.read() if e["kind"] == "redo_from_delivery"][0]
        self.assertIn("缺章节：## 交付章", "；".join(redo["payload"]["problems"]))
        # 重做后仍红：不许因为「已经重做过」就放绿
        self.assertEqual(ledger.count("delivery"), 1)
        self.assertFalse([e for e in ledger.read()
                          if e["kind"] == "delivery"][0]["payload"]["passed"])

    def test_rework_replaces_last_stage_instead_of_appending(self):
        """A2：交付门第一次红、第二次绿 → passed，且必需标题只出现 1 次。

        阶段门刻意用字面 regex（而不是 sections）：`_produce_stage` 的 `_trim`
        只保留阶段 sections 门允许的 `## ` 标题，回退产出里的交付标题会被裁掉；
        这里要测的是「回退替换」本身，所以让阶段门不产生裁剪边界。
        """
        judge = _registered(
            Judge(authority=("leader",)),
            fc.tested(fc.propose_content(STAGE_GATE, ["作业"], ("correctness",))),
            fc.tested(fc.propose_sections(DELIVERY_GATE, ["## 交付章"], ("correctness",))),
        )
        ledger = Ledger(self.root / "ledger.jsonl")
        seen: list[dict] = []

        def produce(role, stage, upstream, attempt, feedback="", requirements=""):
            seen.append({"attempt": attempt, "feedback": feedback})
            if attempt == 1:
                return f"{STAGE_HEADING}\n\n初稿，缺交付标题。"
            return f"{STAGE_HEADING}\n\n## 交付章\n\n定稿正文。"

        report = PDCA(judge, ledger, _plan(STAGE_GATE), produce, fd.VOCAB).run(
            _decl((STAGE_GATE, DELIVERY_GATE)))

        self.assertIs(report["passed"], True, report)
        self.assertEqual(report["dispatches"], 2, report)
        self.assertEqual(ledger.count("redo_from_delivery"), 1)
        # 回退是「替换最后一阶段」：正文里这个标题恰好一份，不是叠加成两份
        self.assertEqual(report["text"].count("## 交付章"), 1, report["text"])

    def test_rework_happens_at_most_once(self):
        """A3：交付门永远红 → 派活封顶 2 次，不许无限回退。"""
        judge = _registered(
            Judge(authority=("leader",)),
            fc.tested(fc.propose_sections(STAGE_GATE, [STAGE_HEADING], ("correctness",))),
            fc.tested(fc.propose_sections(DELIVERY_GATE, ["## 不会出现的章"], ("correctness",))),
        )
        ledger = Ledger(self.root / "ledger.jsonl")
        attempts: list[int] = []

        def produce(role, stage, upstream, attempt, feedback="", requirements=""):
            attempts.append(attempt)
            return f"{STAGE_HEADING}\n\n正文。"

        report = PDCA(judge, ledger, _plan(STAGE_GATE), produce, fd.VOCAB).run(
            _decl((STAGE_GATE, DELIVERY_GATE)))

        self.assertIs(report["passed"], False)
        self.assertEqual(report["dispatches"], 2, report)
        self.assertLessEqual(report["dispatches"], 2)
        self.assertEqual(attempts, [1, 2], "回退后不许再派第三次活")
        self.assertEqual(ledger.count("redo_from_delivery"), 1)


class CandidatePromoteTest(unittest.TestCase):
    """B 候选提升（S8）：两种形态各走一条路，判定权在 register 里守。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _criterion_spec() -> dict:
        return {"name": "候选判据", "kind": "regex",
                "spec": {"patterns": ["x"], "mode": "any"},
                "dims": [], "self_tested": True, "scope": "delivery"}

    def _judge(self) -> Judge:
        return Judge(authority=("leader", "verifier"),
                     path=self.root / "criteria.json",
                     history=self.root / "criteria-history.jsonl")

    def test_prompt_note_written_once(self):
        """B4：prompt_note 写进临时 seed 同一行号只写一次。"""
        seed = self.root / "seed.jsonl"
        cand = {"when": {"failure_kind": "missing_heading"},
                "proposal": {"kind": "prompt_note", "text": "缺章节时先按结构补齐"}}

        first = candidate_promote.promote(cand, "leader", seed=seed)
        self.assertIs(first["written"], True)
        self.assertEqual(len(seed.read_text(encoding="utf-8").splitlines()), 1)

        second = candidate_promote.promote(cand, "leader", seed=seed)
        self.assertIs(second["written"], False)
        self.assertEqual(len(seed.read_text(encoding="utf-8").splitlines()), 1,
                         "同一条候选被写了第二遍")
        self.assertEqual(second["target"], str(seed))

    def test_criterion_registered_with_authorized_proposer(self):
        """B5：criterion 走真实 Judge.register 登记成功，形态就是候选里写的。"""
        judge = self._judge()
        cand = {"proposal": {"kind": "criterion", "spec": self._criterion_spec()}}

        done = candidate_promote.promote(cand, "leader", judge=judge,
                                         seed=self.root / "seed.jsonl")

        self.assertIs(done["written"], True)
        self.assertIn("候选判据", judge.names())
        self.assertEqual(judge.get("候选判据").kind, "regex")
        # 登记确实落盘（不是只活在内存里）
        persisted = json.loads((self.root / "criteria.json").read_text(encoding="utf-8"))
        self.assertIn("候选判据", [row["name"] for row in persisted])

    def test_generator_cannot_register_criterion(self):
        """B6：生成方不在 authority，register 抛 Unauthorized，判据库保持干净。"""
        judge = self._judge()
        cand = {"proposal": {"kind": "criterion", "spec": self._criterion_spec()}}

        with self.assertRaises(Unauthorized):
            candidate_promote.promote(cand, "generator", judge=judge,
                                      seed=self.root / "seed.jsonl")

        self.assertNotIn("候选判据", judge.names())

    def test_illegal_shapes_raise_value_error(self):
        """B7：不认识的形态与空正文都在写之前抛 ValueError。"""
        seed = self.root / "seed.jsonl"
        with self.assertRaises(ValueError):
            candidate_promote.promote({"proposal": {"kind": "magic"}}, "leader", seed=seed)
        with self.assertRaises(ValueError):
            candidate_promote.promote(
                {"proposal": {"kind": "prompt_note", "text": "   "}}, "leader", seed=seed)
        self.assertFalse(seed.exists(), "非法候选不该留下写了一半的文件")


class LessonWriteTest(unittest.TestCase):
    """C 经验写入（S7）：被拒时注入的经验必须是「条件 + 对策」，不是空壳。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_rejected_stage_injects_lesson_with_registered_condition(self):
        """C8：阶段门恒红触发注入；落盘每条经验的 when 落在 vocab.events 枚举内。"""
        lesson_path = self.root / "lessons.jsonl"
        lessons.add(lesson_path, "补章节", {"failure_kind": "missing_heading"},
                    fix="把缺失的 ## 标题补上再交")

        judge = _registered(
            Judge(authority=("leader",)),
            fc.tested(fc.propose_sections(STAGE_GATE, ["## 必需章"], ("correctness",))),
        )
        ledger = Ledger(self.root / "ledger.jsonl")

        def produce(role, stage, upstream, attempt, feedback="", requirements=""):
            return "只有正文，没有标题"        # 缺章节 → classify=missing_heading

        report = PDCA(judge, ledger, _plan(STAGE_GATE), produce, fd.VOCAB,
                      lesson_path=lesson_path).run(_decl((STAGE_GATE,)))

        self.assertIs(report["passed"], False, report)
        self.assertEqual(report["dispatches"], 2)    # 两次尝试都被阶段门拒
        self.assertGreaterEqual(ledger.count("lesson"), 1, "没有落 lesson 事件")

        events = load("vocab")["events"]
        rows = lessons.all(lesson_path)
        self.assertEqual(len(rows), 1, rows)
        for row in rows:
            self.assertTrue(str(row.get("text") or "").strip(), "经验正文为空")
            self.assertTrue(row.get("when"), "经验条件为空")
            for key, value in row["when"].items():
                self.assertIn(key, events, f"when 的键 {key!r} 不在 vocab.events")
                self.assertIn(value, events[key],
                              f"when.{key}={value!r} 不在 {events[key]} 枚举内")
            self.assertGreaterEqual(int(row["stats"]["injected"]), 1,
                                    "注入统计没回写：经验等于没被用过")


class _RecordingLLM:
    """假 llm：只记录收到的 kwargs，不联网。"""

    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[dict] = []

    def __call__(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return self.reply


class OrgBudgetTest(unittest.TestCase):
    """D 编制额度（S12）：max_tokens 只透传不硬编码；解析器不受角色数上限牵连。"""

    ORG = json.dumps({
        "roles": [
            {"name": "规划", "kind": "planner", "duty": "拆解目标", "criteria": "可验收", "budget": 10},
            {"name": "执行", "kind": "executor", "duty": "写正文", "criteria": "结构完整", "budget": 10},
            {"name": "验证", "kind": "verifier", "duty": "只判不写", "criteria": "有结论", "budget": 10},
        ],
        "stages": [
            {"name": "起草", "output": "草稿", "roles": ["规划", "执行"], "gate_criteria": ["门甲"]},
            {"name": "定稿", "output": "成稿", "roles": ["执行", "验证"], "gate_criteria": ["门乙"]},
        ],
    }, ensure_ascii=False)

    def test_max_tokens_forwarded_to_llm(self):
        """D9a：给了 max_tokens 就原样传给 llm，不吞掉。"""
        llm = _RecordingLLM(self.ORG)
        plan = fo.plan_org("写报告", llm, criteria=("门甲", "门乙"),
                           attempts=1, max_tokens=6000)

        self.assertEqual(len(llm.calls), 1, llm.calls)
        self.assertEqual(llm.calls[0]["kwargs"].get("max_tokens"), 6000)
        self.assertEqual(len(plan.roles), 3)

    def test_no_max_tokens_kwarg_by_default(self):
        """D9b：不给 max_tokens 就不传这个 kwarg（老调用方签名兼容）。"""
        llm = _RecordingLLM(self.ORG)
        fo.plan_org("写报告", llm, criteria=("门甲", "门乙"), attempts=1)

        self.assertNotIn("max_tokens", llm.calls[0]["kwargs"])

    def test_eight_roles_four_stages_parse_fine(self):
        """D10：8 角色 / 4 阶段的合法 JSON 能解析——额度问题不是解析器上限。"""
        roles = [
            {"name": f"角色{i}", "kind": kind, "duty": f"只做第{i}件事",
             "criteria": f"第{i}件事可判", "budget": 1000}
            for i, kind in enumerate(
                ("planner", "executor", "expert", "verifier",
                 "curator", "executor", "expert", "planner"), 1)
        ]
        stages = [
            {"name": "阶段一", "output": "一稿", "roles": ["角色1", "角色2", "角色3"],
             "gate_criteria": ["门一"]},
            {"name": "阶段二", "output": "二稿", "roles": ["角色4", "角色5", "角色6"],
             "gate_criteria": ["门二"]},
            {"name": "阶段三", "output": "三稿", "roles": ["角色7", "角色8"],
             "gate_criteria": ["门三"]},
            {"name": "阶段四", "output": "定稿", "roles": ["角色1", "角色4"],
             "gate_criteria": ["门四"]},
        ]
        raw = json.dumps({"roles": roles, "stages": stages}, ensure_ascii=False)

        plan = fo.parse_plan("写一份大报告", raw)

        self.assertEqual(len(plan.roles), 8)
        self.assertEqual(len(plan.stages), 4)
        self.assertLess(plan.dispatches(), len(plan.roles) * len(plan.stages),
                        "8 角色 4 阶段被当成了全连接")
        assigned = {name for stage in plan.stages for name in stage.roles}
        self.assertEqual(assigned, {r.name for r in plan.roles})


if __name__ == "__main__":
    unittest.main()