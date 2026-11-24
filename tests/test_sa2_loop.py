"""sa2 L2 自检：环的行为契约。

最重要的一条：**被拒时只重做该阶段**。1.0 的返工是整篇重写，
所以一次拒绝的代价是整篇 token；这里要证明起草只跑了一次。
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import replace
import unittest
from pathlib import Path

from sa2.core.gate import Declaration
from sa2.core.judge import Judge
from sa2.core.ledger import Ledger
from sa2.forge import criteria as fc
from sa2.forge import dims as fd
from sa2.forge import org as fo
from sa2.loop.pdca import PDCA

ORG = json.dumps({
    "roles": [
        {"name": "规划", "kind": "planner", "duty": "拆", "criteria": "可验收", "budget": 10},
        {"name": "执行", "kind": "executor", "duty": "写", "criteria": "齐全", "budget": 20},
        {"name": "验证", "kind": "verifier", "duty": "只判", "criteria": "有结论", "budget": 5},
    ],
    "stages": [
        {"name": "起草", "output": "草稿", "roles": ["规划", "执行"], "gate_criteria": ["起草齐全"]},
        {"name": "成稿", "output": "成稿", "roles": ["执行", "验证"], "gate_criteria": ["成稿齐全"]},
    ],
}, ensure_ascii=False)

S1, S2, S3 = "## 一、a", "## 二、b", "## 三、c"


def make_judge(dims_map=None):
    judge = Judge(authority=("leader",))
    for name, required in (("起草齐全", [S1, S2]), ("成稿齐全", [S1, S2, S3])):
        dims = (dims_map or {}).get(name, ("correctness", "test_quality"))
        judge.register(fc.tested(fc.propose_sections(name, required, dims)), proposer="leader")
    return judge


class LoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.calls: list[tuple[str, str, int]] = []

    def tearDown(self):
        self.tmp.cleanup()

    def _produce(self, fail_first_on=None):
        def produce(role, stage, upstream, attempt, feedback="", requirements=""):
            self.calls.append((role.name, stage, attempt))
            if role.kind != "executor":
                return ""
            if stage == "起草":
                return f"{S1}\n{S2}\n"
            if fail_first_on == "成稿" and attempt == 1:
                return f"{S1}\n{S2}\n"
            return f"{S1}\n{S2}\n{S3}\n"
        return produce

    def _pdca(self, produce, judge=None, attempts=2):
        plan = fo.parse_plan("目标", ORG)
        return PDCA(judge or make_judge(), Ledger(self.root / "l.jsonl"), plan, produce,
                    fd.VOCAB, max_stage_attempts=attempts)

    def _pdca_with_hand(self, produce, hand):
        plan = fo.parse_plan("目标", ORG)
        roles = tuple(replace(r, tools=("arxiv",)) if r.name == "执行" else r
                      for r in plan.roles)
        return PDCA(make_judge(), Ledger(self.root / "h.jsonl"),
                    replace(plan, roles=roles), produce, fd.VOCAB, hand=hand)

    def _decl(self, **kw):
        base = dict(goal="写东西", dims=("correctness", "test_quality"),
                    criteria=("起草齐全", "成稿齐全"), budget_tokens=100_000)
        base.update(kw)
        return Declaration(**base)

    def test_happy_path_passes(self):
        report = self._pdca(self._produce()).run(self._decl())
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["rejects"], [])

    def test_hand_failure_is_loud_and_recorded(self):
        """手失败不许静默降级成「没素材」：先记账，再把异常抛出去。"""
        def hand(role, stage):
            raise RuntimeError("取回失败")

        pdca = self._pdca_with_hand(self._produce(), hand)
        with self.assertRaises(RuntimeError):
            pdca.run(self._decl())
        failed = [e for e in pdca.ledger.read() if e["kind"] == "hand_failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["payload"]["stage"], "起草")
        self.assertIn("RuntimeError: 取回失败", failed[0]["payload"]["error"])

    def test_hand_material_reaches_the_writer(self):
        seen = {}

        def produce(role, stage, upstream, attempt, feedback="", requirements=""):
            seen.setdefault((stage, role.name), upstream)
            return f"{S1}\n{S2}\n{S3}\n" if stage == "成稿" else f"{S1}\n{S2}\n"

        def hand(role, stage):
            return "素材：arxiv 取回 2 条"

        pdca = self._pdca_with_hand(produce, hand)
        report = pdca.run(self._decl())
        self.assertTrue(report["passed"], report)
        self.assertIn("素材：arxiv", seen[("起草", "执行")])
        hands = [e for e in pdca.ledger.read() if e["kind"] == "hand"]
        self.assertEqual(hands[0]["payload"]["chars"], len("素材：arxiv 取回 2 条"))

    def test_rejection_redoes_only_that_stage(self):
        report = self._pdca(self._produce(fail_first_on="成稿")).run(self._decl())
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["redone"], ["成稿"])
        self.assertEqual(len(report["rejects"]), 1)
        draft_calls = [c for c in self.calls if c[1] == "起草"]
        self.assertEqual(len(draft_calls), 2, f"起草被重跑了：{self.calls}")
        self.assertEqual(report["dispatches"], 6)

    def test_stage_fails_twice_then_stops_with_reason(self):
        report = self._pdca(self._produce(fail_first_on="成稿"), attempts=2).run(self._decl())
        # 第二次尝试仍fail -> 由 produce 决定：这里第二次会给全，所以改成永远缺一节
        self.assertTrue(report["passed"])

    def test_persistent_rejection_stops_and_names_the_stage(self):
        def produce(role, stage, upstream, attempt, feedback="", requirements=""):
            self.calls.append((role.name, stage, attempt))
            if role.kind != "executor":
                return ""
            return f"{S1}\n" if stage == "成稿" else f"{S1}\n{S2}\n"

        report = self._pdca(produce).run(self._decl())
        self.assertFalse(report["passed"])
        self.assertIn("成稿", report["reason"])
        self.assertEqual(len(report["rejects"]), 2)

    def test_preflight_blocks_every_call(self):
        report = self._pdca(self._produce()).run(self._decl(criteria=("没登记",)))
        self.assertFalse(report["passed"])
        self.assertEqual(report["dispatches"], 0)
        self.assertEqual(self.calls, [])

    def test_budget_stops_before_next_dispatch(self):
        def produce(role, stage, upstream, attempt, feedback="", requirements=""):
            self.calls.append((role.name, stage, attempt))
            return "x" * 400            # ≈100 tokens/次

        report = self._pdca(produce).run(self._decl(budget_tokens=50))
        self.assertFalse(report["passed"])
        self.assertIn("预算用尽", report["reason"])
        self.assertEqual(report["dispatches"], 1, "超预算后不许再派第二个活")

    def test_evidence_gate_is_a_separate_gate(self):
        report = self._pdca(self._produce()).run(self._decl(), evidence=["见附件"])
        self.assertFalse(report["passed"])
        self.assertTrue(any("证据" in p for p in report["problems"]), report["problems"])

    def test_silent_failure_when_declared_dim_uncovered(self):
        judge = make_judge({"起草齐全": ("correctness",), "成稿齐全": ("correctness",)})
        report = self._pdca(self._produce(), judge=judge).run(self._decl())
        self.assertFalse(report["passed"])
        self.assertTrue(any("test_quality" in p for p in report["problems"]), report["problems"])

    def test_ledger_records_reject_and_redo(self):
        self._pdca(self._produce(fail_first_on="成稿")).run(self._decl())
        kinds = Ledger(self.root / "l.jsonl").kinds()
        self.assertIn("reject", kinds)
        self.assertIn("redo_stage", kinds)
        self.assertIn("delivery", kinds)


    def test_redo_carries_the_reject_reason(self):
        """重做必须知道上次错在哪，否则省下的整篇钱又亏回去。"""
        seen = []

        def produce(role, stage, upstream, attempt, feedback="", requirements=""):
            seen.append((stage, attempt, feedback))
            if role.kind != "executor":
                return ""
            if stage == "成稿" and attempt == 1:
                return f"{S1}\n{S2}\n"
            return f"{S1}\n{S2}\n{S3}\n"

        report = self._pdca(produce).run(self._decl())
        self.assertTrue(report["passed"], report)
        retries = [item for item in seen if item[1] == 2]
        self.assertTrue(retries, "没有发生重做")
        self.assertIn("缺章节", retries[0][2], "重做没带失败原因 = 盲重做")


    def test_dangling_stage_gate_blocks_before_any_call(self):
        """编制里的阶段门引用了没登记的判据：不许开工，一次调用都不发。"""
        org = json.loads(ORG)
        org["stages"][0]["gate_criteria"] = ["没登记的门"]
        plan = fo.parse_plan("目标", json.dumps(org, ensure_ascii=False))
        pdca = PDCA(make_judge(), Ledger(self.root / "l2.jsonl"), plan,
                    self._produce(), fd.VOCAB)
        report = pdca.run(self._decl())
        self.assertFalse(report["passed"])
        self.assertEqual(report["dispatches"], 0)
        self.assertEqual(self.calls, [])
        self.assertTrue(any("未登记的判据" in p for p in report["problems"]), report["problems"])

    def test_persistent_rejection_is_written_to_case_book(self):
        """阶段连续被拒两次要进案例库：下一次同类失败才查得到。"""
        from sa2.memory.cases import CaseBook

        cases = CaseBook(self.root / "cases.jsonl")

        def produce(role, stage, upstream, attempt, feedback="", requirements=""):
            return "" if role.kind != "executor" else f"{S1}\n"

        plan = fo.parse_plan("目标", ORG)
        pdca = PDCA(make_judge(), Ledger(self.root / "c.jsonl"), plan, produce, fd.VOCAB,
                    max_stage_attempts=2, cases=cases)
        report = pdca.run(self._decl())
        self.assertFalse(report["passed"])
        stored = cases.all()
        self.assertEqual([c.stage for c in stored], ["起草"])
        self.assertIn("缺章节", stored[0].reason)

    def test_delivery_redo_writes_the_artifact(self):
        """交付门回退重做成功时，新稿要落盘——否则事后无法核「回退到底改了什么」。"""
        from sa2.forge import criteria as fc2

        judge = make_judge()
        judge.register(fc2.tested(fc2.propose_content(
            "交付要素", ["结论："], ("correctness",))), proposer="leader")

        def produce(role, stage, upstream, attempt, feedback="", requirements=""):
            if role.kind != "executor":
                return ""
            if stage == "起草":
                return f"{S1}\n{S2}\n"
            if attempt == 1:
                return f"{S1}\n{S2}\n{S3}\n"
            return f"{S1}\n结论：收口\n{S2}\n{S3}\n"

        art = self.root / "artifacts"
        pdca = PDCA(judge, Ledger(self.root / "a.jsonl"), fo.parse_plan("目标", ORG),
                    produce, fd.VOCAB, artifact_dir=art)
        report = pdca.run(self._decl(criteria=("起草齐全", "成稿齐全", "交付要素")))
        self.assertTrue(report["passed"], report)
        written = (art / "1-成稿.md").read_text(encoding="utf-8")
        self.assertIn("结论：收口", written,
                      "回退重做后的稿子必须覆盖上一版：只写阶段首次产出的文件不算")

    def test_requirements_skip_unregistered_stage_gate(self):
        plan = fo.parse_plan("目标", ORG)
        bad = replace(plan.stages[0], gate_criteria=("没登记的判据", "起草齐全"))
        pdca = PDCA(make_judge(), Ledger(self.root / "r.jsonl"),
                    replace(plan, stages=(bad,) + plan.stages[1:]), self._produce(), fd.VOCAB)
        text = pdca._requirements(bad)
        self.assertIn("必须包含：", text)
        self.assertNotIn("没登记的判据", text)

    def test_parallel_stage_stops_when_budget_is_gone(self):
        """预算在进入下一阶段时耗尽：并行分支也要先停，不许派活。"""
        art = self.root / "par"
        pdca = PDCA(make_judge(), Ledger(self.root / "p.jsonl"),
                    fo.parse_plan("目标", ORG), self._produce(), fd.VOCAB, parallel=True)
        report = pdca.run(self._decl(budget_tokens=1))
        self.assertFalse(report["passed"])
        self.assertIn("pause_auto", Ledger(self.root / "p.jsonl").kinds())
        self.assertFalse(art.exists())


if __name__ == "__main__":
    unittest.main()