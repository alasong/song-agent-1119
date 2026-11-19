"""sa 组织级跑任务的端到端验收（假模型 + 假判据，不联网）。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from xm.sa_task import run

PLAN = json.dumps({
    "roles": [
        {"name": "规划者", "kind": "planner", "duty": "拆解", "criteria": "有步骤", "budget": 1000},
        {"name": "实现者", "kind": "executor", "duty": "产出", "criteria": "有内容", "budget": 1000},
        {"name": "验证者", "kind": "verifier", "duty": "复核", "criteria": "能判红", "budget": 1000},
    ],
    "process": ["拆解", "产出"],
}, ensure_ascii=False)

GOOD_DOC = "## 一\n内容\n## 二\n内容\n"


def fake_llm(messages, max_tokens=2000):
    prompt = messages[0]["content"]
    if "Super" in prompt or "组一支" in prompt:
        return PLAN
    if "整合成一份完整" in prompt:
        return GOOD_DOC
    if "没有通过验收" in prompt:
        return "## 一\n修好了\n## 二\n内容\n"
    return "片段"


class SaTaskTest(unittest.TestCase):
    def _mk_task(self, check_body: str) -> Path:
        tmp = Path(tempfile.mkdtemp())
        (tmp / "task.json").write_text(
            json.dumps({"spec": "格式要求", "check": "check.py"}, ensure_ascii=False), encoding="utf-8")
        (tmp / "check.py").write_text(check_body, encoding="utf-8")
        return tmp

    def test_pass_path(self):
        task = self._mk_task("import sys\nsys.exit(0)\n")
        report = run("做个任务", task, fake_llm, rounds=2)
        self.assertTrue(report["passed"])
        self.assertEqual(len(report["org"]["roles"]), 3)
        self.assertEqual(report["dispatch"]["chain_ok"], True)
        self.assertEqual(report["dispatch"]["distinct_roles"], 3)

    def test_rework_then_pass(self):
        # 判据第一次失败、第二次通过：用文件计数模拟
        body = (
            "import sys\n"
            "from pathlib import Path\n"
            "counter = Path(__file__).parent / 'n.txt'\n"
            "n = int(counter.read_text()) if counter.exists() else 0\n"
            "counter.write_text(str(n + 1))\n"
            "sys.exit(1 if n == 0 else 0)\n"
        )
        task = self._mk_task(body)
        report = run("做个任务", task, fake_llm, rounds=3)
        self.assertTrue(report["passed"])
        self.assertEqual(len(report["attempts"]), 2)
        self.assertEqual(report["attempts"][0]["rc"], 1)

    def test_keeps_failing_is_reported(self):
        task = self._mk_task("import sys\nsys.exit(1)\n")
        report = run("做个任务", task, fake_llm, rounds=2)
        self.assertFalse(report["passed"])
        self.assertEqual(len(report["attempts"]), 2)


if __name__ == "__main__":
    unittest.main()