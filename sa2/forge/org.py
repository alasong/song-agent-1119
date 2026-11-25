"""编制与流程：阶段自己绑角色，不允许「每个角色在每个阶段都干一遍」。

sa 1.0 的调度器是 `for stage: for role:` 两层循环，6 角色 × 7 阶段 = 42 次派活，
不管这个角色和这个阶段有没有关系。2.0 把「谁在哪个阶段干活」变成数据：
Stage.roles 非空且是全体角色的**真子集**（至少有一处不是全连接），门直接判这一条。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

from .. import config
from ..knowledge import load

KINDS = set(load("vocab")["kinds"])
# 下界是代码红线（少于这些就不叫组织），上界是资源项，从数据读。
ROLE_MIN, STAGE_MIN = 3, 2
# 能「去看外面东西」的工具能力；researcher 手上至少得有一件这样的。
FETCH_CAPABILITIES = set(load("vocab")["hand_capabilities"])


class OrgError(RuntimeError):
    """编制不合格。"""


@dataclass(frozen=True)
class Role:
    name: str
    kind: str
    duty: str
    criteria: str
    budget: int
    # 手上有什么：工具库里已登记的工具名。researcher 必须带——没有工具就只能凭记忆，
    # 那不叫采集（rsi 那轮 21 条全在训练截止之前，就是这个原因）。
    tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class Stage:
    name: str
    output: str
    roles: tuple[str, ...]
    gate_criteria: tuple[str, ...]
    # replace：本阶段产出就是全文（重写）
    # append ：上游全文 + 本阶段产出（装配/定稿）
    # 没有这个区分，最后一道「定稿」阶段会把前面的正文整个丢掉。
    mode: str = "replace"


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


def parse_plan(goal: str, raw: str, budget_cap: int = 200_000,
               available_criteria=None, require_gates: bool = True,
               available_tools=None, headings=()) -> OrgPlan:
    match = re.search(r"\{.*\}", raw or "", re.S)
    if not match:
        raise OrgError("模型输出里没有 JSON")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise OrgError(f"JSON 解析失败：{exc}") from exc

    roles_raw = data.get("roles") or []
    if len(roles_raw) < ROLE_MIN:
        raise OrgError(f"角色只有 {len(roles_raw)} 个，至少 {ROLE_MIN} 个")
    roles: list[Role] = []
    seen: set[str] = set()
    for i, item in enumerate(roles_raw, 1):
        name = str(item.get("name", "")).strip()
        kind = str(item.get("kind", "")).strip()
        duty = str(item.get("duty", "")).strip()
        criteria = str(item.get("criteria", "")).strip()
        budget = int(item.get("budget", 0) or 0)
        # 模型会照抄提示里的显示格式「名字[能力]」，这里把它剥回名字再校验
        tools = tuple(re.sub(r"\s*\[[^\]]*\]\s*$", "", str(x).strip())
                      for x in (item.get("tools") or []) if str(x).strip())
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
        caps = {} if available_tools is None else dict(available_tools)
        if available_tools is not None and tools:
            unknown_tools = [t for t in tools if t not in caps]
            if unknown_tools:
                raise OrgError(f"角色 {name} 引用了工具库里没有的工具：{unknown_tools}"
                               f"（可选：{sorted(caps)}）")
        if kind == "researcher":
            # 「有工具」不够，得是**能去看外面**的工具：挂一个章节检查器也过，那是假的手。
            usable = [t for t in tools if str(caps.get(t, "")) in FETCH_CAPABILITIES]
            if not (tools and (usable or available_tools is None)):
                raise OrgError(
                    f"角色 {name} 是 researcher，却没有能去看外面的手"
                    f"（它挂的：{ {t: caps.get(t) for t in tools} or '没挂任何工具' }；"
                    f"库里能用的：{sorted(t for t in caps if caps[t] in FETCH_CAPABILITIES) or '一件也没有'}）。"
                    f"没有手就只能凭记忆写清单——实测那轮 21 条最新只到训练截止前。"
                    f"要么先造一件 fetch 类工具入库，要么把 kind 改成 expert（只做推理，不需要手）。")
        seen.add(name)
        roles.append(Role(name, kind, duty, criteria, budget, tools))

    if not any(r.kind == "verifier" for r in roles):
        raise OrgError("没有独立验证角色（kind=verifier）——不允许自己给自己发毕业证")

    stages_raw = data.get("stages") or data.get("process") or []
    if len(stages_raw) < STAGE_MIN:
        raise OrgError(f"阶段只有 {len(stages_raw)} 个，至少 {STAGE_MIN} 个")
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
        if not gates and require_gates:
            raise OrgError(f"阶段 {name} 没有阶段门：过不过谁说了算")
        mode = str(item.get("mode", "replace")).strip()
        if mode not in ("replace", "append"):
            raise OrgError(f"阶段 {name} 的 mode={mode!r} 只能是 replace / append")
        stages.append(Stage(name, output, names, gates, mode))

    if available_criteria is not None:
        known = set(available_criteria)
        for stage in stages:
            unknown = [g for g in stage.gate_criteria if g not in known]
            if unknown:
                raise OrgError(f"阶段 {stage.name} 的阶段门引用了未登记的判据：{unknown}"
                               f"（可选：{sorted(known)}）")

    if headings and len(stages) != len(headings):
        raise OrgError(f"阶段有 {len(stages)} 个，而交付只有 {len(headings)} 个章节："
                       f"请正好造 {len(headings)} 个阶段，一个阶段写一个章节 {list(headings)}")
    plan = OrgPlan(goal=goal, roles=tuple(roles), stages=tuple(stages))
    unassigned = [r.name for r in roles if not any(r.name in s.roles for s in stages)]
    if unassigned:
        raise OrgError(f"角色没被派任何活：{unassigned}")
    if len(stages) >= 2 and plan.dispatches() >= len(roles) * len(stages):
        raise OrgError(f"派活 {plan.dispatches()} 次 = 角色 × 阶段：这是全连接，不是流程")
    if plan.total_budget > budget_cap:
        raise OrgError(f"总预算 {plan.total_budget} 超过上限 {budget_cap}")
    return plan


def _org_prompt(goal: str, budget_cap: int, criteria, tools_text: str = "",
                headings=(), notes=()) -> str:
    shape = ""
    if headings:
        shape = (f"\n- **交付结构已经定了**，有且只有 {len(headings)} 个章节：{list(headings)}\n"
                 f"  请造 {len(headings)} 个阶段，第 i 个阶段负责第 i 个章节；"
                 f"阶段名要能看出它在写哪一节（别用「问题拆解」占了「最新进展」那一节）。")
    note_block = ""
    if notes:
        note_block = ("\n- **外环采纳的经验（务必照做）**：\n"
                      + "\n".join(f"  - {n}" for n in notes))
    return f"""你是这个组织的 Super，负责搭班子。领导下达了一个目标，你要组一支能交付的团队。

目标：{goal}

要求：
- {ROLE_MIN}–{config.get('org_roles_max')} 个角色，kind 只能取：{sorted(KINDS)}
- 每个角色的 duty 写「只负责什么」，criteria 写「怎么判它干得好」（必须可机检或可验收）
- 必须有一个独立的 verifier 角色，它不参与生产
- 每个角色给 token 预算，总和不超过 {budget_cap}
- 角色可以带 tools（工具名列表），只能从下面这些**工具库里已登记**的选：
  {tools_text or "（工具库是空的，这一轮谁都不许带 tools）"}
- kind=researcher 的角色手上必须有一件**能去看外面**的工具（能力标 fetch/search/crawl/api/database）：
  没有手就只能凭记忆写清单。这一轮想不出谁有这种工具，就别设 researcher——用 expert，
  它只做推理、不需要手。
- {STAGE_MIN}–{config.get('org_stages_max')} 个阶段；每个阶段必须写明：产出物 output、参与角色 roles（真子集，不是全体）、
  阶段门 gate_criteria（这一阶段按哪些判据算过）
- gate_criteria 只能从下面这些**已登记**判据里选，一个都不许自造（自造等于自己发毕业证）：
  {list(criteria) or "（没有可用的判据，先让领导登记）"}
- **每个角色至少要在某一个阶段的 roles 里出现一次**，没派活就别设这个角色{shape}{note_block}

只返回一个 JSON：
{{"roles":[{{"name":"","kind":"","duty":"","criteria":"","budget":0,"tools":[]}}],
  "stages":[{{"name":"","output":"","roles":[""],"gate_criteria":[""]}}]}}"""


def _plan_to_dict(plan: OrgPlan) -> dict:
    return {
        "goal": plan.goal,
        "roles": [{"name": r.name, "kind": r.kind, "duty": r.duty,
                   "criteria": r.criteria, "budget": r.budget,
                   "tools": list(r.tools)} for r in plan.roles],
        "stages": [{"name": s.name, "output": s.output, "roles": list(s.roles),
                    "gate_criteria": list(s.gate_criteria), "mode": s.mode}
                   for s in plan.stages],
    }


def _plan_from_dict(data: dict) -> OrgPlan:
    roles = tuple(
        Role(name=str(r["name"]), kind=str(r["kind"]), duty=str(r.get("duty") or ""),
             criteria=str(r.get("criteria") or ""), budget=int(r.get("budget") or 0),
             tools=tuple(r.get("tools") or ()))
        for r in data.get("roles") or ())
    stages = tuple(
        Stage(name=str(s["name"]), output=str(s.get("output") or ""),
              roles=tuple(s.get("roles") or ()),
              gate_criteria=tuple(s.get("gate_criteria") or ()),
              mode=str(s.get("mode") or "replace"))
        for s in data.get("stages") or ())
    if not roles or not stages:
        raise OrgError("编制库里这一条是空的")
    return OrgPlan(goal=str(data.get("goal") or ""), roles=roles, stages=stages)


def plan_org(goal: str, llm, budget_cap: int = 200_000, criteria=(), attempts: int = 2,
             require_gates: bool = True, available_tools=None,
             headings=(), max_tokens: int | None = None,
             store=None, ledger=None, notes=()) -> OrgPlan:
    """生成编制。被自己的校验拒了就带着拒收原因重来一次——
    不给原因的重试等于让它重复同一个错，这一点在环里和在这里是同一个道理。

    store 给定时先查复合键：命中就不再问模型，账本记 `plan_reused`。
    """
    key = store.key(goal, budget_cap, criteria, available_tools, headings, notes) if store else ""
    if store:
        cached = store.get(key)
        if cached:
            plan = _plan_from_dict(cached)
            store.mark_reuse(key)
            if ledger is not None:
                ledger.append("plan_reused", "org",
                              {"key": key, "goal": goal,
                               "roles": len(plan.roles), "stages": len(plan.stages)})
            return plan
    tools_text = "、".join(f"{n}（能力：{c or '未知'}）"
                          for n, c in (available_tools or {}).items())
    prompt = _org_prompt(goal, budget_cap, criteria, tools_text, headings, notes)
    feedback = ""
    last: OrgError | None = None
    for _ in range(max(1, attempts)):
        ask = prompt if not feedback else (
            f"{prompt}\n\n上次这份编制被拒，原因：{feedback}\n请修正后重新输出完整 JSON。")
        try:
            # 编制的输出是一整份 JSON：5 角色 3 阶段就要两千多字，贴着通道默认上限
            # （2400 tokens）就会随机被截断，然后整支班子搭不起来。这里单独给额度。
            ask_kwargs = {"max_tokens": max_tokens} if max_tokens else {}
            plan = parse_plan(goal, llm([{"role": "user", "content": ask}], **ask_kwargs),
                              budget_cap,
                              available_criteria=criteria, require_gates=require_gates,
                              available_tools=available_tools, headings=headings)
            if store:
                store.put(key, _plan_to_dict(plan))
            return plan
        except OrgError as exc:
            last = exc
            feedback = str(exc)
    raise last if last else OrgError("编制生成失败")


def collapse_uncovered(plan: OrgPlan, writers, covered: int):
    """切片只够 `covered` 份时，把多出来的写手阶段并进最后一个拿到切片的阶段。

    为什么不干脆让它跑：它没有自己的章节，只能被兜成「整篇交付」当门，append 模式下两次
    必红（2026-11-20 真跑：4 阶段 / 3 标题，passed=False）。**结构由样例定义，编制服从**，
    多出来的阶段不是多余的人，是他们并入前一阶段一起写那一片。

    返回 (新编制, 截断后的写手列表, 被并掉的阶段名)。
    """
    writers = list(writers)
    if not writers or covered <= 0 or covered >= len(writers):
        return plan, writers, ()
    keep = writers[covered - 1]
    dropped = writers[covered:]
    drop_names = {st.name for st in dropped}
    merged_roles = tuple(dict.fromkeys(
        keep.roles + tuple(r for st in dropped for r in st.roles)))
    stages = tuple(replace(st, roles=merged_roles) if st.name == keep.name else st
                   for st in plan.stages if st.name not in drop_names)
    surviving = {name for st in stages for name in st.roles}
    lost = [r.name for r in plan.roles if r.name not in surviving]
    if lost:
        raise OrgError(f"合并后会丢掉角色：{lost}")
    return replace(plan, stages=stages), writers[:covered], tuple(sorted(drop_names))


def attach_stage_gates(plan: OrgPlan, gates: dict[str, tuple[str, ...]]) -> OrgPlan:
    """把每个阶段的阶段门换成它自己的判据。

    为什么必须换：如果所有阶段都拿「整篇交付」的判据当门，中间阶段就被迫写成完整文档，
    分层等于没有。阶段判据是 stage 作用域的，交付判据是 delivery 作用域的。
    """
    missing = [st.name for st in plan.stages if st.name not in gates]
    if missing:
        raise OrgError(f"这些阶段没有给阶段门：{missing}")
    stages = tuple(replace(st, gate_criteria=tuple(gates[st.name])) for st in plan.stages)
    return replace(plan, stages=stages)


def close_with_delivery(plan: OrgPlan, criteria) -> OrgPlan:
    """最后一道阶段门必须包含交付门。

    否则会出现一种很难查的红：中间阶段全过、最后阶段按自己的判据也过了，
    但整篇不满足交付判据——因为那段要求从来没进过任何人的提示词。
    交付要求必须在最后一个阶段的可见范围里，才可能被写出来。
    """
    criteria = tuple(str(c) for c in criteria)
    if not plan.stages:
        raise OrgError("编制没有阶段")
    stages = list(plan.stages)
    targets = [len(stages) - 1]
    # 装配阶段只是把上游接起来；真正写正文的是它前面最后一个 replace 阶段。
    # 交付要求必须同时进那个阶段的可见范围，否则写正文的人从头到尾都不知道交付结构。
    if stages[-1].mode == "append":
        writers = [i for i, st in enumerate(stages) if st.mode == "replace"]
        if writers:
            targets.append(writers[-1])
    for i in targets:
        merged = tuple(dict.fromkeys(tuple(stages[i].gate_criteria) + criteria))
        stages[i] = replace(stages[i], gate_criteria=merged)
    return replace(plan, stages=tuple(stages))
