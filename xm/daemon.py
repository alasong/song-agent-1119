"""无人值守 daemon：自己派活、自己跑测试、自己返工、自己记账。

与前面几轮的区别：整个过程没有人在环里。驱动方只负责启动一次，
之后每一轮由 daemon 调用模型、写文件、跑验收、决定是否继续。
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from xm.ledger import Ledger


@dataclass
class DaemonConfig:
    spec: str
    target_file: str
    tests: list[str]
    max_rounds: int = 8
    patience: int = 3


class Daemon:
    def __init__(self, ledger: Ledger, llm, cfg: DaemonConfig, workspace: str = "."):
        self.ledger = ledger
        self.llm = llm
        self.cfg = cfg
        self.ws = Path(workspace)
        self.no_progress = 0
        self.calls = 0
        self.green_at: int | None = None
        self.last_output = ""
        self.final_rc: int | None = None
        self.simplify = False

    def _prompt(self) -> str:
        target = self.ws / self.cfg.target_file
        current = target.read_text(encoding="utf-8") if target.exists() else "（文件还不存在）"
        feedback = self.last_output[-2000:] if self.last_output else "（还没有跑过测试）"
        simplify = "\\n注意：已连续多轮失败，请优先给出最简单能跑通的实现。\\n" if self.simplify else ""
        return f"""你在一个自动化循环里，没有人看着。目标：让验收测试全部通过。

## 规格
{self.cfg.spec}

## 当前 {self.cfg.target_file}
```python
{current}
```

## 上一次测试输出（末尾）
```
{feedback}
```
{simplify}
## 输出要求
只返回一个 ```python 代码块，内容是 {self.cfg.target_file} 的完整最终代码。
不要写解释，不要写多个代码块，不要省略任何已有功能。"""

    def _parse(self, text: str) -> str | None:
        blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.S)
        if not blocks:
            return None
        return max(blocks, key=len)

    def _run_tests(self) -> tuple[int, str]:
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", *self.cfg.tests, "-q"],
            cwd=self.ws, capture_output=True, text=True,
        )
        return proc.returncode, (proc.stderr or "") + (proc.stdout or "")

    def run(self) -> dict:
        for rnd in range(1, self.cfg.max_rounds + 1):
            self.ledger.append("dispatch", "daemon", {"round": rnd})
            try:
                raw = self.llm([{"role": "user", "content": self._prompt()}])
            except Exception as exc:  # 模型通道故障也要记账，不能静默
                self.ledger.append("llm_error", "daemon", {"round": rnd, "error": str(exc)[:300]})
                self.no_progress += 1
                continue
            self.calls += 1

            block = self._parse(raw)
            if block is None:
                self.no_progress += 1
                self.ledger.append("parse_failure", "daemon", {"round": rnd})
                self.last_output = "上一轮没有给出代码块，请严格按格式只返回一个 ```python 代码块。"
                continue

            target = self.ws / self.cfg.target_file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(block.strip() + "\n", encoding="utf-8")
            self.ledger.append("submission", "daemon", {"round": rnd, "bytes": len(block)})

            rc, out = self._run_tests()
            self.final_rc = rc
            self.ledger.append("test_result", "daemon", {"round": rnd, "rc": rc})
            if rc == 0:
                self.green_at = rnd
                self.ledger.append("completed", "daemon", {"round": rnd})
                break

            self.last_output = out
            first = next((l.strip() for l in out.splitlines() if l.strip().startswith(("FAIL:", "ERROR:"))), "")
            self.ledger.append("rejected", "daemon", {"round": rnd, "reason": first[:200]})
            self.no_progress += 1
            if self.no_progress >= self.cfg.patience:
                self.simplify = True
                self.ledger.append("downgrade", "daemon", {"no_progress": self.no_progress})

        return {
            "green_at_round": self.green_at,
            "rounds_used": self.calls,
            "final_rc": self.final_rc,
            "no_progress_peak": self.no_progress,
            "ledger_events": len(self.ledger.read()),
        }