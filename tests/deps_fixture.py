"""W4/W5 共用夹具：两阶段编制 + 假 produce + 真 Judge。"""
from __future__ import annotations

import json
from pathlib import Path

from sa2.core.deps import Assertion, DepNote
from sa2.core.gate import Declaration
from sa2.core.judge import Judge
from sa2.core.ledger import Ledger
from sa2.forge import criteria as fc
from sa2.forge import dims as fd
from sa2.forge import org as fo
from sa2.loop.pdca import PDCA

ORG = json.dumps({
    "roles": [
        {"name": "规划", "kind": "planner", "duty": "拆", "criteria": "可验收", "budget": 10},
        {"name": "执行", "kind": "executor", "duty": "写", "criteria": "齐全", "budget": 20},
        {"name": "验证", "kind": "verifier", "duty": "只判", "criteria": "有结论", "budget": 5},
    ],
    "stages": [
        {"name": "起草", "output": "草稿", "roles": ["规划", "执行"], "gate_criteria": ["起草齐全"]},
        {"name": "成稿", "output": "成稿", "roles": ["执行", "验证"], "gate_criteria": ["成稿齐全"]},
    ],
}, ensure_ascii=False)

S1, S2, S3 = "## 一、a", "## 二、b", "## 三、c"


def make_judge() -> Judge:
    judge = Judge(authority=("leader",))
    for name, required in (("起草齐全", [S1, S2]), ("成稿齐全", [S1, S2, S3])):
        judge.register(fc.tested(fc.propose_sections(name, required,
                                                     ("correctness", "test_quality"))),
                       proposer="leader")
    return judge


def note(step: str, verify: str = "cmd:true") -> DepNote:
    return DepNote(step, (
        Assertion("抓取工具", "tool", "能取回至少 2 条真实记录", verify, "换成 hn 源"),
    ))


class Fixture:
    def __init__(self, root, *, require_deps: bool = False, dep_notes=None,
                 produce=None, **pdca_kw):
        self.calls: list[tuple[str, str, int]] = []
        self.ledger = Ledger(Path(root) / "l.jsonl")
        self.pdca = PDCA(make_judge(), self.ledger, fo.parse_plan("目标", ORG),
                         produce or self._produce, fd.VOCAB, max_stage_attempts=2,
                         require_deps=require_deps, dep_notes=dep_notes, **pdca_kw)

    def _produce(self, role, stage, upstream, attempt, feedback="", requirements=""):
        self.calls.append((role.name, stage, attempt))
        if role.kind != "executor":
            return ""
        if stage == "起草":
            return f"{S1}\n{S2}\n"
        return f"{S1}\n{S2}\n{S3}\n"

    def decl(self, **kw) -> Declaration:
        base = dict(goal="写东西", dims=("correctness", "test_quality"),
                    criteria=("起草齐全", "成稿齐全"), budget_tokens=100_000)
        base.update(kw)
        return Declaration(**base)