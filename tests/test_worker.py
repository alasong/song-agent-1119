"""真模型角色 worker 的验收（用假 llm，不联网）。"""
import unittest

from xm.worker import RoleWorker

ROLE = {"name": "实现者", "kind": "executor", "duty": "只负责写实现", "criteria": "测试绿"}
ROLE2 = {"name": "复核者", "kind": "verifier", "duty": "只负责复核", "criteria": "能判红"}


class RoleWorkerTest(unittest.TestCase):
    def test_artifact_has_content_and_upstream(self):
        calls = []

        def fake_llm(messages):
            calls.append(messages[0]["content"])
            return f"产出{len(calls)}"

        w = RoleWorker(fake_llm)
        first = w(ROLE, "实现", None)
        second = w(ROLE2, "复核", first)

        self.assertEqual(first["upstream"], None)
        self.assertEqual(first["content"], "产出1")
        self.assertEqual(second["upstream"], first["id"])
        self.assertEqual(second["content"], "产出2")
        self.assertIn("产出1", calls[1])  # 下游提示里带上了上游内容

    def test_prompt_contains_role_duty_and_criteria(self):
        seen = {}
        w = RoleWorker(lambda m: seen.setdefault("p", m[0]["content"]) or "x")
        w(ROLE, "实现", None)
        self.assertIn("只负责写实现", seen["p"])
        self.assertIn("测试绿", seen["p"])

    def test_log_records_artifacts(self):
        w = RoleWorker(lambda m: "内容")
        w(ROLE, "实现", None)
        self.assertEqual(len(w.log), 1)
        self.assertEqual(w.log[0]["role"], "实现者")


if __name__ == "__main__":
    unittest.main()