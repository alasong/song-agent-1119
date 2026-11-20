"""三处新守卫的测试：

1. `sa2/forge/tools.py::_cases`：合格件必须同时覆盖「平铺正文」与「以 ### 子标题开头」，
   拒收件覆盖「缺件」「冒充件」；
2. `generate_checker`：坏检查器（把 `###` 当空章节）必须被拒且不留半成品，
   好检查器必须通过并包成 `exec` 判据；
3. `PDCA.run`：配了 artifact_dir 时，被拒阶段的候选文本要落盘。

全程不碰网络（llm 注入假实现），也不读 ~/xm-runs；临时目录用 TemporaryDirectory。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sa2.core.gate import Declaration           # noqa: E402
from sa2.core.judge import Criterion, Judge      # noqa: E402
from sa2.core.ledger import Ledger               # noqa: E402
from sa2.forge.org import OrgPlan, Role, Stage   # noqa: E402
from sa2.forge.tools import _cases, generate_checker  # noqa: E402
from sa2.loop.pdca import PDCA                   # noqa: E402

H1 = "## 一、标题"
H2 = "## 二、依据"
REQUIRED = [H1, H2]

# 坏检查器的最小形态：找到必需标题后，紧随的非空行以 # 开头就判「标题下没有内容」。
# 于是带 `### 子项一` 的合格件会被它误判成空章节。
BUGGY_CHECKER = '''import sys

HEADINGS = __HEADINGS__
lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
problems = []
for i, line in enumerate(lines):
    if line.strip() not in HEADINGS:
        continue
    nxt = next((l.strip() for l in lines[i + 1:] if l.strip()), "")
    if nxt.startswith("#"):
        problems.append(line.strip())
if problems:
    print("标题下没有内容：" + ", ".join(problems))
    sys.exit(1)
'''

# 正确检查器的最小形态：标题与其后到下一个 `## ` 之间的非空字符数 >= 1 才算有内容，
# `###` 不算截止；代码围栏内的标题不算数（冒充件要拒）。
CORRECT_CHECKER = '''import sys

HEADINGS = __HEADINGS__
lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
content = {h: 0 for h in HEADINGS}
current = None
fence = False
for line in lines:
    s = line.strip()
    if s.startswith("```"):
        fence = not fence
        continue
    if fence:
        continue
    if s in HEADINGS:
        current = s
        continue
    if current is not None:
        if s.startswith("## ") and not s.startswith("### "):
            current = None
            continue
        content[current] += len(s)
missing = [h for h in HEADINGS if content[h] < 1]
if missing:
    print("缺内容：" + ", ".join(missing))
    sys.exit(1)
'''


def _script(template: str) -> str:
    return template.replace("__HEADINGS__", repr(REQUIRED))


def _fake_llm(code: str):
    """假 llm：generate_checker 只把它当「返回一段带代码块的文本」。"""
    def llm(messages, max_tokens=1400):
        return "```python\n" + code.rstrip() + "\n```"
    return llm


class GuardrailsTest(unittest.TestCase):
    # 契约 1：_cases 必须给 4 条用例——两种合格件（平铺 / 以 ### 子标题开头）
    # 期望 rc=0，两种拒收件（缺件 / 冒充件）期望 rc=1。
    def test_cases_cover_flat_and_sectioned_good_plus_two_rejects(self):
        cases = _cases(REQUIRED)
        self.assertEqual(len(cases), 4)
        self.assertEqual([c[0] for c in cases],
                         ["合格件", "带子标题的合格件", "缺件", "冒充件"])
        good, sectioned, missing, fake = cases

        for label, text, rc, is_good in (good, sectioned):
            self.assertEqual((rc, is_good), (0, 1), label)
            for heading in REQUIRED:
                self.assertIn(heading, text, label)

        # 平铺正文与「正文以 ### 子标题开头」是两份不同的合格件，缺一不可。
        self.assertNotIn("###", good[1])
        self.assertIn("### 子项一", sectioned[1])
        self.assertTrue(sectioned[1].startswith(H1 + "\n\n### "),
                        sectioned[1][:40])

        # 缺件：最后一条标题缺席；冒充件：全部标题塞进代码围栏。
        self.assertEqual((missing[2], missing[3]), (1, 0))
        self.assertNotIn(H2, missing[1])
        self.assertIn(H1, missing[1])
        self.assertEqual((fake[2], fake[3]), (1, 0))
        self.assertTrue(fake[1].lstrip().startswith("```"), fake[1][:20])

    # 契约 2a：坏检查器被 _cases 的子标题合格件判红 → ValueError，且半成品被删。
    def test_generate_checker_rejects_buggy_script_and_cleans_out_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "tools"
            with self.assertRaises(ValueError) as ctx:
                generate_checker("写一份报告", REQUIRED,
                                 _fake_llm(_script(BUGGY_CHECKER)), out_dir,
                                 name="bad_checker")
            self.assertIn("工具未通过三反例", str(ctx.exception))
            # out_dir 目录可以留着，但不许留半成品脚本（实现路径会 unlink）。
            leftovers = list(out_dir.iterdir()) if out_dir.exists() else []
            self.assertEqual(leftovers, [])

    # 契约 2b：正确检查器通过准入，返回的判据是 exec；脚本本身可跑且合格 exit 0。
    def test_generate_checker_accepts_correct_script_as_exec_criterion(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "tools"
            path, crit = generate_checker(
                "写一份报告", REQUIRED, _fake_llm(_script(CORRECT_CHECKER)),
                out_dir, name="good_checker")
            self.assertTrue(path.exists())
            self.assertEqual(crit.kind, "exec")
            self.assertEqual(crit.scope, "stage")
            self.assertTrue(crit.self_tested)

            # 生成物要能被 `python3 脚本.py <file>` 直接跑；带 ### 子标题的合格件 exit 0。
            target = Path(tmp) / "target.md"
            target.write_text(_cases(REQUIRED)[1][1], encoding="utf-8")
            proc = subprocess.run([sys.executable, str(path), str(target)],
                                  capture_output=True, text=True, cwd=tmp)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    # 契约 3：阶段门恒判红时，被拒候选写到 rejected/<序号>-<安全化阶段名>-try<attempt>.md，
    # 内容等于 produce 的返回，且报告 passed=False。
    def test_pdca_rejected_stage_writes_candidate_to_artifact_dir(self):
        stage_name = "写作/初稿"
        produced = "被拒的候选正文\n第二行也在。"
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            judge = Judge()
            # 恒判红：exec 命令永远 exit 1，与文本无关。
            judge.register(Criterion(
                name="always_red", kind="exec",
                spec={"cmd": [sys.executable, "-c", "import sys; sys.exit(1)"]},
                dims=("d1",), self_tested=True, scope="stage"), proposer="leader")
            plan = OrgPlan(
                goal="写一份报告",
                roles=(Role(name="writer", kind="executor", duty="写",
                            criteria="按判据", budget=50_000),),
                stages=(Stage(name=stage_name, output="正文", roles=("writer",),
                              gate_criteria=("always_red",)),),
            )
            decl = Declaration(goal="写一份报告", dims=("d1",),
                               criteria=("always_red",), budget_tokens=50_000)

            def produce(role, stage, upstream, attempt, feedback, requirements):
                return produced

            loop = PDCA(judge=judge, ledger=Ledger(tmp / "ledger.jsonl"),
                        plan=plan, produce=produce, vocab={"d1"},
                        max_stage_attempts=1, artifact_dir=tmp / "artifacts")
            result = loop.run(decl)

            self.assertIs(result["passed"], False)
            self.assertEqual(result["dispatches"], 1)
            self.assertEqual(len(result["rejects"]), 1)
            # 序号取阶段下标 0，attempt 从 1 起；阶段名里的 `/` 被安全化成 `_`。
            rejected = tmp / "artifacts" / "rejected" / "0-写作_初稿-try1.md"
            self.assertTrue(rejected.exists(),
                            sorted(str(p) for p in (tmp / "artifacts").rglob("*")))
            self.assertEqual(rejected.read_text(encoding="utf-8"), produced)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()