"""编制与流程：阶段自己绑角色，不允许「每个角色在每个阶段都干一遍」。

sa 1.0 的调度器是 `for stage: for role:` 两层循环，6 角色 × 7 阶段 = 42 次派活，
不管这个角色和这个阶段有没有关系。2.0 把「谁在哪个阶段干活」变成数据：
Stage.roles 非空且是全体角色的**真子集**（至少有一处不是全连接），门直接判这一条。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

KINDS = {"planner", "researcher", "expert", "executor", "verifier", "curator"}


class OrgError(RuntimeError):
    """编制不合格。"""


@dataclass(frozen=True)
class Role:
    name: str
    kind: str
    duty: str
    criteria: str
    budget: int


@dataclass(frozen=True)
class Stage:
    name: str
    output: str
    roles: tuple[str, ...]
    gate_criteria: tuple[str, ...]


@dataclass(frozen=True)
class OrgPlan:
    goal: str
    roles: tuple[Role, ...]
    stages: tuple[Stage, ...]

    @property
    def total_budget(self) -> int:
        return sum(r.budget for r in self.roles)

    def role(self, name: str) -> Role:
        for r in self.roles:
            if r.name == name:
                return r
        raise OrgError(f"没有这个角色：{name}")

    def dispatches(self) -> int:
        return sum(len(s.roles) for s in self.stages)


def parse_plan(goal: str, raw: str, budget_cap: int = 200_000) -> OrgPlan:
    match = re.search(r"\{.*\}", raw or "", re.S)
    if not match:
        raise OrgError("模型输出里没有 JSON")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise OrgError(f"JSON 解析失败：{exc}") from exc

    roles_raw = data.get("roles") or []
    if len(roles_raw) < 3:
        raise OrgError(f"角色只有 {len(roles_raw)} 个，至少 3 个")
    roles: list[Role] = []
    seen: set[str] = set()
    for i, item in enumerate(roles_raw, 1):
        name = str(item.get("name", "")).strip()
        kind = str(item.get("kind", "")).strip()
        duty = str(item.get("duty", "")).strip()
        criteria = str(item.get("criteria", "")).strip()
        budget = int(item.get("budget", 0) or 0)
        if not name or not duty or not criteria:
            raise OrgError(f"第 {i} 个角色缺 name/duty/criteria")
        if kind not in KINDS:
            raise OrgError(f"第 {i} 个角色 kind={kind!r} 不在 {sorted(KINDS)}")
        if name in seen:
            raise OrgError(f"角色名重复：{name}")
        if budget <= 0:
            raise OrgError(f"第 {i} 个角色预算必须为正")
        if duty == criteria:
            raise OrgError(f"角色 {name} 的 duty 与 criteria 是同一句话：职责和判法是两件事")
        seen.add(name)
        roles.append(Role(name, kind, duty, criteria, budget))

    if not any(r.kind == "verifier" for r in roles):
        raise OrgError("没有独立验证角色（kind=verifier）——不允许自己给自己发毕业证")

    stages_raw = data.get("stages") or data.get("process") or []
    if len(stages_raw) < 2:
        raise OrgError(f"阶段只有 {len(stages_raw)} 个，至少 2 个")
    stages: list[Stage] = []
    for i, item in enumerate(stages_raw, 1):
        if isinstance(item, str):
            raise OrgError(f"第 {i} 个阶段只给了名字：阶段必须绑角色与阶段门")
        name = str(item.get("name", "")).strip()
        output = str(item.get("output", "")).strip()
        names = tuple(str(x).strip() for x in (item.get("roles") or []) if str(x).strip())
        gates = tuple(str(x).strip() for x in (item.get("gate_criteria") or []) if str(x).strip())
        if not name or not output:
            raise OrgError(f"第 {i} 个阶段缺 name/output")
        if not names:
            raise OrgError(f"阶段 {name} 没绑角色：阶段不绑角色就会变成全连接")
        unknown = [n for n in names if n not in seen]
        if unknown:
            raise OrgError(f"阶段 {name} 引用了不存在的角色：{unknown}")
        if not gates:
            raise OrgError(f"阶段 {name} 没有阶段门：过不过谁说了算")
        stages.append(Stage(name, output, names, gates))

    plan = OrgPlan(goal=goal, roles=tuple(roles), stages=tuple(stages))
    unassigned = [r.name for r in roles if not any(r.name in s.roles for s in stages)]
    if unassigned:
        raise OrgError(f"角色没被派任何活：{unassigned}")
    if len(stages) >= 2 and plan.dispatches() >= len(roles) * len(stages):
        raise OrgError(f"派活 {plan.dispatches()} 次 = 角色 × 阶段：这是全连接，不是流程")
    if plan.total_budget > budget_cap:
        raise OrgError(f"总预算 {plan.total_budget} 超过上限 {budget_cap}")
    return plan


def plan_org(goal: str, llm, budget_cap: int = 200_000) -> OrgPlan:
    prompt = f"""你是这个组织的 Super，负责搭班子。领导下达了一个目标，你要组一支能交付的团队。

目标：{goal}

要求：
- 3–6 个角色，kind 只能取：{sorted(KINDS)}
- 每个角色的 duty 写「只负责什么」，criteria 写「怎么判它干得好」（必须可机检或可验收）
- 必须有一个独立的 verifier 角色，它不参与生产
- 每个角色给 token 预算，总和不超过 {budget_cap}
- 2–4 个阶段；每个阶段必须写明：产出物 output、参与角色 roles（真子集，不是全体）、
  阶段门 gate_criteria（这一阶段按哪些判据算过）
- 同一个角色不必出现在每个阶段；没关系就不要派

只返回一个 JSON：
{{"roles":[{{"name":"","kind":"","duty":"","criteria":"","budget":0}}],
  "stages":[{{"name":"","output":"","roles":[""],"gate_criteria":[""]}}]}}"""
    return parse_plan(goal, llm([{"role": "user", "content": prompt}]), budget_cap)