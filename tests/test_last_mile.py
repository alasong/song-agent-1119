"""收尾：几个小模块里最后一次没人跑过的行。

都不是主路径，但各自守一条规则：案例库能跳过坏行、维度词表拒重复、
指标会对利用率与通信效率报警、任务规格要进提示词、账本能跳过空行、
组队决策要交出给了的编制、作业没回正文时给空串而不是 None。
"""
import json
import tempfile
import unittest
from pathlib import Path

from sa2.core import ledger as ledger_mod
from sa2.core import metrics
from sa2.core.gate import Declaration
from sa2.forge import dims, org
from sa2.forge import scribe as scribe_mod
from sa2.loop import pool_producer, size
from sa2.memory.cases import CaseBook

ROLE = org.Role("执行", "executor", "写", "齐", 10)


class CaseBookAllTest(unittest.TestCase):
    def test_blank_corrupt_and_wrong_shape_rows_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = CaseBook(Path(tmp) / "cases.jsonl")
            book.add("起草", "缺章节", "补一节")
            with book.path.open("a", encoding="utf-8") as fh:
                fh.write("\n")
                fh.write("{坏行\n")
                fh.write(json.dumps({"stage": "只有阶段"}) + "\n")
            self.assertEqual([c.stage for c in book.all()], ["起草"])


class DimsTest(unittest.TestCase):
    def test_duplicate_dimension_is_reported(self):
        problems = dims.validate(["correctness", "correctness"])
        self.assertTrue(any("维度重复" in p for p in problems), problems)

    def test_declare_refuses_invalid_selection(self):
        with self.assertRaisesRegex(ValueError, "维度重复"):
            dims.declare(["correctness", "correctness"])

    def test_describe_lists_vocab_pairs_in_order(self):
        self.assertEqual(dims.describe(), list(dims.VOCAB.items()))


class MetricsFlagsTest(unittest.TestCase):
    def test_low_efficiency_flags(self):
        events = [{"kind": "dispatch", "payload": {"chars": 0}},
                  {"kind": "dispatch", "payload": {"chars": 0}},
                  {"kind": "dispatch", "payload": {"chars": 10}}]
        out = metrics.compute(events, {"budget": {"spent": 10_000}, "chars": 10})
        self.assertIn("资源利用率偏低：每千 token 产出不足 50 字", out["flags"])
        self.assertIn("通信效率偏低：过半派活没有产出", out["flags"])


class ScribeSpecTest(unittest.TestCase):
    def test_spec_is_rendered_into_the_prompt(self):
        prompts: list[str] = []

        def llm(messages, max_tokens=None):
            prompts.append(messages[-1]["content"])
            return "正文"

        sc = scribe_mod.Scribe(llm=llm, spec="必须包含：## 一、a")
        self.assertEqual(sc(ROLE, "起草", "", 1), "正文")
        self.assertIn("## 任务规格", prompts[0])
        self.assertIn("必须包含：## 一、a", prompts[0])


class LedgerBlankLineTest(unittest.TestCase):
    def test_blank_lines_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            path.write_text('{"kind": "x"}\n\n\n{"kind": "y"}\n', encoding="utf-8")
            self.assertEqual([e["kind"] for e in ledger_mod.Ledger(path).read()], ["x", "y"])


class SizeTeamTest(unittest.TestCase):
    def test_team_decision_returns_the_given_plan(self):
        stage = org.Stage("交付", "产出", ("执行",), ("齐",))
        team_plan = org.OrgPlan("目标", (ROLE,), (stage,))
        decl = Declaration(goal="目标", dims=("correctness", "test_quality"),
                           criteria=("甲", "乙", "丙"), budget_tokens=100_000)
        plan, decision = size.plan_for(decl, team_plan)
        self.assertEqual(decision.scale, "team")
        self.assertIs(plan, team_plan, "决策为组队时必须用调用方给的编制")


class PoolProducerEmptyTest(unittest.TestCase):
    def test_missing_job_output_becomes_empty_string(self):
        class FakePool:
            def submit(self, module, func, messages, max_tokens, timeout=None):
                return {"ok": True, "out": None}

        producer = pool_producer.PoolProducer(FakePool(), lambda *a, **k: "提示")
        self.assertEqual(producer(ROLE, "起草", "", 1), "",
                         "作业没回正文时给空串，别把 None 传进装配")


if __name__ == "__main__":
    unittest.main()