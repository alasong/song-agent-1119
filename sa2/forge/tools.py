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
    """(名字, 文本, 期望退出码, 期望码是否为 0=合格)。"""
    body = "本节给出结论、依据与关键数据，满足本节的验收要求。"
    good = "\n\n".join(f"{item}\n{body}" for item in required) + "\n"
    missing = "\n".join(required[:-1]) + "\n正文略。\n"
    fake = "```\n" + "\n".join(required) + "\n```\n"
    return [("合格件", good, 0, 1), ("缺件", missing, 1, 0), ("冒充件", fake, 1, 0)]


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