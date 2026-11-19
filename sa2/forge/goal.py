"""目标拆解：领到一个目标，拆成 1–5 个可分别验收的子任务。

2.0 的拆解必须带维度：每个子任务声明它覆盖哪几维，
否则下游没法回答「这个子任务算不算完成」。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass


class GoalError(RuntimeError):
    """拆解不合格。"""


@dataclass(frozen=True)
class Subtask:
    name: str
    deliverable: str
    dims: tuple[str, ...]


def parse(goal: str, raw: str, vocab, max_n: int = 5) -> tuple[Subtask, ...]:
    match = re.search(r"\{.*\}", raw or "", re.S)
    if not match:
        raise GoalError("模型输出里没有 JSON")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise GoalError(f"JSON 解析失败：{exc}") from exc

    items = data.get("subtasks") or []
    if not 1 <= len(items) <= max_n:
        raise GoalError(f"子任务 {len(items)} 个，要求 1–{max_n}")
    out: list[Subtask] = []
    seen: set[str] = set()
    for i, item in enumerate(items, 1):
        name = str(item.get("name", "")).strip()
        deliverable = str(item.get("deliverable", "")).strip()
        dims = tuple(str(d).strip() for d in (item.get("dims") or []) if str(d).strip())
        if not name or not deliverable:
            raise GoalError(f"第 {i} 个子任务缺 name/deliverable")
        if name in seen:
            raise GoalError(f"子任务重名：{name}")
        if not dims:
            raise GoalError(f"子任务 {name} 没声明维度")
        unknown = [d for d in dims if d not in vocab]
        if unknown:
            raise GoalError(f"子任务 {name} 用了词表外维度：{unknown}")
        seen.add(name)
        out.append(Subtask(name, deliverable, dims))
    return tuple(out)


def decompose(goal: str, llm, vocab, max_n: int = 5) -> tuple[Subtask, ...]:
    prompt = f"""把下面这个目标拆成可分别验收的子任务。

目标：{goal}

要求：
- 1–{max_n} 个子任务，名字不重复
- 每个子任务写清交付物是什么
- 每个子任务声明覆盖哪些维度，维度只能取：{sorted(vocab)}
- 拆不动就只给一个子任务，不要硬凑

只返回一个 JSON：
{{"subtasks":[{{"name":"","deliverable":"","dims":[""]}}]}}"""
    return parse(goal, llm([{"role": "user", "content": prompt}]), vocab, max_n)