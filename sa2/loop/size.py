"""编制规模决策：这次到底用几个人。

1.0 有过一个结论——「先单人，判不过再组队」——但那是一次性实测，没被写成决策，
后来就演成 `deliver.py` 里一段 if/else。2.0 把它放回该在的位置：**进环之前的第一问**。

规则按顺序，第一条命中即返回：
1. 预算低于单人下限 → 单人。组队跑不完预算，等于花更多钱买更少完成度。
2. 声明维度 ≥ 2 或判据 ≥ 3 → 组队。多域、多判据需要分工与独立复核。
3. 其余 → 单人。默认单人不是保守，是 1.0 的实测：组织臂多花 2 次调用、2645 个
   prompt token，只换来更少轮数。

这条决策必须在 L2（环）而不是 L1（forge）：让生成方决定自己要被验收多严，
等于把红线拆了。
"""
from __future__ import annotations

from dataclasses import dataclass

from .. import config
from ..core.gate import Declaration
from ..forge.org import OrgPlan, Role, Stage


@dataclass(frozen=True)
class SizeDecision:
    scale: str                      # "single" | "team"
    reason: str
    budget_tokens: int


def decide(decl: Declaration) -> SizeDecision:
    floor = config.get("single_floor")
    if decl.budget_tokens < floor:
        return SizeDecision("single", f"预算 {decl.budget_tokens} < 单人下限 {floor}", decl.budget_tokens)
    if len(decl.dims) >= config.get("team_dims"):
        return SizeDecision("team", f"声明了 {len(decl.dims)} 个维度，需要分工与独立复核", decl.budget_tokens)
    if len(decl.criteria) >= config.get("team_criteria"):
        return SizeDecision("team", f"声明了 {len(decl.criteria)} 条判据，需要独立验证方", decl.budget_tokens)
    return SizeDecision("single", "单一维度、判据不超过 2 条：先单人", decl.budget_tokens)


def single_plan(decl: Declaration, tools=()) -> OrgPlan:
    """单人编制：一个执行角色、一个阶段。

    它不走 `org.parse_plan`（那套校验是给模型生成的编制用的，要求 ≥3 角色），
    但仍然是同一个 OrgPlan 类型——环不需要知道规模。
    """
    role = Role(name="执行", kind="executor", duty="按声明写交付物",
                tools=tuple(tools),
                criteria="；".join(decl.criteria), budget=max(1, decl.budget_tokens))
    stage = Stage(name="交付", output=decl.goal, roles=("执行",), gate_criteria=decl.criteria)
    return OrgPlan(goal=decl.goal, roles=(role,), stages=(stage,))


def plan_for(decl: Declaration, team_plan: OrgPlan | None = None) -> tuple[OrgPlan, SizeDecision]:
    decision = decide(decl)
    if decision.scale == "team":
        if team_plan is None:
            raise ValueError("决策为组队，但没有给出编制")
        return team_plan, decision
    return single_plan(decl), decision