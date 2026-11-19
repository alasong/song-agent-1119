"""HR 组队方案的校验验收（不调模型）。"""
import json
import unittest

from xm.hiring import HiringError, Role, parse_plan


def good(**over):
    base = {
        "roles": [
            {"name": "拆解者", "kind": "planner", "duty": "只负责拆目标",
             "criteria": "每个子任务有可执行判据", "budget": 10000},
            {"name": "实现者", "kind": "executor", "duty": "只负责写实现",
             "criteria": "验收测试 rc=0", "budget": 50000},
            {"name": "复核者", "kind": "verifier", "duty": "只负责独立复核",
             "criteria": "打回率与漏放率可追溯", "budget": 20000},
        ],
        "process": ["拆解", "实现", "复核"],
    }
    base.update(over)
    return json.dumps(base, ensure_ascii=False)


class HiringTest(unittest.TestCase):
    def test_good_plan_passes(self):
        plan = parse_plan("做一件事", good(), 200000)
        self.assertEqual(len(plan.roles), 3)
        self.assertEqual(plan.total_budget, 80000)
        self.assertEqual(plan.process, ["拆解", "实现", "复核"])

    def test_too_few_roles(self):
        with self.assertRaises(HiringError):
            parse_plan("x", good(roles=[{"name": "a", "kind": "planner", "duty": "d",
                                         "criteria": "c", "budget": 1}]), 200000)

    def test_missing_criteria(self):
        roles = json.loads(good())["roles"]
        del roles[0]["criteria"]
        with self.assertRaises(HiringError):
            parse_plan("x", json.dumps({"roles": roles, "process": ["a", "b"]}), 200000)

    def test_no_independent_verifier(self):
        roles = json.loads(good())["roles"]
        roles[2]["kind"] = "curator"
        with self.assertRaises(HiringError):
            parse_plan("x", json.dumps({"roles": roles, "process": ["a", "b"]}), 200000)

    def test_over_budget(self):
        with self.assertRaises(HiringError):
            parse_plan("x", good(), 50000)

    def test_duplicate_names(self):
        roles = json.loads(good())["roles"]
        roles[1]["name"] = roles[0]["name"]
        with self.assertRaises(HiringError):
            parse_plan("x", json.dumps({"roles": roles, "process": ["a", "b"]}), 200000)

    def test_garbage_output(self):
        with self.assertRaises(HiringError):
            parse_plan("x", "我建议你们先开会", 200000)

    def test_process_too_short(self):
        with self.assertRaises(HiringError):
            parse_plan("x", good(process=["一步到位"]), 200000)

    def test_role_is_frozen(self):
        plan = parse_plan("x", good(), 200000)
        with self.assertRaises(Exception):
            plan.roles[0].name = "改名"


if __name__ == "__main__":
    unittest.main()