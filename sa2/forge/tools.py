"""造工具：让系统自己写一个可执行检查器，用它当判据。

这是三个自生成回路里最后补上的一条。它和「造判据」的区别是形态：
- 造判据：把需求翻译成 `sections` / `regex` 这类声明式判据；
- 造工具：**生成一段代码**，能做的判定比声明式判据更复杂（比如算比例、比对两份文本）。

因为生成物是可执行代码，准入比声明式判据更严：
1. 必须在临时目录、限时、只用标准库的条件下跑过三反例（合格件过 / 缺件拒 / 冒充件拒）；
2. 三例全对才把脚本留下来并包成 `exec` 判据；
3. 任何一例不对就**拒绝这个工具**并把原因带回去，不许「先注册再说」。

风险写在明处：这不是安全沙箱，只是限时 + 临时目录。
工具由模型生成、由本机解释器执行，所以只应在你愿意跑模型生成代码的场合使用。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from ..core.judge import Criterion

TOOL_PROMPT = """写一个 Python 3 检查脚本，判断一份 Markdown 文档是否合格。

任务背景：{goal}

必须检查的东西：
{checks}

硬要求：
- 用法：`python3 脚本.py <待检文件>`；合格 exit 0，不合格 exit 1
- 不合格时把原因打印到 stdout，每行一条
- 只用标准库；不要读网络；不要写文件
- 只输出一个 ```python 代码块，不要解释

注意：
- 代码围栏（```）里的内容不算数——把标题或关键词塞进围栏里，也必须判不合格。
- 只判**结构**：要求的标题是否存在、标题下是否有内容。不要要求每一节出现特定关键词，
  也不要要求条目数量——合格样例的正文很短。
- 一节的内容可以被组织成若干 `###` 子标题：子标题本身不算空节，子标题下面的正文算内容。
  只有当标题下到下一个 `## ` 之间一个字都没有时，才算「标题下没有内容」。
"""


def _extract_code(raw: str) -> str:
    """取代码块。

    这里**必须是贪婪匹配到最后一个 ```**：检查器的源码里本身就会含 ``` 字面量
    （判「内容在不在代码围栏里」必须提这个字符串），非贪婪会在第一个字面量处截断，
    把好好的脚本切成语法错误——这条是实测踩出来的，别改回 `.*?`。
    """
    text = raw or ""
    match = re.search(r"```(?:python)?[ \t]*\r?\n(.*)```", text, re.S)
    if match:
        return match.group(1).strip()
    match = re.search(r"```(?:python)?[ \t]*\r?\n(.*)$", text, re.S)
    return (match.group(1) if match else text).strip()


def _cases(required: list[str]) -> list[tuple[str, str, int, int]]:
    """(名字, 文本, 期望退出码, 期望码是否为 0=合格)。

    合格件给两份：平铺正文一份、**正文以子标题开头**一份。后者不是多余的——
    实测生成出来的检查器把「标题下第一行是 `###`」当成空章节，于是任何分小节的
    正文都被判红（真跑：复合题面连续两轮死在这一条上，正文其实有两百多字）。
    判定权只能落在样例上，所以把这种正样例也钉进准入：检查器不接受它，
    就在造的时候退回去，而不是等真活干到一半才判红。
    """
    body = "本节给出结论、依据与关键数据，满足本节的验收要求。"
    good = "\n\n".join(f"{item}\n{body}" for item in required) + "\n"
    sectioned = "\n\n".join(f"{item}\n\n### 子项一\n{body}\n\n### 子项二\n{body}"
                            for item in required) + "\n"
    missing = "\n".join(required[:-1]) + "\n正文略。\n"
    fake = "```\n" + "\n".join(required) + "\n```\n"
    return [("合格件", good, 0, 1), ("带子标题的合格件", sectioned, 0, 1),
            ("缺件", missing, 1, 0), ("冒充件", fake, 1, 0)]


def _run(path: Path, text: str, timeout: int) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "target.md"
        target.write_text(text, encoding="utf-8")
        try:
            # 只给最小环境：生成的代码不该看得到任何密钥类环境变量
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"}
            proc = subprocess.run([sys.executable, str(path), str(target)],
                                  capture_output=True, text=True, cwd=tmp, timeout=timeout,
                                  env=env)
        except subprocess.TimeoutExpired:
            return 124, f"超时（>{timeout}s）"
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def generate_checker(goal: str, required, llm, out_dir: str | Path,
                     name: str = "checker", timeout: int = 10) -> tuple[Path, Criterion]:
    """生成并验证一个检查器。验证不过就抛，不返回半成品。"""
    required = [str(x).strip() for x in required if str(x).strip()]
    if not required:
        raise ValueError("没有可检查的条目，无法造工具")
    prompt = TOOL_PROMPT.format(goal=goal, checks="\n".join(f"- {x}" for x in required))
    code = _extract_code(llm([{"role": "user", "content": prompt}], 1400))
    if not code:
        raise ValueError("模型没有输出代码块")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.py"
    path.write_text(code + "\n", encoding="utf-8")

    fails: list[str] = []
    for label, text, expect_rc, expect_zero in _cases(required):
        rc, detail = _run(path, text, timeout)
        ok = (rc == 0) if expect_zero else (rc != 0)
        if not ok:
            fails.append(f"{label}：期望{'合格' if expect_zero else '拒收'}，"
                         f"实际 rc={rc}（{detail.strip()[:80]}）")
    if fails:
        path.unlink(missing_ok=True)
        raise ValueError("工具未通过三反例：" + "；".join(fails))

    crit = Criterion(name=f"{name}·工具", kind="exec",
                     spec={"cmd": [sys.executable, str(path), "{target}"]},
                     dims=(), self_tested=True, scope="stage")
    return path, crit

CHECKER_TEMPLATE = '''import sys
HEADINGS = __HEADINGS__
MIN = __MIN__
problems = []
text = open(sys.argv[1], encoding="utf-8").read()
fence = False
bodies = {}
current = None
for line in text.splitlines():
    s = line.strip()
    if s.startswith("```"):
        fence = not fence
        continue
    if fence:
        continue
    if s in HEADINGS:
        current = s
        bodies[current] = []
        continue
    if current is not None:
        bodies[current].append(line)
problems = []
seen = {}
for line in text.splitlines():
    s2 = line.strip()
    if not s2.startswith("## ") or fence:
        continue
    if s2 in HEADINGS:
        seen[s2] = seen.get(s2, 0) + 1
    elif __ALLOW_FOREIGN__:
        continue          # 追加阶段：上游的合法章节不算越界
    else:
        problems.append("越界章节：" + s2 + "（本阶段只该写 " + " / ".join(HEADINGS) + "）")
for h, times in seen.items():
    if times > 1:
        problems.append("章节重复：" + h + " 出现 " + str(times) + " 次")
for h in HEADINGS:
    body = "".join(bodies.get(h, []))
    n = len([c for c in body if not c.isspace()])
    if h not in bodies:
        problems.append("缺章节：" + h)
    elif n < MIN:
        problems.append("章节正文过短：" + h + " 只有 " + str(n) + " 字")
for p in problems:
    print(p)
sys.exit(1 if problems else 0)
'''


def headings_of(sample: str) -> list[str]:
    return [line.strip() for line in (sample or "").splitlines()
            if line.strip().startswith("## ")]


def _bodies(sample: str) -> list[int]:
    heads = []
    body: list[int] = []
    current = 0
    for line in (sample or "").splitlines():
        if line.strip().startswith("## "):
            if heads:
                body.append(current)
            heads.append(line.strip())
            current = 0
        else:
            current += len([c for c in line if not c.isspace()])
    if heads:
        body.append(current)
    return body


def checker_from_sections(sample: str, out_dir: str | Path, name: str = "sections_checker",
                          min_chars: int | None = None,
                          allow_foreign: bool = False) -> tuple[Path, Criterion]:
    """从模型的合格样例**确定性**生成检查器：标题齐全 + 每节正文不少于下限。

    为什么不用模型写检查器：一是每阶段一次太贵，二是实测模型写的检查器常常过严
    （要求每节出现特定关键词），把好交付判死。样例本身是模型给的、天然可满足，
    从它生成工具就把「可满足性」变成了构造性质，而不是事后再验。
    """
    heads = headings_of(sample)
    if not heads:
        raise ValueError("样例里没有 `## ` 标题，无法生成章节检查器")
    sizes = [n for n in _bodies(sample) if n > 0]
    if min_chars is None:
        # 取样例里最短一节的六成做下限：样例必然过，同时又逼着真交付写出实质正文
        min_chars = max(10, int(min(sizes) * 0.6)) if sizes else 10

    code = (CHECKER_TEMPLATE.replace("__HEADINGS__", repr(heads))
            .replace("__MIN__", str(min_chars))
            .replace("__ALLOW_FOREIGN__", "True" if allow_foreign else "False"))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.py"
    path.write_text(code, encoding="utf-8")

    cases = [("样例自身", sample, True),
             ("缺章节", "\n".join(line for line in sample.splitlines()
                                  if line.strip() != heads[-1]), False),
             ("冒充件", "```\n" + "\n".join(heads) + "\n```\n" + "正文" * 200, False)]
    if not allow_foreign:
        # 只有「从零写」的阶段才该拒越界；追加阶段的上游章节是合法的，
        # 拿越界案去测它必然误判，进而把一个好检查器退回成纯章节判据。
        cases.append(("越界章节", sample + "\n## 九、不该出现的章节\n" + "正文" * 20, False))
    fails: list[str] = []
    for label, text, expect_ok in cases:
        rc, detail = _run(path, text, 10)
        if (rc == 0) != expect_ok:
            fails.append(f"{label}：期望{'合格' if expect_ok else '拒收'}，实际 rc={rc}"
                         f"（{detail.strip()[:80]}）")
    if fails:
        path.unlink(missing_ok=True)
        raise ValueError("章节检查器未通过三反例：" + "；".join(fails))

    crit = Criterion(name=f"{name}·工具", kind="exec",
                     spec={"cmd": [sys.executable, str(path), "{target}"]},
                     dims=(), self_tested=True, scope="stage")
    return path, crit
