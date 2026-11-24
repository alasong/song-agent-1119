"""造依赖断言单：目标 + 编制 → 每阶段一份可校验的断言单。

生成方只 propose：产出的东西必须过 `core.deps.check`，门在 core 判。
这一步多花一次模型调用，所以默认不开（`sa2_live --require-deps` 才走）；
不花这次调用，就没有"每一步都想过依赖"的证据。
"""
from __future__ import annotations

import json
import re

from ..core import deps

PROMPT = """给下面这个目标的每个阶段写一份「依赖断言单」。

阶段：{stages}
目标：{goal}

规则：
- 每个阶段至少一条依赖，不许交空单；
- 每条写五件事：name（名字）、cls（只能是 team / method / process / tool / other）、
  claim（可证伪的断言，要写出可观察结果：数、路径、命令、rc）、
  verify（验法，必须以 cmd: / path: / value: / read: 之一开头）、
  if_false（这条不成立时怎么办：换用 / 造工具 / 降级）；
- 现有工具或方法够用就直接复用，不够才登记成缺口；
- gaps 只能填 items 里「现在还没就绪」的 name（原样字符串，不要写解释）；没有缺口就填 []，
  也不要为了填而编一个新名字。

只返回 JSON：
{{"stages": {{"<阶段名>": {{"items": [{{"name": "", "cls": "", "claim": "", "verify": "", "if_false": ""}}], "gaps": []}}}}}}
"""


def propose(goal: str, plan, llm, max_tokens: int = 1200) -> dict[str, deps.DepNote]:
    """一次调用产出全部阶段的断言单；任何一个阶段不合格，整体拒。"""
    stages = [stage.name for stage in plan.stages]
    raw = llm([{"role": "user", "content": PROMPT.format(
        goal=goal, stages="、".join(stages))}], max_tokens=max_tokens)
    match = re.search(r"\{.*\}", raw or "", re.S)
    if not match:
        raise deps.DepError("模型输出里没有 JSON")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise deps.DepError(f"断言单 JSON 解析失败：{exc}") from exc
    got = data.get("stages")
    if not isinstance(got, dict):
        raise deps.DepError("断言单缺 stages 对象")
    out: dict[str, deps.DepNote] = {}
    problems: list[str] = []
    for stage in stages:
        note = deps.parse({"step": stage, **(got.get(stage) or {})})
        problems.extend(f"{stage}：{problem}" for problem in deps.check(note))
        out[stage] = note
    if problems:
        raise deps.DepError("；".join(problems))
    return out