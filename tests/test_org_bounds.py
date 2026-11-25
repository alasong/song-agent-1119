"""编制提示词的上限来自数据，不再写死 3–6 / 2–4；代码只保下界。"""
import json
import os
import unittest
from unittest import mock

from sa2.forge import org


def plan_dict() -> dict:
    return {
        "roles": [
            {"name": "甲", "kind": "executor", "duty": "写", "criteria": "齐", "budget": 10},
            {"name": "乙", "kind": "verifier", "duty": "判", "criteria": "检", "budget": 10},
            {"name": "丙", "kind": "curator", "duty": "整", "criteria": "序", "budget": 10},
        ],
        "stages": [
            {"name": "起草", "output": "草稿", "roles": ["甲", "丙"], "gate_criteria": ["c1"]},
            {"name": "定稿", "output": "终稿", "roles": ["乙"], "gate_criteria": ["c1"]},
        ],
    }


class OrgPromptBoundsTest(unittest.TestCase):
    def prompt_with(self, env: dict) -> str:
        prompts: list[str] = []

        def llm(messages, max_tokens=None):
            prompts.append(messages[-1]["content"])
            return json.dumps(plan_dict(), ensure_ascii=False)

        with mock.patch.dict(os.environ, env):
            org.plan_org("写一份报告", llm, criteria=["c1"])
        return prompts[0]

    def test_defaults_are_the_old_prompt_bounds(self):
        prompt = self.prompt_with({})
        self.assertIn("3–6 个角色", prompt)
        self.assertIn("2–4 个阶段", prompt)

    def test_bounds_can_be_raised_from_data(self):
        prompt = self.prompt_with({"XM_SA2_ORG_ROLES_MAX": "12",
                                   "XM_SA2_ORG_STAGES_MAX": "6"})
        self.assertIn("3–12 个角色", prompt)
        self.assertIn("2–6 个阶段", prompt)

    def test_lower_bounds_stay_in_code(self):
        self.assertEqual(org.ROLE_MIN, 3)
        self.assertEqual(org.STAGE_MIN, 2)


if __name__ == "__main__":
    unittest.main()