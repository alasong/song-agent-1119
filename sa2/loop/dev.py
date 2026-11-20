"""M1：代码工单回路——写文件 → 跑验收 → 失败带输出重做。

这是 1.0 daemon 的六步在 2.0 里的最小形态：只改**工单声明的那个文件**，
验收命令由工单给（调用方负责它可信），失败输出原样喂回下一轮。

边界：
- 只有落在 root 内的 target 才允许写；越界在写之前就拒，一次模型都不调。
- 整文件替换，不做 patch：目标文件本来就小；patch 解析留到以后。
- 失败时不回滚：保留最后一次尝试，便于看它错在哪。
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class DevRefused(RuntimeError):
    """工单本身不合法（越界、目标不存在等），不是模型的问题。"""


@dataclass
class DevTicket:
    id: str
    goal: str
    target: str                 # 相对 root 的路径
    test_cmd: list[str]         # 验收命令（cwd=root）
    max_rounds: int = 3


def _extract_code(text: str) -> str | None:
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text or "", re.S)
    return match.group(1) if match else None


class DevLoop:
    def __init__(self, llm, ledger, root, max_tokens: int = 2000, timeout: int = 120):
        self.llm = llm
        self.ledger = ledger
        self.root = Path(root).resolve()
        self.max_tokens = max_tokens
        self.timeout = timeout

    def run(self, ticket: DevTicket) -> dict:
        target = (self.root / ticket.target).resolve()
        if not target.is_relative_to(self.root):
            raise DevRefused(f"目标越界：{ticket.target}")
        if not target.exists():
            raise DevRefused(f"目标不存在：{ticket.target}（M1 只改已有文件）")

        self.ledger.append("dev_start", ticket.id,
                           {"goal": ticket.goal, "target": ticket.target,
                            "test_cmd": list(ticket.test_cmd)})
        feedback = ""
        output = ""
        rounds = max(1, int(ticket.max_rounds))
        for attempt in range(1, rounds + 1):
            current = target.read_text(encoding="utf-8")
            prompt = self._prompt(ticket, current, feedback)
            text = self.llm([{"role": "user", "content": prompt}], self.max_tokens) or ""
            code = _extract_code(text)
            if code is None:
                output = "输出里没有 ```python 代码块"
                self.ledger.append("dev_no_code", ticket.id, {"round": attempt})
                feedback = output
                continue

            target.write_text(code if code.endswith("\n") else code + "\n", encoding="utf-8")
            self.ledger.append("dev_apply", ticket.id,
                               {"round": attempt, "chars": len(code)})
            result = subprocess.run(ticket.test_cmd, cwd=str(self.root),
                                    capture_output=True, text=True, timeout=self.timeout)
            output = (result.stdout or "") + (result.stderr or "")
            self.ledger.append("dev_test", ticket.id,
                               {"round": attempt, "rc": result.returncode,
                                "tail": output[-800:]})
            if result.returncode == 0:
                self.ledger.append("dev_done", ticket.id, {"round": attempt})
                return {"passed": True, "rounds": attempt, "rc": 0,
                        "output": output, "text": target.read_text(encoding="utf-8")}
            feedback = output[-1500:]

        self.ledger.append("dev_failed", ticket.id,
                           {"rounds": rounds, "target": ticket.target})
        return {"passed": False, "rounds": rounds, "rc": 1, "output": output,
                "text": target.read_text(encoding="utf-8")}

    @staticmethod
    def _prompt(ticket: DevTicket, current: str, feedback: str) -> str:
        retry = ""
        if feedback:
            retry = ("\n上一轮你改完后验收命令失败，输出如下：\n```\n"
                     f"{feedback}\n```\n请修掉它。\n")
        return (f"你是这个仓库的开发者。任务：{ticket.goal}\n\n"
                f"要改的文件：{ticket.target}\n它现在的内容：\n```python\n{current}\n```\n"
                f"{retry}\n"
                "只输出修改后的完整文件（一个 ```python 代码块），不要解释，不要改其它文件。")