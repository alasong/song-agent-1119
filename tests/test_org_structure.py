"""编制生成与结构收口的拒收面：空编制、合并丢人、没有阶段都要当场抛。

`test_sa2_forge` / `test_org_parse` 盖的是 parse_plan；这里补
plan_org 的提示词分支与 collapse_uncovered / close_with_delivery 的结构守卫。
"""
import json
import unittest

from sa2.forge import org


def plan_dict() -> dict:
    return {
        "roles": [
            {"name": "甲", "kind": "executor", "duty": "只负责写", "criteria": "齐全", "budget": 100},
            {"name": "乙", "kind": "verifier", "duty": "只负责判", "criteria": "可机检", "budget": 50},
            {"name": "丙", "kind": "curator", "duty": "只负责整理", "criteria": "有序", "budget": 50},
        ],
        "stages": [
            {"name": "起草", "output": "草稿", "roles": ["甲", "丙"], "gate_criteria": ["结论"]},
            {"name": "定稿", "output": "终稿", "roles": ["乙"], "gate_criteria": ["结论"]},
        ],
    }


class OrgPromptTest(unittest.TestCase):
    def test_headings_are_written_into_the_prompt(self):
        prompts = []

        def llm(messages, max_tokens=None):
            prompts.append(messages[-1]["content"])
            return json.dumps(plan_dict(), ensure_ascii=False)

        headings = ("## 一、进展", "## 二、方案")
        plan = org.plan_org("写一份报告", llm, criteria=["结论"], headings=headings)
        self.assertEqual(len(plan.stages), 2)
        self.assertIn("交付结构已经定了", prompts[0])
        self.assertIn(headings[0], prompts[0])
        self.assertIn("有且只有 2 个章节", prompts[0])


class PlanFromDictTest(unittest.TestCase):
    def test_empty_library_entry_is_refused(self):
        with self.assertRaisesRegex(org.OrgError, "编制库里这一条是空的"):
            org._plan_from_dict({"roles": [], "stages": []})


class CollapseUncoveredTest(unittest.TestCase):
    def _plan(self):
        roles = (org.Role("甲", "executor", "写", "齐", 10),
                 org.Role("乙", "verifier", "判", "检", 10),
                 org.Role("丙", "curator", "整理", "序", 10))
        stages = (org.Stage("一", "xa", ("甲",), ("结论",)),
                  org.Stage("二", "xb", ("乙",), ("结论",)))
        return org.OrgPlan("目标", roles, stages)

    def test_merging_that_drops_a_role_is_refused(self):
        plan = self._plan()
        with self.assertRaisesRegex(org.OrgError, "合并后会丢掉角色"):
            org.collapse_uncovered(plan, list(plan.stages), covered=1)

    def test_merging_keeps_everyone_when_roles_are_inside_writers(self):
        roles = (org.Role("甲", "executor", "写", "齐", 10),
                 org.Role("乙", "verifier", "判", "检", 10))
        stages = (org.Stage("一", "xa", ("甲",), ("结论",)),
                  org.Stage("二", "xb", ("乙",), ("结论",)))
        plan, writers, dropped = org.collapse_uncovered(
            org.OrgPlan("目标", roles, stages), list(stages), covered=1)
        self.assertEqual(dropped, ("二",))
        self.assertEqual(len(plan.stages), 1)
        self.assertEqual(set(plan.stages[0].roles), {"甲", "乙"})


class CloseWithDeliveryTest(unittest.TestCase):
    def test_plan_without_stages_is_refused(self):
        plan = org.OrgPlan("目标", (org.Role("甲", "executor", "写", "齐", 10),), ())
        with self.assertRaisesRegex(org.OrgError, "编制没有阶段"):
            org.close_with_delivery(plan, ["结论"])

    def test_append_stage_puts_delivery_in_the_last_writer_too(self):
        roles = (org.Role("甲", "executor", "写", "齐", 10),
                 org.Role("乙", "verifier", "判", "检", 10))
        stages = (org.Stage("起草", "xa", ("甲",), ("起草门",), "replace"),
                  org.Stage("装配", "xb", ("乙",), ("装配门",), "append"))
        plan = org.close_with_delivery(org.OrgPlan("目标", roles, stages), ["交付门"])
        self.assertIn("交付门", plan.stages[-1].gate_criteria)
        self.assertIn("交付门", plan.stages[0].gate_criteria,
                      "写正文的人也要看见交付要求")


if __name__ == "__main__":
    unittest.main()