"""P1–P5 的自检：读数落盘、跨运行资产与版本、断点续跑、审批留痕、配置面。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from sa2 import config
from sa2.core.gate import Declaration
from sa2.core.judge import Criterion, Judge
from sa2.core.ledger import Ledger
from sa2.forge import criteria as fc
from sa2.forge import org as fo
from sa2.loop import size
from sa2.loop.pdca import PDCA
from sa2.memory import registry

S1, S2, S3 = "## 一、a", "## 二、b", "## 三、c"


class RegistryTest(unittest.TestCase):
    def test_paths_follow_the_env_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("XM_SA2_REGISTRY")
            os.environ["XM_SA2_REGISTRY"] = tmp
            try:
                self.assertEqual(registry.criteria_path(), Path(tmp) / "criteria.json")
                self.assertEqual(registry.cases_path(), Path(tmp) / "cases.jsonl")
                self.assertTrue(registry.root().exists())
            finally:
                if old is None:
                    os.environ.pop("XM_SA2_REGISTRY", None)
                else:
                    os.environ["XM_SA2_REGISTRY"] = old


class VersionTest(unittest.TestCase):
    def test_same_name_reregistration_bumps_version_and_keeps_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = Ledger(root / "l.jsonl")
            judge = Judge(authority=("leader",), path=root / "criteria.json",
                          history=root / "history.jsonl", ledger=ledger)
            first = fc.tested(fc.propose_sections("章节", [S1, S2], ("correctness",)))
            judge.register(first, proposer="leader")
            second = fc.tested(fc.propose_sections("章节", [S1, S3], ("correctness",)))
            judge.register(second, proposer="leader")

            self.assertEqual(judge.get("章节").version, 2, "同名重登必须升版本")
            hist = [json.loads(x) for x in (root / "history.jsonl").read_text().splitlines()]
            self.assertEqual([h["version"] for h in hist], [1, 2])
            self.assertEqual(hist[1]["replaced_version"], 1)
            self.assertEqual(ledger.count("criteria_approved"), 2)

    def test_reload_keeps_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            judge = Judge(authority=("leader",), path=path)
            judge.register(fc.tested(fc.propose_sections("章节", [S1], ("correctness",))),
                           proposer="leader")
            judge.register(fc.tested(fc.propose_sections("章节", [S1, S2], ("correctness",))),
                           proposer="leader")
            again = Judge(authority=("leader",), path=path)
            self.assertEqual(again.get("章节").version, 2)


class ConfigTest(unittest.TestCase):
    def test_env_overrides_thresholds(self):
        old = os.environ.get("XM_SA2_SINGLE_FLOOR")
        os.environ["XM_SA2_SINGLE_FLOOR"] = "999999"
        try:
            decl = Declaration(goal="t", dims=("correctness",), criteria=("c",),
                               budget_tokens=100_000)
            self.assertEqual(size.decide(decl).scale, "single",
                             "阈值被调高后 10 万预算也该判单人")
        finally:
            if old is None:
                os.environ.pop("XM_SA2_SINGLE_FLOOR", None)
            else:
                os.environ["XM_SA2_SINGLE_FLOOR"] = old

    def test_unknown_key_is_refused(self):
        with self.assertRaises(KeyError):
            config.get("没有这一项")


class ResumeTest(unittest.TestCase):
    ORG = json.dumps({
        "roles": [
            {"name": "规划", "kind": "planner", "duty": "拆", "criteria": "可验收", "budget": 10},
            {"name": "执行", "kind": "executor", "duty": "写", "criteria": "齐全", "budget": 20},
            {"name": "验证", "kind": "verifier", "duty": "只判", "criteria": "有结论", "budget": 5},
        ],
        "stages": [
            {"name": "起草", "output": "草稿", "roles": ["规划", "执行"], "gate_criteria": ["一段"]},
            {"name": "成稿", "output": "成稿", "roles": ["执行", "验证"], "gate_criteria": ["三段"]},
        ],
    }, ensure_ascii=False)

    def _fixture(self, root: Path):
        judge = Judge(authority=("leader",))
        judge.register(fc.tested(fc.propose_sections("一段", [S1], ("correctness",))),
                       proposer="leader")
        judge.register(fc.tested(fc.propose_sections("三段", [S1, S2, S3], ("correctness",))),
                       proposer="leader")
        plan = fo.parse_plan("目标", self.ORG)
        return judge, plan

    def test_resume_skips_finished_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            judge, plan = self._fixture(root)
            calls: list[str] = []
            state = root / "state.json"

            def flaky(role, stage, upstream, attempt, feedback="", requirements=""):
                calls.append(stage)
                if role.kind != "executor":
                    return ""
                if stage == "成稿":
                    raise RuntimeError("模拟进程被杀")
                return f"{S1}\n"

            decl = Declaration(goal="t", dims=("correctness",), criteria=("一段", "三段"),
                               budget_tokens=100_000)
            pdca = PDCA(judge, Ledger(root / "l.jsonl"), plan, flaky, {"correctness": "正确性"},
                        state_path=state)
            with self.assertRaises(RuntimeError):
                pdca.run(decl)
            self.assertTrue(state.exists(), "阶段通过后必须落 state")
            self.assertEqual(calls.count("起草"), 2, "起草阶段：规划 + 执行各一次")

            calls.clear()

            def good(role, stage, upstream, attempt, feedback="", requirements=""):
                calls.append(stage)
                if role.kind != "executor":
                    return ""
                return f"{S1}\n{S2}\n{S3}\n"

            pdca2 = PDCA(judge, Ledger(root / "l2.jsonl"), plan, good, {"correctness": "正确性"},
                         state_path=state, resume=True)
            report = pdca2.run(decl)
            self.assertTrue(report["passed"], report)
            self.assertNotIn("起草", calls, "续跑不该重跑已通过的阶段")


class ArtifactPersistTest(unittest.TestCase):
    def test_each_passed_stage_is_written_to_disk(self):
        """中间产物必须落盘：上一轮诊断时只能看到红字，看不到模型到底写了什么。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            judge = Judge(authority=("leader",))
            judge.register(fc.tested(fc.propose_sections("一段", [S1], ("correctness",))),
                           proposer="leader")
            plan = fo.parse_plan("目标", json.dumps({
                "roles": [
                    {"name": "执行", "kind": "executor", "duty": "写", "criteria": "齐", "budget": 10},
                    {"name": "验证", "kind": "verifier", "duty": "判", "criteria": "准", "budget": 5},
                    {"name": "规划", "kind": "planner", "duty": "拆", "criteria": "清", "budget": 5},
                ],
                "stages": [
                    {"name": "起草", "output": "草稿", "roles": ["规划", "执行"], "gate_criteria": ["一段"]},
                    {"name": "成稿", "output": "成稿", "roles": ["执行", "验证"], "gate_criteria": ["一段"]},
                ],
            }, ensure_ascii=False))
            pdca = PDCA(judge, Ledger(root / "l.jsonl"), plan,
                        lambda *a, **k: f"{S1}\n正文\n",
                        {"correctness": "正确性"}, artifact_dir=root / "stages")
            report = pdca.run(Declaration(goal="t", dims=("correctness",),
                                          criteria=("一段",), budget_tokens=100_000))
            self.assertTrue(report["passed"], report)
            files = sorted((root / "stages").glob("*.md"))
            self.assertEqual(len(files), 2, files)
            self.assertIn(S1, files[0].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()