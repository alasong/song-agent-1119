"""任务来源：从 ROADMAP 的进度表里取下一个待办。

这是「活性组织」的第一环——目标树 → 任务。现在目标树还是一张手写表格，
所以调度是半自动的：只解决「下一个做什么」，还不解决「为什么是这些目标」。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SECTION = "## 7. 当前进度"


@dataclass(frozen=True)
class Task:
    name: str
    status: str
    evidence: str

    @property
    def done(self) -> bool:
        return "完成" in self.status and "未" not in self.status

    @property
    def slug(self) -> str:
        ascii_part = re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-")
        return ascii_part or "task"


def load(roadmap: str | Path) -> list[Task]:
    text = Path(roadmap).read_text(encoding="utf-8")
    if SECTION not in text:
        raise ValueError(f"{roadmap} 里找不到 {SECTION}")
    body = text.split(SECTION, 1)[1]
    tasks: list[Task] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            if tasks:  # 表格结束
                break
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2 or cells[0] in ("里程碑", "") or set(cells[0]) <= set("-: "):
            continue
        tasks.append(Task(cells[0], cells[1], cells[2] if len(cells) > 2 else ""))
    return tasks


def next_ready(tasks: list[Task]) -> Task | None:
    for task in tasks:
        if not task.done:
            return task
    return None