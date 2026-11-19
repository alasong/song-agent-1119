"""sa2 L1 自检：编制必须是流程不是全连接、判据必须过三反例。"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from sa2.core.judge import Criterion, Judge
from sa2.forge import criteria as fc
from sa2.forge import dims as fd
from sa2.forge import goal as fg
from sa2.forge import org as fo

VOCAB = fd.VOCAB


def org_json(**over):
    data = {
        "roles": [
            {"name": "规划", "kind": "planner", "duty": "拆", "criteria": "可验收", "budget": 10},
            {"name": "执行", "kind": "executor", "duty": "写", "criteria": "齐全", "budget": 20},
            {"name": "验证", "kind": "verifier", "duty": "只判", "criteria": "有结论", "budget": 5},
        ],
        "stages": [
            {"name": "起草", "output": "草稿", "roles": ["规划", "执行"], "gate_criteria": ["g1"]},
            {"name": "成稿", "output": "成稿", "roles": ["执行", "验证"], "gate_criteria": ["g2"]},
        ],
    }
    data.update(over)
    return json.dumps(data, ensure_ascii=False)


class DimsTest(unittest.TestCase):
    def test_declare_normalizes(self):
        self.assertEqual(fd.declare([" correctness "]), ("correctness",))

    def test_unknown_and_empty_are_refused(self):
        self.assertTrue(fd.validate([]))
        self.assertTrue(fd.validate(["vibes"]))

    def test_vocabulary_is_closed(self):
        self.assertEqual(len(fd.VOCAB), 8)


class OrgTest(unittest.TestCase):
    def test_plan_is_not_a_cartesian_product(self):
        plan = fo.parse_plan("目标", org_json())
        self.assertEqual(plan.dispatches(), 4)
        self.assertLess(plan.dispatches(), len(plan.roles) * len(plan.stages))

    def test_full_cartesian_is_refused(self):
        with self.assertRaises(fo.OrgError):
            fo.parse_plan("目标", org_json(stages=[
                {"name": "起草", "output": "草稿", "roles": ["规划", "执行", "验证"], "gate_criteria": ["g"]},
                {"name": "成稿", "output": "成稿", "roles": ["规划", "执行", "验证"], "gate_criteria": ["g"]},
            ]))

    def test_stage_must_bind_roles_and_gates(self):
        with self.assertRaises(fo.OrgError):
            fo.parse_plan("目标", org_json(stages=[
                {"name": "起草", "output": "草稿", "roles": [], "gate_criteria": ["g"]},
                {"name": "成稿", "output": "成稿", "roles": ["执行"], "gate_criteria": ["g"]},
            ]))
        with self.assertRaises(fo.OrgError):
            fo.parse_plan("目标", org_json(stages=[
                {"name": "起草", "output": "草稿", "roles": ["执行"], "gate_criteria": []},
                {"name": "成稿", "output": "成稿", "roles": ["执行"], "gate_criteria": ["g"]},
            ]))

    def test_plain_string_stage_is_refused(self):
        with self.assertRaises(fo.OrgError):
            fo.parse_plan("目标", org_json(stages=["起草", "成稿"]))

    def test_verifier_and_budget_rules_still_hold(self):
        roles = [
            {"name": "规划", "kind": "planner", "duty": "拆", "criteria": "可验收", "budget": 10},
            {"name": "执行", "kind": "executor", "duty": "写", "criteria": "齐全", "budget": 10},
            {"name": "记录", "kind": "curator", "duty": "归档", "criteria": "可查", "budget": 10},
        ]
        with self.assertRaises(fo.OrgError):
            fo.parse_plan("目标", org_json(roles=roles))

    def test_duty_equal_to_criteria_is_refused(self):
        roles = [
            {"name": "规划", "kind": "planner", "duty": "拆目标", "criteria": "拆目标", "budget": 10},
            {"name": "执行", "kind": "executor", "duty": "写", "criteria": "齐全", "budget": 10},
            {"name": "验证", "kind": "verifier", "duty": "只判", "criteria": "有结论", "budget": 5},
        ]
        with self.assertRaises(fo.OrgError):
            fo.parse_plan("目标", org_json(roles=roles))


class CriteriaTest(unittest.TestCase):
    def test_instantiate_requires_marker_lines(self):
        crit = fc.instantiate("必须包含：## 一、a\n必须包含：## 二、b", "齐", ("correctness",))
        self.assertEqual(crit.spec["required"], ["## 一、a", "## 二、b"])
        with self.assertRaises(ValueError):
            fc.instantiate("随便写点", "齐", ("correctness",))

    def test_self_test_passes_for_a_well_formed_criterion(self):
        crit = fc.propose_sections("齐", ["## 一、a", "## 二、b"], ("correctness",))
        ok, fails = fc.self_test(crit)
        self.assertTrue(ok, fails)

    def test_self_test_catches_a_too_loose_criterion(self):
        """把判据改坏（标题在围栏里也放过），自测必须变红——否则自测是摆设。"""
        crit = fc.propose_sections("齐", ["## 一、a", "## 二、b"], ("correctness",))
        with mock.patch.object(Judge, "_run_sections", lambda self, spec, text: []):
            ok, fails = fc.self_test(crit)
        self.assertFalse(ok)
        self.assertTrue(any("缺件" in f for f in fails), fails)

    def test_tested_marks_and_refuses(self):
        crit = fc.propose_sections("齐", ["## 一、a", "## 二、b"], ("correctness",))
        self.assertTrue(fc.tested(crit).self_tested)
        broken = Criterion(name="空", kind="sections", spec={"required": []},
                           dims=("correctness",), self_tested=False)
        with self.assertRaises(ValueError):
            fc.tested(broken)


class GoalTest(unittest.TestCase):
    RAW = json.dumps({"subtasks": [
        {"name": "a", "deliverable": "文档", "dims": ["correctness"]},
        {"name": "b", "deliverable": "实验", "dims": ["test_quality"]},
    ]}, ensure_ascii=False)

    def test_parse_ok(self):
        subs = fg.parse("目标", self.RAW, VOCAB)
        self.assertEqual([s.name for s in subs], ["a", "b"])

    def test_missing_dims_or_unknown_dims_refused(self):
        raw = json.dumps({"subtasks": [{"name": "a", "deliverable": "文档", "dims": []}]},
                         ensure_ascii=False)
        with self.assertRaises(fg.GoalError):
            fg.parse("目标", raw, VOCAB)
        raw = json.dumps({"subtasks": [{"name": "a", "deliverable": "文档", "dims": ["vibes"]}]},
                         ensure_ascii=False)
        with self.assertRaises(fg.GoalError):
            fg.parse("目标", raw, VOCAB)

    def test_too_many_subtasks_refused(self):
        raw = json.dumps({"subtasks": [
            {"name": f"t{i}", "deliverable": "d", "dims": ["correctness"]} for i in range(6)
        ]}, ensure_ascii=False)
        with self.assertRaises(fg.GoalError):
            fg.parse("目标", raw, VOCAB)


if __name__ == "__main__":
    unittest.main()