"""HR 层：拿到目标，自己组队、定流程、分预算。

约束：
- 角色方案必须可机检：每个角色要有职责（只负责什么）和判据（怎么判它干得好）
- 必须有独立验证角色，否则等于自己给自己发毕业证
- 总预算不能超上限，否则组队等于烧钱
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

KINDS = {"planner", "researcher", "expert", "executor", "verifier", "curator"}


class HiringError(RuntimeError):
    """组队方案不可用。"""


@dataclass(frozen=True)
class Role:
    name: str
    kind: str
    duty: str
    criteria: str
    budget: int


@dataclass(frozen=True)
class OrgPlan:
    goal: str
    roles: list[Role]
    process: list[str]

    @property
    def total_budget(self) -> int:
        return sum(r.budget for r in self.roles)


def parse_plan(goal: str, raw: str, budget_cap: int) -> OrgPlan:
    """把模型输出解析成方案并校验。任何一条不满足就抛 HiringError。"""
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        raise HiringError("模型输出里没有 JSON")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise HiringError(f"JSON 解析失败：{exc}") from exc

    roles_raw = data.get("roles") or []
    if len(roles_raw) < 3:
        raise HiringError(f"角色只有 {len(roles_raw)} 个，至少 3 个")

    roles: list[Role] = []
    seen: set[str] = set()
    for i, item in enumerate(roles_raw, 1):
        name = str(item.get("name", "")).strip()
        kind = str(item.get("kind", "")).strip()
        duty = str(item.get("duty", "")).strip()
        criteria = str(item.get("criteria", "")).strip()
        budget = int(item.get("budget", 0))
        if not name or not duty or not criteria:
            raise HiringError(f"第 {i} 个角色缺 name/duty/criteria")
        if kind not in KINDS:
            raise HiringError(f"第 {i} 个角色 kind={kind!r} 不在 {sorted(KINDS)}")
        if name in seen:
            raise HiringError(f"角色名重复：{name}")
        if budget <= 0:
            raise HiringError(f"第 {i} 个角色预算必须为正")
        seen.add(name)
        roles.append(Role(name, kind, duty, criteria, budget))

    if not any(r.kind == "verifier" for r in roles):
        raise HiringError("没有独立验证角色（kind=verifier）——不允许自己给自己发毕业证")

    plan = OrgPlan(goal=goal, roles=roles, process=[str(p) for p in data.get("process") or []])
    if len(plan.process) < 2:
        raise HiringError("流程至少要 2 个阶段")
    if plan.total_budget > budget_cap:
        raise HiringError(f"总预算 {plan.total_budget} 超过上限 {budget_cap}")
    return plan


def plan_org(goal: str, llm, budget_cap: int = 200_000) -> OrgPlan:
    prompt = f"""你是这个组织的 HR。领导下达了一个目标，你要组一支能交付的团队。

目标：{goal}

要求：
- 3–6 个角色，kind 只能取：{sorted(KINDS)}
- 每个角色的 duty 写「只负责什么」，criteria 写「怎么判它干得好」（必须可机检或可验收）
- 必须有一个独立的 verifier 角色，它不参与生产
- 每个角色给 token 预算，总和不超过 {budget_cap}
- process 写交付流程的阶段顺序

只返回一个 JSON：
{{"roles":[{{"name":"","kind":"","duty":"","criteria":"","budget":0}}],"process":["阶段1","阶段2"]}}"""
    return parse_plan(goal, llm([{"role": "user", "content": prompt}]), budget_cap)