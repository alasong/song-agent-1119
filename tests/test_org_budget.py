"""组织路径的成本闸：超预算必须停，且停了的运行不许标成通过。

背景：DNA #8 要求「每个任务有上限，超支即停并落读数」，而组织路径此前没有运行期闸——
单 agent 有（`xm/daemon.py:144`），组队没有，等于升级一次就无限烧。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from xm import sa_task

PLAN = json.dumps({
    "roles": [
        {"name": "规划", "kind": "planner", "duty": "拆目标", "criteria": "步骤齐全", "budget": 10},
        {"name": "执行", "kind": "executor", "duty": "写交付", "criteria": "格式合规", "budget": 10},
        {"name": "验证", "kind": "verifier", "duty": "只判不写", "criteria": "能判真假", "budget": 10},
    ],
    "process": ["起草", "成稿"],
}, ensure_ascii=False)


class FakeLLM:
    """招人那一步返回编制 JSON，其余返回正文；可选按次记账真实 usage。"""

    def __init__(self, text: str = "交付内容", usage: list | None = None):
        self.calls = 0
        self.text = text
        self.usage = usage

    def __call__(self, messages, max_tokens: int = 800):
        self.calls += 1
        if self.usage is not None:
            self.usage.append({"total_tokens": 5})
        prompt = str((messages[0] or {}).get("content") or "")
        return PLAN if "Super" in prompt else self.text


class OrgBudgetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        self.task_dir = root / "task"
        self.task_dir.mkdir()
        (self.task_dir / "task.json").write_text(json.dumps({
            "spec": "写点东西", "target_name": "out.md", "check": "check.py",
        }, ensure_ascii=False), encoding="utf-8")
        # 永远判过：这样「停掉却仍标 passed」的错法才暴露得出来
        (self.task_dir / "check.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        self.saved = {k: os.environ.get(k) for k in ("XM_KB_PATH", "XM_RUNS")}
        os.environ["XM_KB_PATH"] = str(root / "kb.jsonl")
        os.environ["XM_RUNS"] = str(root / "runs")

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def _ledger(self, report) -> str:
        return (Path(report["deliverable"]).parent / "ledger.jsonl").read_text(encoding="utf-8")

    def test_stops_before_any_dispatch_when_budget_already_spent(self):
        report = sa_task.run("目标", self.task_dir, FakeLLM(), budget_tokens=1)
        self.assertEqual(report["dispatch"]["dispatches"], 0)   # 没产出任何产物
        self.assertTrue(report["stopped"], report)
        self.assertIn("预算用尽", report["stopped"])
        self.assertFalse(report["passed"], "停掉的运行不能标成通过")
        self.assertIn("budget_stop", self._ledger(report))

    def test_without_budget_it_dispatches_every_role_in_every_stage(self):
        report = sa_task.run("目标", self.task_dir, FakeLLM())
        self.assertEqual(report["dispatch"]["dispatches"], 6)   # 2 阶段 × 3 角色
        self.assertEqual(report["stopped"], "")
        self.assertTrue(report["passed"])

    def test_real_usage_drives_the_stop(self):
        usage: list[dict] = []
        report = sa_task.run("目标", self.task_dir, FakeLLM(usage=usage),
                             budget_tokens=10, usage=usage)
        # 招人 5 → 派活1 10 → 派活2 15 → 第 3 次派活前停
        self.assertEqual(report["dispatch"]["dispatches"], 2)
        self.assertEqual(report["budget"]["spent"], 15)
        self.assertTrue(report["budget"]["exact_usage"])
        self.assertFalse(report["passed"])

    def test_report_carries_the_budget_block(self):
        report = sa_task.run("目标", self.task_dir, FakeLLM(), budget_tokens=10_000)
        self.assertEqual(report["budget"]["tokens"], 10_000)
        self.assertGreater(report["budget"]["spent"], 0)
        self.assertFalse(report["budget"]["exact_usage"], "没给 usage 时应退回字符估算")


if __name__ == "__main__":
    unittest.main()