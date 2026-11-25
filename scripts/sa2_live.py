"""用真实模型跑一轮 sa2。五个自生成回路都能单独开，另外支持断点续跑。

  --auto-goal      造目标：forge/goal.decompose
  --auto-criteria  造判据：模型出「规格 + 最小合格样例」，整组四反例
  --auto-stages    造阶段判据（scope=stage），并让**交付判据与编制同源**
  --auto-org       造组织：forge/org.plan_org（被自己校验拒了带原因重试）
  --auto-tools     造工具：生成 Python 检查器，三反例准入
  --fresh          不用跨运行判据库（默认用 ~/xm-runs/sa2/registry）
  --resume PATH    从某个 state.json 续跑

退出码：0 = 环跑完且拿到真实 usage；1 = 通道/流程出错。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sa2.core import gate                         # noqa: E402
from sa2.core.gate import Declaration             # noqa: E402
from sa2.core.evidence import EvidenceBook, citation_problems     # noqa: E402
from sa2.core.judge import Criterion, Judge, replace  # noqa: E402
from sa2 import config                             # noqa: E402
from sa2 import fetch                              # noqa: E402
from sa2.core.ledger import Ledger                # noqa: E402
from sa2.core import metrics                      # noqa: E402
from sa2.core import gate_profiles                # noqa: E402
from sa2.forge import criteria as fc              # noqa: E402
from sa2.forge import dims as fd                  # noqa: E402
from sa2.forge import goal as fg                  # noqa: E402
from sa2.forge import org as fo                   # noqa: E402
from sa2.forge import tools as ft                 # noqa: E402
from sa2.forge.scribe import Scribe               # noqa: E402
from sa2.loop import size                         # noqa: E402
from sa2.loop import outer                        # noqa: E402
from sa2.loop.pdca import PDCA                    # noqa: E402
from sa2.memory import registry                   # noqa: E402
from sa2.memory.cases import CaseBook             # noqa: E402
from sa2.memory.plans import PlanStore            # noqa: E402
from sa2.memory.tools import ToolStore            # noqa: E402
from sa2.llm import complete_usage                # noqa: E402

# 宿主级的手：从 sources.json 派生，不在这里列一遍——加源只改数据
SOURCE_OF = {f"fetch:{name}": name for name in fetch.source_names()}
HAND_TOOLS = tuple(SOURCE_OF)
GOAL = "写一份「Agent 递归自我改进的最小可行实验」方案"

SPEC = """必须包含：## 一、基线
必须包含：## 二、改动
必须包含：## 三、止损
必须出现：验收方式：
"""


def runs_root() -> Path:
    return Path(os.environ.get("XM_RUNS", str(Path.home() / "xm-runs"))).expanduser()


def make_llm(usage: list[dict]):
    def llm(messages, max_tokens: int = 1200):
        text, u = complete_usage(messages, model="deepseek-flash", max_tokens=max_tokens,
                                 extra={"thinking": {"type": "disabled"}})
        usage.append(u or {})
        return text
    return llm


def _register(judge: Judge, specs) -> list[str]:
    for crit in specs:
        judge.register(crit, proposer="leader")
    return [c.name for c in specs]


def _source_query(llm, goal: str, role, source: str = "arxiv") -> str:
    """让模型写一条检索语句：题面里的缩写（如 RSI）只有它自己分得清是哪一行。"""
    cfg = fetch.config(source)
    label = str(cfg.get("label") or source)
    prefixed = str(cfg.get("query_style")) == "field-prefixed"
    where = (f'{label} 的检索语句（形如 all:"xxx"）' if prefixed
             else f"{label} 搜索（普通英文短语，不要字段前缀）")
    ask = (f"给 {where}，主题：{goal}；检索意图：{role.duty}。"
           f"**只用英文关键词**，不要出现中文；**查询要短：2–4 个词**，不要 AND/OR 列表；"
           f"只返回这一条查询，不要解释。")
    raw = llm([{"role": "user", "content": ask}], max_tokens=80) or ""
    first = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
    # 中文关键词在英文检索源上基本等于零命中：先剥成 ASCII，剥完为空就当场报，不硬查
    ascii_only = re.sub(r"[^\x20-\x7e]", " ", first).strip()
    query = re.sub(r"\s+", " ", ascii_only).strip("`").strip()
    if not query:
        raise fetch.FetchError(f"模型没给出可用的英文查询（原始：{first[:60]!r}）")
    if not prefixed:
        # 这类源不认 all:/title: 前缀，原样传会被当成关键词的一部分
        return re.sub(r"\s*[A-Za-z]+:", " ", query).strip()
    return query if ":" in query else f'all:"{query}"'


def _simplify_candidates(query: str, source: str = "arxiv") -> list[str]:
    """零命中时按词数递减给出更松的查询，而不是「简化」一次就完。

    实测：`all:"AI research automation planning"`（四词短语）零命中，同名的三词
    有好几条、两词有更多。旧版只取引号里的短语——查询本身已是短语时原样返回，
    于是「降级」降成了原地不动，整轮死在这一次取数上。
    这里返回的候选不含入参本身，也不会重复；词数不足三个时返回空表（真没法再松）。
    """
    ascii_only = re.sub(r"[^\x20-\x7e]", " ", query or "")
    quoted = re.search(r'"([^"]+)"', ascii_only)
    if quoted:
        words = re.findall(r"[A-Za-z][A-Za-z\-]+", quoted.group(1))
    else:
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]+", ascii_only)
                 if w.lower() not in {"and", "or", "not", "all", "latest", "recent"}]
    prefixed = str(fetch.config(source).get("query_style")) == "field-prefixed"

    def wrap(kept: list[str]) -> str:
        phrase = " ".join(kept)
        return f'all:"{phrase}"' if prefixed else phrase

    seen = {query.strip()}
    out: list[str] = []
    for n in range(len(words) - 1, 1, -1):
        candidate = wrap(words[:n])
        if candidate not in seen:
            seen.add(candidate)
            out.append(candidate)
    return out


def evidence_block(book: EvidenceBook) -> str:
    """把台账里已有证据列成可引用清单：编号 / 标题 / 日期 / 链接 / 摘要首句。"""
    rows = book.all()
    if not rows:
        return ""
    lines = ["## 已取回的证据（正文只能引用这些编号；没有证据的地方不许下时间判断）"]
    for ev in rows:
        body = []
        try:
            body = Path(ev.content_path).read_text(encoding="utf-8").splitlines()
        except OSError:
            pass
        title = body[0][:80] if body else ev.uri
        published = body[1][:10] if len(body) > 1 else ""
        summary = " ".join(body[3:])[:200] if len(body) > 3 else ""
        lines.append(f"[{ev.evidence_id}] {title}（{published}）{ev.uri}")
        if summary:
            lines.append(f"  摘要：{summary}")
    return "\n".join(lines)


def make_hand(llm, goal: str, book: EvidenceBook, content_dir):
    """手的实现：角色挂了几件手就把几件都跑一遍（每个源每轮只取一次）。

    为什么全跑：只取第一件手等于只用一条腿——真跑实测台账 8 条全是 arXiv，
    工程与讨论那一路从来没被走过。每个源本轮只取一次，重复派活不重复取数。
    取回的东西只做一件事：落盘、打戳、入台账；引用清单由 `evidence_block` 统一给，
    这样后面的阶段也看得到前面取回的证据。
    """
    fetched: set[str] = set()

    def hand(role, stage: str) -> str:
        tools = tuple(getattr(role, "tools", ()) or ())
        for tool in tools:
            source = SOURCE_OF.get(tool)
            if not source or source in fetched:
                continue
            fetched.add(source)
            query = _source_query(llm, goal, role, source)
            tried = [query]
            items = None
            try:
                items = fetch.search(source, query, 5)
            except fetch.FetchError as exc:
                first = exc
                for candidate in _simplify_candidates(query, source):
                    tried.append(candidate)
                    try:
                        items = fetch.search(source, candidate, 5)
                    except fetch.FetchError:
                        continue
                    query = candidate
                    break
                if items is None:
                    raise fetch.FetchError(f"查询都没取到（试过 {tried}）：{first}") from first
            fetch.record(items, book, content_dir, "leader", start=len(book.all()) + 1)
            print(f"  手：{source} 取回 {len(items)} 条（查询 {query}）", flush=True)
        return ""
    return hand


def record_tool_uses(judge, store: ToolStore) -> list[str]:
    """本轮真的跑过的检查器，在工具库记一次使用。

    为什么放在这里而不是判据内部：判据只拿到 cmd，不知道自己在库里叫什么；
    而「谁被用过」是淘汰工具的唯一依据，不记就等于资产库只涨不瘦。
    """
    used: list[str] = []
    for name in sorted(judge.executed()):
        crit = judge.get(name)
        cmd = list((crit.spec if crit else {}).get("cmd") or [])
        if len(cmd) < 2:
            continue
        entry = store.of_path(cmd[1])
        if entry is None:
            continue
        store.touch(entry["name"])
        used.append(entry["name"])
    return used


def _tool_caps(store: ToolStore) -> dict[str, str]:
    """工具名 → 能力标签。编制校验靠它判「这个角色手上是不是真有能用的手」。"""
    caps = {name: str(entry.get("capability") or "") for name, entry in store.all().items()}
    # 宿主级的手：不进工具库，但编制可以把它挂到角色上；能力标签同样来自配置
    for tool, source in SOURCE_OF.items():
        caps[tool] = str(fetch.config(source)["capability"])
    return caps


def shelve(store: ToolStore, path, crit, signature: str):
    """把生成的脚本收进工具库，并把判据的 cmd 改指向库里的稳定地址。

    不入库的检查器是「一次性的刀」：run 目录一清，注册表里那条判据的 `cmd`
    就指向一个不存在的文件——真跑里那把断刀就是这么来的。
    """
    entry = store.store(path, name=crit.name, owner="leader", signature=signature,
                        self_test={"ok": True, "cases": "生成时已跑过三反例"})
    crit = replace(crit, spec={**crit.spec,
                               "cmd": [sys.executable, entry["path"], "{target}"]})
    return entry, crit


def _org_criteria(judge):
    """造编制时传的可用判据：一条都还没登记就传 None。

    传空列表会被 parse_plan 当成“词表为空”，模型只要写了阶段门就判未登记；
    这不是模型错，是调用方把“还没有”说成了“不许有”。
    """
    names = judge.names()
    return names or None


def _hand_for(args, llm, goal, evidence_book, root):
    """只有要外部证据的档位才挂手：annotation 档没有引用义务，不该为它出网。"""
    if not args.evidence_min:
        return None
    return make_hand(llm, goal, evidence_book, root)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--goal", default=GOAL)
    ap.add_argument("--spec-file", default=None)
    ap.add_argument("--budget", type=int, default=60_000)
    ap.add_argument("--max-tokens", type=int, default=1500)
    ap.add_argument("--name", default="sa2-live")
    ap.add_argument("--auto-goal", action="store_true")
    ap.add_argument("--auto-criteria", action="store_true")
    ap.add_argument("--auto-stages", action="store_true")
    ap.add_argument("--auto-org", action="store_true")
    ap.add_argument("--auto-tools", action="store_true")
    ap.add_argument("--fresh", action="store_true", help="不用跨运行判据库")
    ap.add_argument("--resume", default=None, help="从 state.json 续跑")
    ap.add_argument("--parallel", action="store_true", help="同一阶段的角色并发派活")
    ap.add_argument("--pool", type=int, default=0,
                    help="派活经 N 个 worker 进程执行（0=进程内，默认）")
    ap.add_argument("--evidence-min", type=int, default=3,
                    help="交付至少要几条可追引用；0 = 不要求（默认 3）")
    ap.add_argument("--task-type", choices=tuple(gate_profiles.PROFILES), default="default",
                    help="任务类型决定挂哪些交付判据：default=引用≥3；annotation=只保体量；engineering=必须有测试")
    ap.add_argument("--reuse", action="store_true",
                    help="同目标已有判据就复用，不再让模型重新造")
    ap.add_argument("--require-deps", action="store_true",
                    help="开工前要求每阶段提交依赖断言单（多一次模型调用；默认关）")
    args = ap.parse_args()

    profile = gate_profiles.get(args.task_type)
    if profile.name == "engineering":
        problems = gate_profiles.check_task(profile, test_cmd=None)
        print("工程型任务走 DevLoop（sa2.loop.dev），不走 PDCA 交付：" + "；".join(problems),
              file=sys.stderr)
        return 2
    args.evidence_min = profile.min_citations

    goal = args.goal
    hand_spec = (Path(args.spec_file).expanduser().read_text(encoding="utf-8")
                 if args.spec_file else SPEC)
    spec = hand_spec

    run_dir = runs_root() / args.name / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(run_dir / "ledger.jsonl")
    evidence_book = EvidenceBook(run_dir / "evidence.jsonl")
    # 造出来的东西要有家：工具进全局库（不随 run 目录消失），判据的 cmd 指向库里
    tool_store = ToolStore()

    if args.fresh:
        judge = Judge(authority=("leader",), path=run_dir / "criteria.json",
                      history=run_dir / "criteria-history.jsonl", ledger=ledger)
        cases = CaseBook(run_dir / "cases.jsonl")
        registry_used = ""
    else:
        judge = Judge(authority=("leader",), path=registry.criteria_path(),
                      history=registry.criteria_history_path(), ledger=ledger)
        cases = CaseBook(registry.cases_path())
        registry_used = str(registry.root())

    usage: list[dict] = []
    llm = make_llm(usage)
    notes: dict[str, str] = {}

    # ① 造目标
    subtasks = None
    if args.auto_goal:
        subtasks = fg.decompose(goal, llm, fd.VOCAB)
        (run_dir / "subtasks.json").write_text(json.dumps(
            [{"name": s.name, "deliverable": s.deliverable, "dims": list(s.dims)} for s in subtasks],
            ensure_ascii=False, indent=2), encoding="utf-8")
        dims = tuple(sorted({d for s in subtasks for d in s.dims}))
    else:
        dims = ("correctness",)

    provisional = Declaration(goal=goal, dims=dims, criteria=(), budget_tokens=args.budget)

    # ①.5 先把交付样例拿出来：结构由样例定义，编制要照着它造阶段。
    # 反过来的顺序会出真错——第一节被「问题拆解」阶段占着，标题写着「最新进展」，
    # 正文却是检索计划（2026-11-20 真跑实测）。
    made = None
    sample = ""
    heads: list[str] = []
    if args.auto_stages:
        made = fc.propose_spec(goal, llm, context=("可参考的任务约束：\n" + hand_spec
                                                   if args.spec_file else ""))
        (run_dir / "proposed_spec.md").write_text(made["raw"], encoding="utf-8")
        sample = (made.get("sample") or "").strip()
        heads = ft.headings_of(sample)
        if not heads:
            print("交付样例里没有 `## ` 标题，无法切分阶段结构，先停机。", file=sys.stderr)
            (run_dir / "readings.json").write_text(json.dumps(
                {"passed": False, "reason": "交付样例无标题", "notes": notes},
                ensure_ascii=False, indent=2), encoding="utf-8")
            return 1

    # ② 先定编制（自动阶段判据需要编制才能按阶段造）
    org_error = ""
    plan = None
    decision = None
    plan_store = PlanStore(registry.plans_path())
    promotions = tuple(str(x.get("text") or "") for x in
                       outer.active(registry.promotions_path()))
    promotions = tuple(x for x in promotions if x)
    if args.auto_stages:
        if args.auto_org:
            try:
                plan = fo.plan_org(goal, llm, budget_cap=args.budget, criteria=_org_criteria(judge),
                                   require_gates=False, available_tools=_tool_caps(tool_store),
                                   headings=heads,
                                   max_tokens=int(config.get("org_max_tokens")),
                                   store=plan_store, ledger=ledger, notes=promotions)
                decision = size.SizeDecision("team", f"自生成编制：{len(plan.roles)} 角色 / "
                                                     f"{len(plan.stages)} 阶段", args.budget)
            except fo.OrgError as exc:
                org_error = str(exc)
        if plan is None:
            plan = size.single_plan(provisional, tools=HAND_TOOLS if args.evidence_min else ())
            decision = size.SizeDecision("single", "自动阶段判据需要编制：回退单人", args.budget)

    # ③a 复用：同目标已登记过判据就直接用，省掉一次模型调用
    reused = False
    if args.reuse and not args.fresh and not args.auto_stages:
        index = registry.load_goal_index()
        names = index.get(registry.fingerprint(goal)) or []
        existing = [judge.get(n) for n in names]
        if names and all(existing):
            delivery_specs = [c for c in existing if c and c.scope == "delivery"]
            if delivery_specs:
                reused = True
                notes["reused_from_registry"] = f"{len(delivery_specs)} 条判据（版本 " \
                    + "、".join(str(c.version) for c in delivery_specs) + "）"

    # ③ 造判据：一份交付样例定义结构，各阶段只负责自己的切片（切片互不重叠 → 不重复）
    stage_specs: dict[str, list] = {}
    gates: dict[str, tuple[str, ...]] = {}
    if args.auto_stages:
        delivery_specs = [fc.tested(fc.propose_sections("交付·章节", heads, dims))]
        try:
            raw, full_tool = ft.checker_from_sections(sample, run_dir / "tools",
                                                      name="delivery-sections",
                                                      allow_foreign=False)
            _, full_tool = shelve(tool_store, raw, full_tool, "<script> <target.md> → rc0/1")
            delivery_specs.append(fc.replace(full_tool, name="交付·正文下限", scope="delivery"))
        except ValueError as exc:
            notes["delivery_checker_fallback"] = str(exc)

        writers = [st for st in plan.stages if st.mode == "replace"] or list(plan.stages)
        chunks = fc.plan_slices(heads, len(writers))
        # 样例给的标题比阶段少时，把多余阶段并进最后一个拿到切片的阶段。
        # 结构由样例定义、编制服从；不让它落进「没切片 → 兜成全部交付判据」那条路。
        plan, writers, dropped = fo.collapse_uncovered(plan, writers, len(chunks))
        if dropped:
            notes["stage_merge"] = (f"{len(dropped)} 个阶段并进「{writers[-1].name}」："
                                    f"样例只给了 {len(heads)} 个标题")
            ledger.append("stage_merge", "live",
                          {"into": writers[-1].name, "dropped": list(dropped)})
        for order, (stage, chunk) in enumerate(zip(writers, chunks)):
            piece = fc.slice_sample(sample, chunk)
            specs = [fc.tested(fc.replace(
                fc.propose_sections(f"{stage.name}·章节", chunk, dims), scope="stage"))]
            try:
                raw, tool = ft.checker_from_sections(
                    piece, run_dir / "tools", name=f"stage-{stage.name}-sections",
                    # 第一个阶段从零写，越界就是错；后面的阶段是追加，上游章节合法。
                    allow_foreign=(order > 0))
                _, tool = shelve(tool_store, raw, tool, "<script> <target.md> → rc0/1")
                specs.append(fc.replace(tool, name=f"{stage.name}·正文下限", scope="stage"))
            except ValueError as exc:
                notes[f"checker_fallback:{stage.name}"] = str(exc)
            stage_specs[stage.name] = specs
            gates[stage.name] = tuple(_register(judge, specs))
            (run_dir / f"slice-{stage.name}.md").write_text(piece, encoding="utf-8")
        for stage in plan.stages:
            if stage.name not in stage_specs:
                stage_specs[stage.name] = list(delivery_specs)
                gates[stage.name] = ()
    elif not reused:
        delivery_specs = []
        if args.auto_criteria:
            made = fc.propose_spec(goal, llm, context=("可参考的任务约束：\n" + hand_spec
                                                      if args.spec_file else ""))
            (run_dir / "proposed_spec.md").write_text(made["raw"], encoding="utf-8")
            try:
                delivery_specs = fc.tested_set(fc.instantiate_all(made["spec"], dims),
                                               sample=made["sample"] or None)
                spec = made["spec"]
            except ValueError as exc:
                notes["criteria_fallback"] = f"自拟判据未过四反例，退回人工规格：{exc}"
        if not delivery_specs:
            struct_items, content_items = fc.split_spec(hand_spec)
            cands = []
            if struct_items:
                cands.append(fc.propose_sections("章节齐全", struct_items, dims))
            if content_items:
                cands.append(fc.propose_content("关键要素", content_items, dims))
            if not cands:
                print("没有可用的判据来源", file=sys.stderr)
                return 1
            delivery_specs = fc.tested_set(cands) if len(cands) > 1 else [fc.tested(cands[0])]

    for item in gate_profiles.delivery_specs(profile, book=str(evidence_book.path),
                                             volume_min=int(config.get("delivery_min_chars"))):
        delivery_specs.append(Criterion(name=item["name"], kind="callable", dims=(),
                                        self_tested=True, scope="delivery",
                                        spec=item["spec"]))
    _register(judge, delivery_specs)
    if not args.fresh and not args.auto_stages and delivery_specs:
        registry.remember_goal(goal, [c.name for c in delivery_specs])
    decl = Declaration(goal=goal, dims=dims,
                       criteria=tuple(c.name for c in delivery_specs),
                       budget_tokens=args.budget)

    if plan is None:
        if args.auto_org:
            try:
                plan = fo.plan_org(goal, llm, budget_cap=args.budget, criteria=_org_criteria(judge),
                                   available_tools=_tool_caps(tool_store),
                                   store=plan_store, ledger=ledger, notes=promotions)
                decision = size.SizeDecision("team", f"自生成编制：{len(plan.roles)} 角色 / "
                                                     f"{len(plan.stages)} 阶段", args.budget)
            except fo.OrgError as exc:
                org_error = str(exc)
        if plan is None:
            try:
                plan, decision = size.plan_for(decl)
            except ValueError as exc:
                # 决策为组队、却没有编制：回退单人并记账。不许静默把「一个人写完」
                # 记成「组织干成了」——与编制失败回退同一个口径。
                plan = size.single_plan(decl)
                decision = size.SizeDecision("single", f"回退单人：{exc}", args.budget)
                # 只有「调用方要了组织、组织没成立」才算没完成；规模启发式判组队
                # 但调用方没要组织时，单人就是被请求的形态，不记失败。
                if args.auto_org:
                    org_error = org_error or str(exc)

    # ④ 编制收口：补阶段门、最后一阶段装配、交付要求下发到写正文的人
    if args.evidence_min:
        # 挂了一只手的角色要把手挂全：只挂 arXiv 等于只用一条腿（真跑实测：台账 8 条全是 arXiv）
        plan = replace(plan, roles=tuple(
            replace(r, tools=tuple(dict.fromkeys(r.tools + HAND_TOOLS)))
            if any(t in HAND_TOOLS for t in r.tools) else r for r in plan.roles))
    if args.auto_stages:
        plan = fo.attach_stage_gates(plan, {st.name: gates.get(st.name) or tuple(decl.criteria)
                                            for st in plan.stages})
        # 切片模式：第一个阶段是 replace（它就是第一篇），后面全部 append（各自追加自己那片）。
        # 每个标题只由一个人写一次，所以装配后不会重复——这正是上一版 26 个标题的根因。
        stages = list(plan.stages)
        for i in range(1, len(stages)):
            stages[i] = replace(stages[i], mode="append")
        plan = replace(plan, stages=tuple(stages))

    # ⑤ 造工具：给第一个阶段挂一个生成的检查器
    tool_error = ""
    tool_path = ""
    if args.auto_tools and plan.stages:
        first_specs = stage_specs.get(plan.stages[0].name) or delivery_specs
        required = [h for c in first_specs if c.kind == "sections"
                    for h in (c.spec.get("required") or [])]
        try:
            tool_path_obj, tool_crit = ft.generate_checker(
                goal, required, llm, run_dir / "tools", name="stage1_checker")
            entry, tool_crit = shelve(tool_store, tool_path_obj, tool_crit,
                                      "<script> <target.md> → rc0/1")
            judge.register(tool_crit, proposer="leader")
            first = plan.stages[0]
            plan = fo.attach_stage_gates(plan, {
                **{st.name: st.gate_criteria for st in plan.stages},
                first.name: tuple(first.gate_criteria) + (tool_crit.name,),
            })
            tool_path = entry["path"]
        except (ValueError, OSError) as exc:
            tool_error = str(exc)

    # ⑥ 跑环（带断点）
    state_path = Path(args.resume) if args.resume else run_dir / "state.json"
    # 切片模式下不能再把整份任务规格塞给执笔角色：它一看见六节就会把整篇写出来，
    # 阶段门随即判它越界。每个阶段的「验收要求」已经写明它只该写哪几节。
    scribe = Scribe(llm, spec=("" if args.auto_stages else spec), max_tokens=args.max_tokens,
                    notes=promotions)
    produce = scribe
    pool = None
    if args.pool:
        from sa2.loop.pool_producer import PoolProducer
        from sa2.loop.workers import WorkerPool
        pool = WorkerPool(run_dir / "pool", ledger, workers=args.pool, ttl=5.0).start()
        produce = PoolProducer(pool, scribe.prompt, max_tokens=scribe.max_tokens,
                               timeout=600, usage=usage)
    dep_notes = {}
    if args.require_deps:
        from sa2.core import deps as core_deps
        from sa2.forge import deps as forge_deps
        try:
            dep_notes = forge_deps.propose(goal, plan, llm, criteria=decl.criteria)
        except core_deps.DepError as exc:
            print(f"依赖断言单不合格：{exc}", file=sys.stderr)
            return 2
        for stage_name, dep_note in dep_notes.items():
            ledger.append("dependency_note", "forge",
                          {"stage": stage_name, "items": len(dep_note.items),
                           "gaps": list(dep_note.gaps)})

    pdca = PDCA(judge, ledger, plan, produce, fd.VOCAB, usage=usage,
                max_stage_attempts=2, cases=cases, parallel=args.parallel,
                state_path=state_path, resume=bool(args.resume),
                artifact_dir=run_dir / "stages",
                hand=_hand_for(args, llm, goal, evidence_book,
                                run_dir / "evidence-content"),
                context=lambda: evidence_block(evidence_book),
                lesson_path=registry.lessons_path(),
                require_deps=args.require_deps, dep_notes=dep_notes)
    try:
        report = pdca.run(decl, evidence=[])
    finally:
        if pool is not None:
            pool.stop()

    tool_uses = record_tool_uses(judge, tool_store)
    artifact = run_dir / "deliverable.md"
    artifact.write_text(report.get("text") or "", encoding="utf-8")
    evidence = [f"{artifact}:1", f"dispatches={report['dispatches']}"]
    evidence_problems = gate.check_evidence(evidence)
    # 编制失败后回退单人：可以出稿，但不许记绿——否则「组织干成了一件事」和
    # 「一个人写完一篇」在读数里长得一模一样（2026-11-20 实测就是这么绿的）。
    org_fallback = bool(org_error)
    if org_fallback:
        evidence_problems = evidence_problems + [
            f"编制未成立：{org_error}——回退单人出稿，不算完成"]
    delivery_ok = report["passed"] and not evidence_problems

    readings = {
        "goal": goal,
        "scale": decision.scale if decision else "",
        "scale_reason": decision.reason if decision else "",
        "passed": delivery_ok,
        "delivery_passed": report["passed"],
        "reason": report["reason"],
        "problems": report["problems"],
        "evidence_problems": evidence_problems,
        "dispatches": report["dispatches"],
        "rejects": len(report["rejects"]),
        "redone": report["redone"],
        "chars": report["chars"],
        "budget": report["budget"],
        "exact_usage": bool((report["budget"] or {}).get("exact")),
        "criteria": judge.names(),
        "delivery_criteria": [c.name for c in delivery_specs],
        "reused": reused,
        "subtasks": [s.name for s in subtasks] if subtasks else [],
        "org_generated": bool(args.auto_org and not org_error),
        "org_fallback": org_fallback,
        "org_error": org_error,
        "tool": tool_path,
        "tool_uses": tool_uses,
        "evidence_count": len(evidence_book.all()),
        "citation_problems": citation_problems(report.get("text") or "", evidence_book),
        "tool_error": tool_error,
        "notes": notes,
        "registry": registry_used,
        "plan": {"roles": [r.name for r in plan.roles],
                 "stages": [st.name for st in plan.stages],
                 "modes": [st.mode for st in plan.stages],
                 "gates": {st.name: list(st.gate_criteria) for st in plan.stages}},
        "ledger": str(ledger.path),
        "run_dir": str(run_dir),
    }
    readings["metrics"] = metrics.compute(ledger.read(), readings)
    (run_dir / "readings.json").write_text(json.dumps(readings, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    ok = bool(readings["exact_usage"]) and report["dispatches"] >= 1

    if args.json:
        print(json.dumps({**readings, "ok": ok}, ensure_ascii=False, indent=2))
    else:
        print("sa 2.0 真模型跑一轮")
        print(f"  目标：{goal}")
        if subtasks:
            print(f"  自造目标：{len(subtasks)} 个子任务")
        print(f"  交付判据：{'、'.join(c.name for c in delivery_specs)}（"
              f"{'与编制同源' if args.auto_stages else '来自规格'}）")
        if args.auto_stages:
            for st in plan.stages:
                print(f"      阶段「{st.name}」[{st.mode}] 门：{'、'.join(st.gate_criteria)}")
        if args.auto_org:
            print(f"  自造编制：{'成功' if not org_error else '失败→回退'} "
                  f"（{len(plan.roles)} 角色 / {len(plan.stages)} 阶段）")
            if org_error:
                print(f"      拒收原因：{org_error}")
        if args.auto_tools:
            print(f"  自造工具：{'成功 ' + tool_path if tool_path else '失败：' + tool_error}")
        for key, note in notes.items():
            print(f"  注：{key} — {note}")
        print(f"  派活 {report['dispatches']} 次，拒绝 {len(report['rejects'])} 次，"
              f"重做 {report['redone'] or '无'}")
        b = report["budget"] or {}
        print(f"  预算：{b.get('spent')}/{b.get('tokens')} tokens "
              f"（{'真实 usage' if b.get('exact') else '字符估算'}），调用 {b.get('calls')} 次")
        print(f"  证据门：{'过' if not evidence_problems else evidence_problems}")
        print(f"  结果：passed={delivery_ok}" + (f"，{report['reason']}" if report["reason"] else ""))
        for problem in report["problems"]:
            print(f"      红：{problem}")
        print(f"  账本：{readings['ledger']}")
        print(f"  读数：{run_dir / 'readings.json'}")
        print(f"结论：{'跑通' if ok else '未跑通'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())