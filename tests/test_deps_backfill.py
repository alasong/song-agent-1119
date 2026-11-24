"""W10：交付门最终仍红时，把"断言没覆盖到"的依赖记成 claim_missed。

夹具与别处不同：阶段门只要求 S1/S2，交付判据要求 S3——
所以会出现「阶段都过、交付门红」的状态，这正是回填要覆盖的场景。
"""
import json
import tempfile
import unittest
from pathlib import Path

from sa2.core.deps import Assertion, DepNote
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


def make_judge():
    judge = Judge(authority=("leader",))
    for name, required in (("起草齐全", [S1]), ("成稿齐全", [S1, S2])):
        judge.register(fc.tested(fc.propose_sections(name, required, ("correctness",))),
                       proposer="leader")
    # 交付门用关键词判据：它不被阶段门的章节裁剪影响，才构造得出「阶段过、交付红」
    judge.register(fc.tested(fc.propose_content("整篇齐全", ["结论："], ("correctness",))),
                   proposer="leader")
    return judge


def note(step):
    return DepNote(step, (
        Assertion("抓取工具", "tool", "能取回至少 2 条真实记录", "cmd:true", "换源"),
    ))


def build(root, produce, dep_notes, require_deps=True):
    ledger = Ledger(Path(root) / "l.jsonl")
    pdca = PDCA(make_judge(), ledger, fo.parse_plan("目标", ORG), produce, fd.VOCAB,
                max_stage_attempts=2, require_deps=require_deps, dep_notes=dep_notes)
    decl = Declaration(goal="写东西", dims=("correctness",),
                       criteria=("整篇齐全",), budget_tokens=100_000)
    return pdca, ledger, decl


def short_produce(role, stage, upstream, attempt, feedback="", requirements=""):
    if role.kind != "executor":
        return ""
    return f"{S1}\n{S2}\n"            # 阶段门过；交付门缺「结论：」


def fixed_produce(role, stage, upstream, attempt, feedback="", requirements=""):
    if role.kind != "executor":
        return ""
    return f"{S1}\n{S2}\n结论：做完了\n"   # 阶段门与交付门都过


class BackfillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.notes = {stage: note(stage) for stage in ("起草", "成稿")}

    def tearDown(self):
        self.tmp.cleanup()

    def missed(self, ledger):
        return [e for e in ledger.read() if e["kind"] == "claim_missed"]

    def test_delivery_stays_red_records_missed_for_each_stage(self):
        pdca, ledger, decl = build(self.root, short_produce, self.notes)
        report = pdca.run(decl)
        self.assertFalse(report["passed"])
        records = self.missed(ledger)
        self.assertEqual(len(records), 2, records)
        payload = records[0]["payload"]
        self.assertEqual(payload["name"], "抓取工具")
        self.assertEqual(payload["penalty"], 0.4)
        self.assertTrue(payload["problems"])

    def test_delivery_fixed_by_redo_records_no_miss(self):
        pdca, ledger, decl = build(self.root, fixed_produce, self.notes)
        report = pdca.run(decl)
        self.assertTrue(report["passed"], report)
        self.assertEqual(self.missed(ledger), [])

    def test_no_notes_no_miss(self):
        pdca, ledger, decl = build(self.root, short_produce, {}, require_deps=False)
        pdca.run(decl)
        self.assertEqual(self.missed(ledger), [])


if __name__ == "__main__":
    unittest.main()