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


class ContentCriteriaTest(unittest.TestCase):
    """内容类判据：关键词必须出现，但塞进代码围栏里不算。"""

    def test_instantiate_content_marker(self):
        crit = fc.instantiate("必须出现：机制：\n必须出现：止损：", "有要素", ("correctness",))
        self.assertEqual(crit.kind, "regex")
        self.assertTrue(crit.spec["literal"])
        self.assertEqual(crit.spec["patterns"], ["机制：", "止损："])

    def test_mixed_markers_are_refused(self):
        with self.assertRaises(ValueError):
            fc.instantiate("必须包含：## 一、a\n必须出现：机制：", "混用", ("correctness",))

    def test_self_test_holds_for_content_criteria(self):
        crit = fc.propose_content("有要素", ["机制：", "止损："], ("correctness",))
        ok, fails = fc.self_test(crit)
        self.assertTrue(ok, fails)

    def test_keyword_inside_fence_does_not_count(self):
        judge = Judge(authority=("leader",))
        judge.register(fc.tested(fc.propose_content("有要素", ["止损："], ("correctness",))),
                       proposer="leader")
        self.assertFalse(judge.run("有要素", "```\n止损：连续两轮即停\n```").ok)
        self.assertTrue(judge.run("有要素", "止损：连续两轮即停").ok)


if __name__ == "__main__":
    unittest.main()

class ResearcherToolsTest(unittest.TestCase):
    """没有手的 researcher 不许过编制：凭记忆写清单不是采集（rsi 那轮实测的根因）。

    「有工具」也不够——挂一个章节检查器同样过不了：那是一件检查器，不是一双手。
    """

    def roles_with(self, kind: str, tools=None) -> str:
        role = {"name": "查", "kind": kind, "duty": "找资料", "criteria": "有来源", "budget": 20}
        if tools:
            role["tools"] = tools
        return org_json(roles=[
            {"name": "规划", "kind": "planner", "duty": "拆", "criteria": "可验收", "budget": 10},
            role,
            {"name": "验证", "kind": "verifier", "duty": "只判", "criteria": "有结论", "budget": 5},
        ], stages=[
            {"name": "查资料", "output": "清单", "roles": ["规划", "查"], "gate_criteria": ["g1"]},
            {"name": "定稿", "output": "稿子", "roles": ["查", "验证"], "gate_criteria": ["g2"]},
        ])

    def test_researcher_without_tools_is_refused(self):
        with self.assertRaises(fo.OrgError) as ctx:
            fo.parse_plan("目标", self.roles_with("researcher"))
        self.assertIn("researcher", str(ctx.exception))

    def test_researcher_with_fetch_tool_passes(self):
        plan = fo.parse_plan("目标", self.roles_with("researcher", ["抓取器"]),
                             available_tools={"抓取器": "fetch"})
        self.assertEqual(plan.role("查").tools, ("抓取器",))

    def test_checker_is_not_a_hand(self):
        with self.assertRaises(fo.OrgError) as ctx:
            fo.parse_plan("目标", self.roles_with("researcher", ["章节检查器"]),
                          available_tools={"章节检查器": "checker"})
        self.assertIn("researcher", str(ctx.exception))

    def test_unknown_tool_is_refused(self):
        with self.assertRaises(fo.OrgError) as ctx:
            fo.parse_plan("目标", self.roles_with("researcher", ["没这个"]),
                          available_tools={"抓取器": "fetch"})
        self.assertIn("没这个", str(ctx.exception))

    def test_capability_unknown_is_not_judged(self):
        """没给能力表时不能凭空判红，只能先信它挂的名字。"""
        plan = fo.parse_plan("目标", self.roles_with("researcher", ["某个工具"]))
        self.assertEqual(plan.role("查").tools, ("某个工具",))

    def test_expert_needs_no_tool(self):
        plan = fo.parse_plan("目标", self.roles_with("expert"))
        self.assertEqual(plan.role("查").tools, ())


class CollapseUncoveredTest(unittest.TestCase):
    """样例标题比阶段少时，多余阶段并进最后一个拿到切片的阶段。

    不许让它落进「没切片 → 兜成全部交付判据」那条路：append 模式下那两次必红
    （2026-11-20 真跑 4 阶段 / 3 标题，passed=False）。
    """

    def four_stages(self):
        data = json.loads(org_json())
        data["roles"].append({"name": "补充", "kind": "curator", "duty": "归档",
                              "criteria": "可查", "budget": 5})
        data["stages"] = [
            {"name": "一", "output": "a", "roles": ["规划"], "gate_criteria": ["g1"]},
            {"name": "二", "output": "b", "roles": ["执行"], "gate_criteria": ["g2"]},
            {"name": "三", "output": "c", "roles": ["验证"], "gate_criteria": ["g3"]},
            {"name": "四", "output": "d", "roles": ["补充"], "gate_criteria": ["g4"]},
        ]
        return fo.parse_plan("目标", json.dumps(data, ensure_ascii=False), require_gates=False)

    def test_extra_stage_merges_into_last_covered(self):
        plan = self.four_stages()
        merged, kept, dropped = fo.collapse_uncovered(plan, list(plan.stages), 3)
        self.assertEqual([st.name for st in merged.stages], ["一", "二", "三"])
        self.assertEqual(dropped, ("四",))
        self.assertEqual(len(kept), 3)
        by_name = {st.name: st for st in merged.stages}
        self.assertIn("补充", by_name["三"].roles, "被并掉的阶段，人和活要一起过去")

    def test_no_role_is_lost(self):
        plan = self.four_stages()
        merged, _, _ = fo.collapse_uncovered(plan, list(plan.stages), 3)
        surviving = {n for st in merged.stages for n in st.roles}
        self.assertEqual(surviving, {r.name for r in merged.roles})

    def test_no_op_when_there_are_enough_slices(self):
        plan = self.four_stages()
        same, kept, dropped = fo.collapse_uncovered(plan, list(plan.stages), 4)
        self.assertEqual(same, plan)
        self.assertEqual(len(kept), 4)
        self.assertEqual(dropped, ())


class HeadingsShapeTest(unittest.TestCase):
    """结构由样例定义：阶段数必须等于章节数，否则第一节会被错岗占着。"""

    def test_stage_count_must_match_headings(self):
        data = json.loads(org_json())
        data["stages"] = [
            {"name": "一", "output": "a", "roles": ["规划"], "gate_criteria": ["g1"]},
            {"name": "二", "output": "b", "roles": ["执行"], "gate_criteria": ["g2"]},
            {"name": "三", "output": "c", "roles": ["验证"], "gate_criteria": ["g3"]},
        ]
        with self.assertRaises(fo.OrgError) as ctx:
            fo.parse_plan("目标", json.dumps(data, ensure_ascii=False),
                          headings=("## 一、最新进展", "## 二、主要方向"))
        self.assertIn("章节", str(ctx.exception))

    def test_matching_stage_count_passes(self):
        data = json.loads(org_json())
        data["stages"] = [
            {"name": "进展梳理", "output": "a", "roles": ["规划"], "gate_criteria": ["g1"]},
            {"name": "方向研判", "output": "b", "roles": ["执行", "验证"], "gate_criteria": ["g2"]},
        ]
        plan = fo.parse_plan("目标", json.dumps(data, ensure_ascii=False),
                             headings=("## 一、最新进展", "## 二、主要方向"))
        self.assertEqual([s.name for s in plan.stages], ["进展梳理", "方向研判"])
