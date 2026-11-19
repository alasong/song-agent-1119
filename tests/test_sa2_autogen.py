"""三个自生成回路的自检：造判据（整组四反例）、造阶段判据（真分层）、造工具。"""
from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from sa2.core.gate import Declaration
from sa2.core.judge import Criterion, Judge
from sa2.core.ledger import Ledger
from sa2.forge import criteria as fc
from sa2.forge import org as fo
from sa2.forge import tools as ft
from sa2.loop.pdca import PDCA

S1, S2, S3, S4, S5 = ("## 一、a", "## 二、b", "## 三、c", "## 四、d", "## 五、e")

SPEC_MODEL_OUT = """必须包含：## 一、a
必须包含：## 二、b
必须包含：## 三、c
必须出现：单位经济
必须出现：不选"""


class ProposeSpecTest(unittest.TestCase):
    def test_model_spec_becomes_a_criterion_set(self):
        specs = fc.instantiate_all(SPEC_MODEL_OUT, ("correctness",))
        self.assertEqual([c.kind for c in specs], ["sections", "regex"])
        ok, fails = fc.test_set(specs)
        self.assertTrue(ok, fails)
        tested = fc.tested_set(specs)
        self.assertTrue(all(c.self_tested for c in tested))

    def test_sections_only_set_is_refused_because_shell_passes(self):
        """只有章节判据 = 判别力不足：标题齐全的空壳能毕业，必须拒。"""
        specs = fc.instantiate_all("必须包含：## 一、a\n必须包含：## 二、b", ("correctness",))
        ok, fails = fc.test_set(specs)
        self.assertFalse(ok)
        self.assertTrue(any("空壳件" in f for f in fails), fails)

    def test_vacuous_keyword_is_caught_by_the_missing_case(self):
        """要素词如果出现在章节标题里，缺件反例就抓得住这种空判据。"""
        specs = fc.instantiate_all("必须包含：## 一、单位经济\n必须出现：单位经济", ("correctness",))
        ok, _fails = fc.test_set(specs)
        self.assertFalse(ok)

    def test_unsatisfiable_spec_is_caught_by_the_model_sample(self):
        """模型把要求句子当成必现标题：它自己给的样例都过不了，必须整组拒掉。"""
        raw = """### SPEC
必须包含：素材条目总数 ≥ 40，且每条素材含「来源标注」
必须出现：来源标注
### SAMPLE
## 一、素材清单
共 12 条，包含来源标注。
"""
        made = {"raw": raw, "spec": fc._blocks(raw)[0], "sample": fc._blocks(raw)[1]}
        specs = fc.instantiate_all(made["spec"], ("correctness",))
        ok, fails = fc.test_set(specs, sample=made["sample"])
        self.assertFalse(ok)
        self.assertTrue(any("样例自证" in f for f in fails) or any("缺件" in f for f in fails), fails)

    def test_keyword_lists_are_split(self):
        crit = fc.propose_content("要素", ["来源标注、分类标签"], ("correctness",))
        self.assertEqual(crit.spec["patterns"], ["来源标注", "分类标签"])


    def test_out_of_slice_sections_are_trimmed_not_kept(self):
        """模型爱把整篇都写出来：结构由系统裁，不靠它自觉。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            judge = Judge(authority=("leader",))
            judge.register(fc.tested(fc.propose_sections("第一片", [S1], ("correctness",))),
                           proposer="leader")
            judge.register(fc.tested(fc.propose_sections("第二片", [S2, S3], ("correctness",))),
                           proposer="leader")
            plan = fo.parse_plan("目标", json.dumps({
                "roles": [
                    {"name": "执行", "kind": "executor", "duty": "写", "criteria": "齐", "budget": 5},
                    {"name": "验证", "kind": "verifier", "duty": "判", "criteria": "准", "budget": 5},
                    {"name": "规划", "kind": "planner", "duty": "拆", "criteria": "清", "budget": 5},
                ],
                "stages": [
                    {"name": "一段", "output": "a", "roles": ["规划", "执行"],
                     "gate_criteria": ["第一片"]},
                    {"name": "二段", "output": "b", "roles": ["执行", "验证"],
                     "gate_criteria": ["第二片"], "mode": "append"},
                ],
            }, ensure_ascii=False))

            def produce(role, stage, upstream, attempt, feedback="", requirements=""):
                if role.kind != "executor":
                    return ""
                # 故意写整篇：一段二段三段全写
                return f"{S1}\n甲\n{S2}\n乙\n{S3}\n丙\n"

            pdca = PDCA(judge, Ledger(root / "l.jsonl"), plan, produce,
                        {"correctness": "正确性"})
            report = pdca.run(Declaration(goal="t", dims=("correctness",),
                                          criteria=("第一片", "第二片"), budget_tokens=100_000))
            self.assertTrue(report["passed"], report)
            self.assertEqual(report["text"].count(S1), 1)
            self.assertEqual(report["text"].count(S2), 1)
            self.assertEqual(report["text"].count(S3), 1)


class SliceTest(unittest.TestCase):
    def test_slices_cover_every_heading_exactly_once(self):
        heads = [f"## 第{i}节" for i in range(1, 8)]
        chunks = fc.plan_slices(heads, 3)
        flat = [h for chunk in chunks for h in chunk]
        self.assertEqual(sorted(flat), sorted(heads))
        self.assertEqual(len(flat), len(set(flat)), "切片之间不许重叠")

    def test_slice_sample_keeps_only_its_own_sections(self):
        sample = "## 一、a\nA\n## 二、b\nB\n## 三、c\nC\n"
        piece = fc.slice_sample(sample, ["## 二、b"])
        self.assertIn("## 二、b", piece)
        self.assertNotIn("## 一、a", piece)
        self.assertNotIn("## 三、c", piece)

    def test_checker_rejects_duplicated_sections(self):
        """重复章节必须判红：这是「合规的绿、不是好文档的绿」那个缺陷的守门人。"""
        sample = "## 一、a\n" + "正文" * 20 + "\n## 二、b\n" + "正文" * 20
        with tempfile.TemporaryDirectory() as tmp:
            _, crit = ft.checker_from_sections(sample, tmp, name="dup")
            judge = Judge(authority=("leader",))
            judge.register(crit, proposer="leader")
            once = "## 一、a\n" + "正文" * 20 + "\n## 二、b\n" + "正文" * 20
            twice = once + "\n" + once
            self.assertTrue(judge.run(crit.name, once).ok)
            verdict = judge.run(crit.name, twice)
            self.assertFalse(verdict.ok)
            self.assertTrue(any("重复" in p for p in verdict.problems), verdict.problems)


class StageScopeTest(unittest.TestCase):
    ORG = json.dumps({
        "roles": [
            {"name": "规划", "kind": "planner", "duty": "拆", "criteria": "可验收", "budget": 10},
            {"name": "执行", "kind": "executor", "duty": "写", "criteria": "齐全", "budget": 20},
            {"name": "验证", "kind": "verifier", "duty": "只判", "criteria": "有结论", "budget": 5},
        ],
        "stages": [
            {"name": "起草", "output": "前两节", "roles": ["规划", "执行"], "gate_criteria": []},
            {"name": "成稿", "output": "五节齐", "roles": ["执行", "验证"], "gate_criteria": []},
        ],
    }, ensure_ascii=False)

    def test_draft_plan_allows_empty_gates_then_attaches(self):
        plan = fo.parse_plan("目标", self.ORG, require_gates=False)
        self.assertEqual(plan.stages[0].gate_criteria, ())
        with self.assertRaises(fo.OrgError):
            fo.attach_stage_gates(plan, {"起草": ("a",)})
        attached = fo.attach_stage_gates(plan, {"起草": ("一段",), "成稿": ("五段",)})
        self.assertEqual(attached.stages[0].gate_criteria, ("一段",))

    def test_stage_gates_no_longer_force_a_full_document(self):
        """起草阶段只判前两节：中间产出不必先长成完整五节。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            judge = Judge(authority=("leader",))
            stage_crit = fc.tested(fc.propose_sections("起草·章节", [S1, S2], ("correctness",)))
            stage_crit = fc.replace(stage_crit, scope="stage")
            delivery = fc.tested(fc.propose_sections("交付·章节", [S1, S2, S3, S4, S5],
                                                     ("correctness",)))
            for crit in (stage_crit, delivery):
                judge.register(crit, proposer="leader")

            plan = fo.parse_plan("目标", self.ORG, require_gates=False)
            plan = fo.attach_stage_gates(plan, {"起草": ("起草·章节",), "成稿": ("交付·章节",)})

            def produce(role, stage, upstream, attempt, feedback="", requirements=""):
                if role.kind != "executor":
                    return ""
                if stage == "起草":
                    return f"{S1}\n{S2}\n"                      # 只有前两节，但够本阶段
                return "\n".join([S1, S2, S3, S4, S5]) + "\n"

            pdca = PDCA(judge, Ledger(root / "l.jsonl"), plan, produce, {"correctness": "正确性"},
                        max_stage_attempts=2)
            report = pdca.run(Declaration(goal="t", dims=("correctness",),
                                          criteria=("交付·章节",), budget_tokens=100_000))
            self.assertTrue(report["passed"], report)
            self.assertEqual(report["rejects"], [], "起草阶段不该因为不是完整文档被拒")

    def test_last_stage_must_carry_delivery_gates(self):
        """交付要求必须进最后一个阶段的可见范围，否则没人被要求写它。"""
        plan = fo.parse_plan("目标", self.ORG, require_gates=False)
        plan = fo.attach_stage_gates(plan, {"起草": ("一段",), "成稿": ("五段",)})
        plan = fo.close_with_delivery(plan, ("交付·章节",))
        self.assertEqual(plan.stages[-1].gate_criteria, ("五段", "交付·章节"))
        self.assertEqual(plan.stages[0].gate_criteria, ("一段",))

    def test_delivery_reaches_the_writer_before_the_assembly_stage(self):
        plan = fo.parse_plan("目标", self.ORG, require_gates=False)
        stages = list(plan.stages)
        stages[-1] = fo.replace(stages[-1], mode="append")
        plan = fo.replace(plan, stages=tuple(stages))
        plan = fo.attach_stage_gates(plan, {"起草": ("一段",), "成稿": ("五段",)})
        plan = fo.close_with_delivery(plan, ("交付·章节",))
        self.assertIn("交付·章节", plan.stages[-2].gate_criteria,
                      "写正文的阶段没拿到交付要求")


    def test_append_mode_keeps_the_previous_document(self):
        """定稿阶段是装配：上游全文 + 本阶段补充，而不是把前面整篇丢掉。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            judge = Judge(authority=("leader",))
            judge.register(fc.tested(fc.propose_sections("全篇", [S1, S2], ("correctness",))),
                           proposer="leader")
            plan = fo.parse_plan("目标", self.ORG, require_gates=False)
            stages = list(plan.stages)
            stages[-1] = fo.replace(stages[-1], gate_criteria=("全篇",), mode="append")
            plan = fo.replace(plan, stages=tuple(stages))
            plan = fo.attach_stage_gates(plan, {"起草": (), "成稿": ("全篇",)})

            def produce(role, stage, upstream, attempt, feedback="", requirements=""):
                if role.kind != "executor":
                    return ""
                return f"{S2}\n定稿补充。\n" if stage == "成稿" else f"{S1}\n草稿正文。\n"

            pdca = PDCA(judge, Ledger(root / "l.jsonl"), plan, produce,
                        {"correctness": "正确性"}, max_stage_attempts=2)
            report = pdca.run(Declaration(goal="t", dims=("correctness",),
                                          criteria=("全篇",), budget_tokens=100_000))
            self.assertTrue(report["passed"], report)
            self.assertIn(S1, report["text"], "上游正文被丢了")
            self.assertIn(S2, report["text"])



class ToolTest(unittest.TestCase):
    SCRIPT = textwrap.dedent('''
        import sys
        text = open(sys.argv[1], encoding="utf-8").read()
        fence, body = False, []
        for line in text.splitlines():
            if line.strip().startswith("```"):
                fence = not fence
                continue
            if not fence:
                body.append(line.strip())
        need = ["## 一、a", "## 二、b"]
        missing = [h for h in need if h not in body]
        for h in missing:
            print("缺章节：" + h)
        sys.exit(1 if missing else 0)
    ''').strip()

    class FakeLLM:
        def __init__(self, code):
            self.code = code

        def __call__(self, messages, max_tokens=1000):
            return f"```python\n{self.code}\n```"

    def test_generated_checker_is_admitted_after_three_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, crit = ft.generate_checker("写东西", [S1, S2], self.FakeLLM(self.SCRIPT), tmp)
            self.assertTrue(path.exists())
            self.assertEqual(crit.kind, "exec")
            self.assertEqual(crit.scope, "stage")
            judge = Judge(authority=("leader",))
            judge.register(crit, proposer="leader")
            self.assertTrue(judge.run(crit.name, f"{S1}\n{S2}\n正文\n").ok)
            self.assertFalse(judge.run(crit.name, f"{S1}\n正文\n").ok)
            self.assertFalse(judge.run(crit.name, f"```\n{S1}\n{S2}\n```").ok)

    def test_bad_checker_is_refused_and_deleted(self):
        bad = "import sys\nsys.exit(0)\n"        # 永远合格：三反例里缺件必红
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                ft.generate_checker("写东西", [S1, S2], self.FakeLLM(bad), tmp)
            self.assertEqual(list(Path(tmp).glob("*.py")), [], "没通过的工具不许留在盘上")


if __name__ == "__main__":
    unittest.main()