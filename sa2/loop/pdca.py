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
from ..memory.cases import CaseBook


class PDCA:
    def __init__(self, judge: Judge, ledger: Ledger, plan: OrgPlan, produce: "callable",
                 vocab, usage: list[dict] | None = None,
                 max_stage_attempts: int = 2, cases: CaseBook | None = None,
                 state_path: str | Path | None = None, resume: bool = False,
                 artifact_dir: str | Path | None = None, parallel: bool = False,
                 hand=None):
        """produce(role, stage, upstream, attempt, feedback) -> str。

        feedback 是上一轮这一阶段被拒的原因；第一次尝试为空串。
        带上它的理由很实际：sa 1.0 的整篇重写虽然也带反馈，但代价是整篇；
        2.0 只重做一格，如果这一格不知道上次错在哪，等于把省下的钱又亏回去。
        """
        self.hand = hand          # 角色手上有工具时，派活前先真的取一次（结果进上游与证据台账）
        self.judge = judge
        self.ledger = ledger
        self.plan = plan
        self.produce = produce
        self.vocab = vocab
        self.usage = usage
        self.max_stage_attempts = max_stage_attempts
        self.cases = cases
        self.state_path = Path(state_path) if state_path else None
        self.resume = resume
        self.artifact_dir = Path(artifact_dir) if artifact_dir else None
        self.parallel = parallel

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
        dispatches = 0
        start = 0

        # 断点续跑：多阶段编制一次十几二十次调用，中途挂掉全丢的代价太高
        if self.resume and self.state_path and self.state_path.exists():
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            start = int(state.get("stage_index") or 0)
            text = state.get("text") or text
            ran = set(state.get("ran") or [])
            budget.spent_seed = int(state.get("spent") or 0)
            self.ledger.append("resume", "loop", {"from_stage": start, "spent": budget.spent_seed})

        for index, stage in enumerate(self.plan.stages[start:], start=start):
            # 判据对生成方必须是可见的：看不见要求，只能猜，猜不中就红两次。
            # 可见 ≠ 可控：生成方知道要求是什么，但改不了判据本身。
            requirements = self._requirements(stage)
            writer = self._writer(stage)
            feedback = ""                      # 上一轮被拒的原因：重做必须带着它，否则是盲重做
            for attempt in range(1, self.max_stage_attempts + 1):
                parts: list[str] = []
                roles = [self.plan.role(name) for name in stage.roles]
                # 同一阶段的角色互不依赖（都只读上游、互不写对方），所以这是唯一
                # 不会破坏交接顺序的并发粒度；预算仍串行入账，避免多线程计费打架。
                if self.parallel and len(roles) > 1:
                    if budget.exhausted():
                        self.ledger.append("budget_stop", "loop", budget.snapshot())
                        return self._report(False, budget.why(f"{stage.name} 之前"),
                                            redone=redone, rejects=rejects,
                                            dispatches=dispatches, budget=budget)
                    materials = {role.name: self._run_hand(role, stage.name) for role in roles}
                    with ThreadPoolExecutor(max_workers=len(roles)) as pool:
                        futures = [(role, pool.submit(
                            self.produce, role, stage.name,
                            self._with_material(text, materials[role.name]), attempt, feedback,
                            requirements if role.name == writer else self._supplement(writer)))
                                   for role in roles]
                        for role, future in futures:
                            out = future.result()
                            budget.note(out)
                            dispatches += 1
                            self.ledger.append("dispatch", role.name,
                                               {"stage": stage.name, "attempt": attempt,
                                                "chars": len(out), "parallel": True})
                            parts.append(out)
                else:
                    for role in roles:
                        if budget.exhausted():
                            self.ledger.append("budget_stop", "loop", budget.snapshot())
                            return self._report(False, budget.why(f"{stage.name}·{role.name} 之前"),
                                                redone=redone, rejects=rejects,
                                                dispatches=dispatches, budget=budget)
                        material = self._run_hand(role, stage.name)
                        out = self.produce(role, stage.name, self._with_material(text, material),
                                       attempt, feedback,
                                       requirements if role.name == writer else self._supplement(writer))
                        budget.note(out)
                        dispatches += 1
                        self.ledger.append("dispatch", role.name,
                                           {"stage": stage.name, "attempt": attempt, "chars": len(out)})
                        parts.append(out)

                assembled = "\n\n".join(p for p in parts if p and p.strip())
                # 结构由系统保证，不靠模型自觉：本阶段只准留自己那几节，越界部分裁掉。
                # 实测模型即使被要求「只写这一片」，也会把整篇写出来——五轮同向失败。
                allowed = self._allowed(stage)
                if allowed:
                    assembled = self._trim(assembled, allowed)
                if stage.mode == "append" and text.strip():
                    candidate = text.rstrip() + "\n\n" + assembled
                else:
                    candidate = assembled
                problems: list[str] = []
                for name in stage.gate_criteria:
                    verdict = self.judge.run(name, candidate)
                    ran.add(name)
                    problems.extend(verdict.problems)

                if not problems:
                    text = candidate
                    self.ledger.append("stage_ok", stage.name, {"attempt": attempt})
                    if self.artifact_dir:
                        self.artifact_dir.mkdir(parents=True, exist_ok=True)
                        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in stage.name)
                        (self.artifact_dir / f"{index}-{safe}.md").write_text(
                            candidate, encoding="utf-8")
                    if self.state_path:
                        self.state_path.write_text(json.dumps({
                            "stage_index": index + 1, "text": text,
                            "ran": sorted(ran), "spent": budget.spent,
                        }, ensure_ascii=False), encoding="utf-8")
                    break

                raw = "；".join(problems)
                feedback = self._feedback(raw)
                rejects.append({"stage": stage.name, "attempt": attempt,
                                "problems": problems, "feedback": feedback})
                self.ledger.append("reject", "stage_gate",
                                   {"stage": stage.name, "attempt": attempt, "problems": problems})
                if attempt == self.max_stage_attempts:
                    if self.cases is not None:
                        self.cases.add(stage.name, raw, "按拒收原因逐条修后重做该阶段")
                    return self._report(
                        False, f"阶段「{stage.name}」连续 {attempt} 次未过阶段门",
                        redone=redone, rejects=rejects, dispatches=dispatches, budget=budget)
                # 只重做这一阶段：下游还没跑，上游不用重来
                redone.append(stage.name)
                self.ledger.append("redo_stage", stage.name, {"attempt": attempt})

        # ② 交付门：声明里的全部判据
        delivery: list[str] = []
        for name in decl.criteria:
            verdict = self.judge.run(name, text)
            ran.add(name)
            delivery.extend(f"{name}: {p}" for p in verdict.problems)

        # ③ 证据门 + ④ 不静默失败
        evidence = list(evidence or ())
        evidence_problems = gate.check_evidence(evidence)
        silent = gate.check_silent_failure(self.judge, decl, ran)
        problems = delivery + evidence_problems + silent
        passed = not problems
        self.ledger.append("delivery", "gate",
                           {"passed": passed, "problems": problems, "chars": len(text)})
        return self._report(passed, "" if passed else "交付门/证据门未过",
                            redone=redone, rejects=rejects, dispatches=dispatches,
                            budget=budget, problems=problems, evidence=evidence,
                            chars=len(text), ran=sorted(ran), text=text)

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

    def _feedback(self, raw: str) -> str:
        """把历史案例并进重做提示：没有这一句，案例库就只是写不读的死功能。"""
        if self.cases is None:
            return raw
        hints = [f"{c.stage}·{c.fix}" for c in self.cases.similar(raw, k=2) if c.fix]
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