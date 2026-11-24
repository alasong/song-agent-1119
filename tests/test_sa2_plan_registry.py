"""S5：编制与流程复用。同一组输入的第二次 plan_org 不该再问模型。

复合键必须带预算、判据、工具、标题——只按 goal 缓存会把不同条件下的编制当同一份。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sa2.core.ledger import Ledger
from sa2.forge import org as fo
from sa2.memory.plans import PlanStore

ORG = json.dumps({
    "roles": [
        {"name": "规划", "kind": "planner", "duty": "拆解任务", "criteria": "有子任务", "budget": 100},
        {"name": "执行", "kind": "executor", "duty": "写正文", "criteria": "章节齐全", "budget": 200},
        {"name": "验证", "kind": "verifier", "duty": "独立判", "criteria": "有结论", "budget": 50},
    ],
    "stages": [
        {"name": "起草", "output": "草稿", "roles": ["规划", "执行"], "gate_criteria": ["c1"]},
        {"name": "成稿", "output": "成稿", "roles": ["执行", "验证"], "gate_criteria": ["c1", "c2"]},
    ],
}, ensure_ascii=False)


class PlanRegistryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = PlanStore(self.root / "plans.json")
        self.ledger = Ledger(self.root / "ledger.jsonl")
        self.calls: list[int] = []

        def llm(messages, max_tokens=None):
            self.calls.append(1)
            return ORG

        self.llm = llm

    def tearDown(self):
        self.tmp.cleanup()

    def _plan(self, goal="写一篇稿", **kw):
        opts = dict(budget_cap=10_000, criteria=("c1", "c2"))
        opts.update(kw)
        return fo.plan_org(goal, self.llm, store=self.store,
                           ledger=self.ledger, **opts)

    def test_second_call_does_not_ask_the_model(self):
        first = self._plan()
        self.assertEqual(len(self.calls), 1)
        second = self._plan()
        self.assertEqual(len(self.calls), 1, "同条件第二次不该再问模型")
        self.assertEqual([r.name for r in first.roles], [r.name for r in second.roles])
        self.assertEqual([s.name for s in first.stages], [s.name for s in second.stages])
        self.assertEqual(self.ledger.count("plan_reused"), 1)

    def test_different_budget_misses(self):
        self._plan()
        self._plan(budget_cap=9_000)
        self.assertEqual(len(self.calls), 2, "预算变了，编制不能复用")

    def test_different_goal_misses(self):
        self._plan()
        self._plan(goal="换一个目标")
        self.assertEqual(len(self.calls), 2)

    def test_criteria_order_does_not_split_the_key(self):
        self._plan()
        self._plan(criteria=("c2", "c1"))
        self.assertEqual(len(self.calls), 1, "判据是集合，顺序不同不该算新条件")

    def test_store_roundtrip_keeps_roles_and_gates(self):
        key = self.store.key("写一篇稿", 10_000, ("c1", "c2"), (), ())
        self.store.put(key, {"roles": [], "stages": [{"name": "起草"}]})
        got = PlanStore(self.root / "plans.json").get(key)
        self.assertEqual(got["stages"][0]["name"], "起草")

    def test_corrupt_plan_library_is_loud(self):
        self.store = PlanStore(self.root / "plans.json")
        (self.root / "plans.json").write_text("{坏了", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "编制库坏了"):
            self.store.get("任意键")

    def test_mark_reuse_of_unknown_key_is_a_noop(self):
        self._plan()
        before = (self.root / "plans.json").read_text(encoding="utf-8")
        self.store.mark_reuse("不存在的键")
        self.assertEqual((self.root / "plans.json").read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()