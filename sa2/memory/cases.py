"""案例库：失败案例优先。

成功案例教你「可以这么写」，失败案例教你「这样会被拒」——后者更省 token，
因为它是唯一能避免同一阶段被拒两次的东西。检索用字符二元组重合，不引分词。
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Case:
    stage: str
    reason: str
    fix: str
    ts: str = ""


def _grams(text: str) -> set[str]:
    clean = "".join(ch for ch in (text or "") if ch.strip())
    return {clean[i:i + 2] for i in range(len(clean) - 1)} or {clean}


class CaseBook:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def add(self, stage: str, reason: str, fix: str) -> Case:
        case = Case(stage=stage, reason=reason, fix=fix,
                    ts=time.strftime("%Y-%m-%dT%H:%M:%S"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(case), ensure_ascii=False) + "\n")
        return case

    def all(self) -> list[Case]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(Case(**json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                continue
        return out

    def similar(self, reason: str, k: int = 3) -> list[Case]:
        target = _grams(reason)
        scored = []
        for case in self.all():
            overlap = len(target & _grams(case.reason))
            if overlap:
                scored.append((overlap, case))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [case for _, case in scored[:k]]