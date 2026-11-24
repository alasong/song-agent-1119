"""编制是红线的一部分：没有独立验证角色、阶段不绑角色、阶段门自造，都必须当场拒。

`test_sa2_forge` 盖的是「好编制能跑通 + 生成流程」；这里逐条打 `parse_plan` 的拒收分支，
并钉住 `plan_org` 的重试要把拒收原因带回去——不带原因的重试等于让它重复同一个错。
"""
import json
import unittest

from sa2.forge import org


def plan_dict() -> dict:
    return {
        "roles": [
            {"name": "甲", "kind": "executor", "duty": "只负责写正文",
             "criteria": "正文齐全", "budget": 100},
            {"name": "乙", "kind": "verifier", "duty": "只负责判",
             "criteria": "判据可机检", "budget": 50},
            {"name": "丙", "kind": "curator", "duty": "只负责整理",
             "criteria": "条目有序", "budget": 50},
        ],
        "stages": [
            {"name": "起草", "output": "草稿", "roles": ["甲", "丙"], "gate_criteria": ["结论"]},
            {"name": "定稿", "output": "终稿", "roles": ["乙"], "gate_criteria": ["结论"]},
        ],
    }


def raw_of(data: dict) -> str:
    return "前置说明\n" + json.dumps(data, ensure_ascii=False)


class ParsePlanTest(unittest.TestCase):
    def parse(self, data, **kw):
        return org.parse_plan("写一份报告", raw_of(data), **kw)

    def reject(self, data, pattern, **kw):
        with self.assertRaisesRegex(org.OrgError, pattern):
            self.parse(data, **kw)

    # -- 对照组 -----------------------------------------------------------
    def test_good_plan_is_parsed(self):
        plan = self.parse(plan_dict())
        self.assertEqual([r.name for r in plan.roles], ["甲", "乙", "丙"])
        self.assertEqual(len(plan.stages), 2)
        self.assertEqual(plan.total_budget, 200)
        self.assertEqual(plan.dispatches(), 3)
        self.assertEqual(plan.role("乙").kind, "verifier")

    def test_unknown_role_lookup_is_named(self):
        with self.assertRaisesRegex(org.OrgError, "没有这个角色"):
            self.parse(plan_dict()).role("丁")

    # -- 形状 -------------------------------------------------------------
    def test_no_json_in_output(self):
        with self.assertRaisesRegex(org.OrgError, "没有 JSON"):
            org.parse_plan("写一份报告", "模型只说了抱歉")

    def test_broken_json_is_named(self):
        with self.assertRaisesRegex(org.OrgError, "JSON 解析失败"):
            org.parse_plan("写一份报告", "{这不是 JSON}")

    # -- 角色 -------------------------------------------------------------
    def test_fewer_than_three_roles(self):
        data = plan_dict()
        data["roles"] = data["roles"][:2]
        self.reject(data, "至少 3 个")

    def test_role_missing_duty(self):
        data = plan_dict()
        data["roles"][0]["duty"] = ""
        self.reject(data, "缺 name/duty/criteria")

    def test_unknown_role_kind(self):
        data = plan_dict()
        data["roles"][0]["kind"] = "super"
        self.reject(data, "不在")

    def test_duplicate_role_name(self):
        data = plan_dict()
        data["roles"][2]["name"] = "甲"
        self.reject(data, "角色名重复")

    def test_role_budget_must_be_positive(self):
        data = plan_dict()
        data["roles"][0]["budget"] = 0
        self.reject(data, "预算必须为正")

    def test_duty_and_criteria_cannot_be_the_same_sentence(self):
        data = plan_dict()
        data["roles"][0]["criteria"] = data["roles"][0]["duty"]
        self.reject(data, "同一句话")

    def test_verifier_is_mandatory(self):
        data = plan_dict()
        data["roles"][1]["kind"] = "executor"
        self.reject(data, "独立验证角色")

    def test_unknown_tool_is_refused(self):
        data = plan_dict()
        data["roles"][0]["tools"] = ["不存在的工具"]
        self.reject(data, "工具库里没有的工具", available_tools={"arx": "fetch"})

    def test_researcher_without_hands_is_refused(self):
        data = plan_dict()
        data["roles"][2]["kind"] = "researcher"
        data["roles"][2]["tools"] = []
        self.reject(data, "没有能去看外面的手", available_tools={"arx": "fetch"})

    def test_researcher_with_fetch_tool_passes(self):
        data = plan_dict()
        data["roles"][2]["kind"] = "researcher"
        data["roles"][2]["tools"] = ["arx [fetch]"]
        plan = self.parse(data, available_tools={"arx": "fetch"})
        self.assertEqual(plan.role("丙").tools, ("arx",), "工具名后面的能力标注要剥掉")

    # -- 阶段 -------------------------------------------------------------
    def test_fewer_than_two_stages(self):
        data = plan_dict()
        data["stages"] = data["stages"][:1]
        self.reject(data, "至少 2 个")

    def test_stage_given_only_a_name(self):
        data = plan_dict()
        data["stages"][0] = "起草"
        self.reject(data, "只给了名字")

    def test_stage_missing_output(self):
        data = plan_dict()
        data["stages"][0]["output"] = ""
        self.reject(data, "缺 name/output")

    def test_stage_role_must_exist(self):
        data = plan_dict()
        data["stages"][0]["roles"] = ["甲", "丁"]
        self.reject(data, "引用了不存在的角色")

    def test_stage_needs_a_gate(self):
        data = plan_dict()
        data["stages"][0]["gate_criteria"] = []
        self.reject(data, "没有阶段门")

    def test_gate_can_be_waived_explicitly(self):
        data = plan_dict()
        data["stages"][0]["gate_criteria"] = []
        self.parse(data, require_gates=False)

    def test_stage_mode_is_closed_set(self):
        data = plan_dict()
        data["stages"][1]["mode"] = "merge"
        self.reject(data, "只能是 replace / append")

    def test_gate_must_be_registered_criteria(self):
        data = plan_dict()
        self.reject(data, "未登记的判据", available_criteria=["别的判据"])

    def test_headings_must_match_stage_count(self):
        data = plan_dict()
        self.reject(data, "章节", headings=("一", "二", "三"))

    # -- 全图 -------------------------------------------------------------
    def test_role_without_work_is_refused(self):
        data = plan_dict()
        data["stages"] = [
            {"name": "起草", "output": "草稿", "roles": ["甲"], "gate_criteria": ["结论"]},
            {"name": "定稿", "output": "终稿", "roles": ["乙"], "gate_criteria": ["结论"]},
        ]
        self.reject(data, "没被派任何活")

    def test_full_connection_is_not_a_process(self):
        data = plan_dict()
        data["stages"] = [
            {"name": name, "output": f"{name}产出", "roles": ["甲", "乙", "丙"],
             "gate_criteria": ["结论"]}
            for name in ("起草", "核对", "定稿")]
        self.reject(data, "全连接")

    def test_total_budget_cap(self):
        data = plan_dict()
        self.reject(data, "超过上限", budget_cap=100)

    # -- 生成：重试要带原因 -----------------------------------------------
    def test_plan_org_retries_with_feedback(self):
        bad = plan_dict()
        bad["roles"] = bad["roles"][:1]
        answers = [raw_of(bad), raw_of(plan_dict())]
        prompts = []

        def llm(messages, **kw):
            prompts.append(messages[-1]["content"])
            return answers.pop(0)

        plan = org.plan_org("写一份报告", llm, criteria=["结论"], attempts=2)
        self.assertEqual(len(plan.roles), 3)
        self.assertEqual(len(prompts), 2)
        self.assertNotIn("上次这份编制被拒", prompts[0])
        self.assertIn("上次这份编制被拒", prompts[1])
        self.assertIn("至少 3 个", prompts[1], "重试必须带拒收原因")

    def test_plan_org_gives_up_with_the_last_reason(self):
        def llm(messages, **kw):
            return "模型不肯给 JSON"

        with self.assertRaisesRegex(org.OrgError, "没有 JSON"):
            org.plan_org("写一份报告", llm, criteria=["结论"], attempts=2)


if __name__ == "__main__":
    unittest.main()