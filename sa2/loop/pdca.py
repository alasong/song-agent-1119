"""L2：PDCA 环。声明 → 前置门 → 逐阶段（产出 → 阶段门）→ 交付门 → 证据门。

与 sa 1.0 的实质差别只有一条，但它是全部价值所在：
**被拒时只重做这一阶段**，不是整篇重来。1.0 的返工是「把整篇文档再写一遍」，
所以一次拒绝的代价是整篇的 token；这里拒绝的代价只有这一阶段的产出。

阶段门与交付门是两层，不许合并：
- 阶段门判「这一段能不能进下一段」（结构、要素齐不齐）
- 交付门判「整篇能不能交」（声明里的全部判据）
合并的后果是——中间某一格不合格要到最后一刻才被发现，等于又回到 1.0。
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..core import gate
from ..core.budget import Budget
from ..core.gate import Declaration
from ..core.judge import Judge
from ..core.ledger import Ledger
from ..forge.org import OrgPlan
from ..memory import lessons as lessonbook
from ..memory.cases import CaseBook


class PDCA:
    def __init__(self, judge: Judge, ledger: Ledger, plan: OrgPlan, produce: "callable",
                 vocab, usage: list[dict] | None = None,
                 max_stage_attempts: int = 2, cases: CaseBook | None = None,
                 state_path: str | Path | None = None, resume: bool = False,
                 artifact_dir: str | Path | None = None, parallel: bool = False,
                 hand=None, context=None, lesson_path: str | Path | None = None,
                 supervisor=None):
        """produce(role, stage, upstream, attempt, feedback) -> str。

        feedback 是上一轮这一阶段被拒的原因；第一次尝试为空串。
        带上它的理由很实际：sa 1.0 的整篇重写虽然也带反馈，但代价是整篇；
        2.0 只重做一格，如果这一格不知道上次错在哪，等于把省下的钱又亏回去。
        """
        self.hand = hand
        self.context = context    # 每次派活都带上「截至目前已取回的证据」，后面的阶段才引用得到          # 角色手上有工具时，派活前先真的取一次（结果进上游与证据台账）
        self.judge = judge
        self.ledger = ledger
        self.plan = plan
        self.produce = produce
        self.vocab = vocab
        self.usage = usage
        self.max_stage_attempts = max_stage_attempts
        self.cases = cases
        # 经验库：按「这次失败属于哪一类」取对策。取到的不只是提示，还要记命中，
        # 否则「哪条经验有用」永远只能靠感觉——经验库又会变成写不读的死功能。
        self.lesson_path = Path(lesson_path) if lesson_path else None
        self._injected: dict[str, list[str]] = {}
        self.state_path = Path(state_path) if state_path else None
        self.resume = resume
        self.artifact_dir = Path(artifact_dir) if artifact_dir else None
        self.parallel = parallel
        self.supervisor = supervisor

    def run(self, decl: Declaration, seed: str = "", evidence=None) -> dict:
        # ① 前置门：任何一条不成立，一次调用都不发
        pre = gate.pre_flight(decl, self.judge, self.vocab)
        if not pre["ok"]:
            self.ledger.append("preflight_reject", "gate", {"problems": pre["problems"]})
            return self._report(False, "前置门未过", problems=pre["problems"])

        # 编制的阶段门也必须落在已登记判据里，否则一跑就是注定红的空转
        known = set(self.judge.names())
        dangling = [f"{st.name}:{g}" for st in self.plan.stages
                    for g in st.gate_criteria if g not in known]
        if dangling:
            problem = f"编制的阶段门引用了未登记的判据：{dangling}"
            self.ledger.append("preflight_reject", "gate", {"problems": [problem]})
            return self._report(False, "前置门未过", problems=[problem])

        budget = Budget(decl.budget_tokens, usage=self.usage if self.usage is not None else [])
        text = seed
        ran: set[str] = set()
        rejects: list[dict] = []
        redone: list[str] = []
        start = 0

        # 断点续跑：多阶段编制一次十几二十次调用，中途挂掉全丢的代价太高
        if self.resume and self.state_path and self.state_path.exists():
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            start = int(state.get("stage_index") or 0)
            text = state.get("text") or text
            ran = set(state.get("ran") or [])
            budget.spent_seed = int(state.get("spent") or 0)
            self.ledger.append("resume", "loop", {"from_stage": start, "spent": budget.spent_seed})

        counters = {"dispatches": 0}
        before: dict[str, str] = {}      # 阶段成功时的上游快照：交付门回退要从这里重做
        for index, stage in enumerate(self.plan.stages[start:], start=start):
            # 判据对生成方必须是可见的：看不见要求，只能猜，猜不中就红两次。
            # 可见 ≠ 可控：生成方知道要求是什么，但改不了判据本身。
            requirements = self._requirements(stage)
            feedback = ""                      # 上一轮被拒的原因：重做必须带着它，否则是盲重做
            for attempt in range(1, self.max_stage_attempts + 1):
                assembled = self._produce_stage(stage, text, attempt, feedback,
                                                requirements, budget, counters)
                if assembled is None:
                    self.ledger.append("budget_stop", "loop", budget.snapshot())
                    return self._report(False, budget.why(f"{stage.name} 之前"),
                                        redone=redone, rejects=rejects,
                                        dispatches=counters["dispatches"], budget=budget)
                candidate = self._assemble(stage, text, assembled)
                problems = self._stage_problems(stage, candidate, ran)

                if not problems:
                    before[stage.name] = text
                    text = candidate
                    self.ledger.append("stage_ok", stage.name, {"attempt": attempt})
                    used = self._injected.pop(stage.name, None)
                    if used and self.lesson_path is not None:
                        lessonbook.bump(self.lesson_path, used, "ok")
                    if self.artifact_dir:
                        self._write_artifact(self.artifact_dir, f"{index}-{stage.name}.md", candidate)
                    if self.state_path:
                        self.state_path.write_text(json.dumps({
                            "stage_index": index + 1, "text": text,
                            "ran": sorted(ran), "spent": budget.spent,
                        }, ensure_ascii=False), encoding="utf-8")
                    break

                raw = "；".join(problems)
                feedback = self._feedback(raw, problems)
                rejects.append({"stage": stage.name, "attempt": attempt,
                                "problems": problems, "feedback": feedback})
                # 被拒的产出也落盘：只留一句原因，事后连「是哪一条判据误判」都查不出来
                if self.artifact_dir:
                    self._write_artifact(self.artifact_dir / "rejected",
                                         f"{index}-{stage.name}-try{attempt}.md", candidate)
                self.ledger.append("reject", "stage_gate",
                                   {"stage": stage.name, "attempt": attempt, "problems": problems})
                if attempt == self.max_stage_attempts:
                    if self.cases is not None:
                        self.cases.add(stage.name, raw, "按拒收原因逐条修后重做该阶段")
                    return self._report(
                        False, f"阶段「{stage.name}」连续 {attempt} 次未过阶段门",
                        redone=redone, rejects=rejects,
                        dispatches=counters["dispatches"], budget=budget)
                # 只重做这一阶段：下游还没跑，上游不用重来
                redone.append(stage.name)
                self.ledger.append("redo_stage", stage.name, {"attempt": attempt})

        # ② 交付门：声明里的全部判据
        delivery = self._delivery_problems(decl, text, ran)

        # ②b 回退：交付门红了但前面各阶段都是绿的，说明问题出在最后一阶段没吃透
        # 交付要求。回到那一阶段、带着交付门的拒收原因重做一次（只一次）。
        # 为什么不整篇重来：那正是 1.0 的代价；为什么只做最后一阶段：前面的已经过门，
        # 动它们等于把已经判过的东西再赌一次。
        if delivery and self.plan.stages:
            if self.lesson_path is not None:
                # 交付门被拒也是一次失败，也得进经验库：只写阶段门拒收的话，
                # 「编排出问题」这类教训永远不会被记下来（真跑 0 阶段拒收 → 库一直空）。
                lessonbook.add(self.lesson_path, text="；".join(delivery)[:400],
                               when={"failure_kind": lessonbook.classify(delivery)},
                               fix="按交付门拒收原因修最后一阶段，而不是整篇重写",
                               origin="delivery_gate")
            stage = self.plan.stages[-1]
            if stage.name in before:
                feedback = self._feedback("；".join(delivery), delivery)
                assembled = self._produce_stage(stage, before[stage.name], 2, feedback,
                                                self._requirements(stage), budget, counters)
                if assembled is not None:
                    candidate = self._assemble(stage, before[stage.name], assembled)
                    retry = self._delivery_problems(decl, candidate, ran)
                    self.ledger.append("redo_from_delivery", stage.name,
                                       {"problems": delivery, "after": retry})
                    redone.append(stage.name)
                    if not retry:
                        text, delivery = candidate, []
                        if self.artifact_dir:
                            self._write_artifact(self.artifact_dir,
                                                 f"{len(self.plan.stages) - 1}-{stage.name}.md",
                                                 candidate)

        # ③ 证据门 + ④ 不静默失败
        evidence = list(evidence or ())
        evidence_problems = gate.check_evidence(evidence)
        silent = gate.check_silent_failure(self.judge, decl, ran)
        problems = delivery + evidence_problems + silent
        passed = not problems
        self.ledger.append("delivery", "gate",
                           {"passed": passed, "problems": problems, "chars": len(text)})
        return self._report(passed, "" if passed else "交付门/证据门未过",
                            redone=redone, rejects=rejects,
                            dispatches=counters["dispatches"],
                            budget=budget, problems=problems, evidence=evidence,
                            chars=len(text), ran=sorted(ran), text=text)

    def _dispatch(self, role, stage, upstream, attempt, feedback, requirements, partial=""):
        """派活入口：有 supervisor 就经它（死亡→接管），没有就走裸 produce。"""
        if self.supervisor is not None:
            return self.supervisor.dispatch(role, stage, upstream, attempt, feedback,
                                            requirements, partial=partial)
        return self.produce(role, stage, upstream, attempt, feedback, requirements)

    def _produce_stage(self, stage, upstream: str, attempt: int, feedback: str,
                       requirements: str, budget: Budget, counters: dict) -> str | None:
        """跑一遍这个阶段的角色，装配并裁剪成候选。预算耗尽返回 None。

        阶段循环与「交付门回退」共用这一段：回退必须走同一条派活路径，
        否则回退出来的东西与正常产出的形状会不一样。
        """
        self._stage_in_flight = stage.name
        writer = self._writer(stage)
        roles = [self.plan.role(name) for name in stage.roles]
        parts: list[str] = []
        # 同一阶段的角色互不依赖（都只读上游、互不写对方），这是唯一不会破坏
        # 交接顺序的并发粒度；预算仍串行入账，避免多线程计费打架。
        if self.parallel and len(roles) > 1:
            if budget.exhausted():
                return None
            materials = {role.name: self._run_hand(role, stage.name) for role in roles}
            with ThreadPoolExecutor(max_workers=len(roles)) as pool:
                futures = [(role, pool.submit(
                    self._dispatch, role, stage.name,
                    self._with_material(upstream, materials[role.name] + self._context()),
                    attempt, feedback,
                    requirements if role.name == writer else self._supplement(writer)))
                           for role in roles]
                for role, future in futures:
                    out = future.result()
                    budget.note(out)
                    counters["dispatches"] += 1
                    self.ledger.append("dispatch", role.name,
                                       {"stage": stage.name, "attempt": attempt,
                                        "chars": len(out), "parallel": True})
                    parts.append(out)
        else:
            for role in roles:
                if budget.exhausted():
                    return None
                material = self._run_hand(role, stage.name) + self._context()
                out = self._dispatch(role, stage.name,
                                     self._with_material(upstream, material),
                                     attempt, feedback,
                                     requirements if role.name == writer else self._supplement(writer),
                                     partial="".join(p for p in parts if p))
                budget.note(out)
                counters["dispatches"] += 1
                self.ledger.append("dispatch", role.name,
                                   {"stage": stage.name, "attempt": attempt, "chars": len(out)})
                parts.append(out)
        assembled = "\n\n".join(p for p in parts if p and p.strip())
        # 结构由系统保证，不靠模型自觉：本阶段只准留自己那几节，越界部分裁掉。
        # 实测模型即使被要求「只写这一片」，也会把整篇写出来——五轮同向失败。
        allowed = self._allowed(stage)
        if allowed:
            assembled = self._trim(assembled, allowed)
        return assembled

    @staticmethod
    def _assemble(stage, upstream: str, assembled: str) -> str:
        """按阶段模式拼进上游：append 追加，replace 换掉。"""
        if stage.mode == "append" and upstream.strip():
            return upstream.rstrip() + "\n\n" + assembled
        return assembled

    def _stage_problems(self, stage, candidate: str, ran: set) -> list[str]:
        problems: list[str] = []
        for name in stage.gate_criteria:
            verdict = self.judge.run(name, candidate)
            ran.add(name)
            problems.extend(verdict.problems)
        return problems

    def _delivery_problems(self, decl, text: str, ran: set) -> list[str]:
        delivery: list[str] = []
        for name in decl.criteria:
            verdict = self.judge.run(name, text)
            ran.add(name)
            delivery.extend(f"{name}: {p}" for p in verdict.problems)
        return delivery

    @staticmethod
    def _write_artifact(folder, name: str, text: str) -> None:
        """落盘一份产出。文件名里的非法字符换成下划线，不静默丢文件。"""
        folder.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)
        (folder / safe).write_text(text, encoding="utf-8")

    def _run_hand(self, role, stage: str) -> str:
        """角色挂了工具就先跑一次手，取回的素材与证据编号进上游。

        为什么放在派活前而不是让写手自己「记得去查」：模型没有手，它只能声称查过。
        取数、落盘、打戳都在这里发生，写手拿到的是一段可以引用的素材。
        """
        if self.hand is None or not getattr(role, "tools", ()):
            return ""
        try:
            material = self.hand(role, stage) or ""
        except Exception as exc:            # 手失败要大声：宁可这一格外，不静默降级
            self.ledger.append("hand_failed", role.name,
                               {"stage": stage, "error": f"{type(exc).__name__}: {exc}"})
            raise
        if material:
            self.ledger.append("hand", role.name, {"stage": stage, "chars": len(material)})
        return material

    def _context(self) -> str:
        return (self.context() or "") if self.context else ""

    @staticmethod
    def _with_material(upstream: str, material: str) -> str:
        return f"{material}\n\n{upstream}" if material else upstream

    def _writer(self, stage) -> str:
        """本阶段谁执笔写标题：优先 executor，没有就第一个角色。

        为什么要有：同一片被三个角色各写一遍，append 之后标题就重复三次——
        实测出现过「## 三 出现 3 次」。
        """
        executors = [n for n in stage.roles if self.plan.role(n).kind == "executor"]
        return (executors or list(stage.roles) or [""])[0]

    @staticmethod
    def _supplement(writer: str) -> str:
        return (f"（本阶段的标题由「{writer}」执笔；你只提供素材、判断或校验意见，"
                f"不要写 ## 标题，也不要把别人的章节再抄一遍。）")

    def _allowed(self, stage) -> set[str]:
        allowed: set[str] = set()
        for name in stage.gate_criteria:
            crit = self.judge.get(name)
            if crit is not None and crit.kind == "sections":
                allowed |= {str(h) for h in (crit.spec.get("required") or [])}
        return allowed

    @staticmethod
    def _trim(text: str, allowed: set[str]) -> str:
        keep: list[str] = []
        inside = False
        seen: set[str] = set()
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                if stripped in allowed and stripped not in seen:
                    seen.add(stripped)
                    inside = True
                else:
                    inside = False
            if inside:
                keep.append(line)
        return "\n".join(keep).strip()

    def _requirements(self, stage) -> str:
        lines: list[str] = []
        for name in stage.gate_criteria:
            crit = self.judge.get(name)
            if crit is None:
                continue
            if crit.kind == "sections":
                lines.extend(f"必须包含：{h}" for h in (crit.spec.get("required") or []))
            elif crit.kind == "regex" and crit.spec.get("literal"):
                lines.append("必须出现：" + "、".join(str(x) for x in (crit.spec.get("patterns") or [])))
        return "\n".join(lines)

    def _feedback(self, raw: str, problems=()) -> str:
        """把「同一类失败的对策」并进重做提示。

        经验先按 failure_kind 取（条件匹配），案例按文本相似兜底：前者能说清「什么时候
        这条算数」，后者只能说「上次也这么说过」。
        """
        hints: list[str] = []
        if self.lesson_path is not None:
            kind = lessonbook.classify(problems or [raw])
            picked = lessonbook.match(lessonbook.all(self.lesson_path),
                                      {"failure_kind": kind}, k=2)
            for lesson in picked:
                text = str(lesson.get("fix") or lesson.get("text") or "").strip()
                if text:
                    hints.append(f"[{kind}] {text}")
            if picked:
                ids = [str(x.get("id")) for x in picked]
                lessonbook.bump(self.lesson_path, ids, "injected")
                stage = getattr(self, "_stage_in_flight", "")
                self._injected.setdefault(stage, []).extend(ids)
                self.ledger.append("lesson", kind, {"ids": ids, "stage": stage})
        if self.cases is not None:
            hints += [f"{c.stage}·{c.fix}" for c in self.cases.similar(raw, k=2) if c.fix]
        return raw + ("；历史案例：" + " / ".join(hints) if hints else "")

    def _report(self, passed: bool, reason: str, *, problems=(), redone=(), rejects=(),
                dispatches: int = 0, budget: Budget | None = None, evidence=(),
                chars: int = 0, ran=(), text: str = "") -> dict:
        return {
            "passed": passed,
            "reason": reason,
            "problems": list(problems),
            "redone": list(redone),
            "rejects": list(rejects),
            "dispatches": dispatches,
            "budget": budget.snapshot() if budget else None,
            "evidence": list(evidence),
            "ran": list(ran),
            "chars": chars,
            "text": text,
            "ledger": str(self.ledger.path) if isinstance(self.ledger.path, Path) else str(self.ledger.path),
        }