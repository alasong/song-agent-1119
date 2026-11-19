"""知识底座：只收**带证据**的事实，跨领域可检索（G4 的基础）。

设计约束：
- 没有证据的事实不收（否则底座会被幻觉污染）
- 只增不改；同一事实重复写入按内容去重
- 领域标签是数据，不是代码——换领域只换数据
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path


class KnowledgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Fact:
    claim: str
    domain: str
    evidence: list[str]
    source: str

    @property
    def key(self) -> str:
        return hashlib.sha256(f"{self.domain}::{self.claim}".encode()).hexdigest()[:16]


class KnowledgeBase:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._facts: dict[str, Fact] = {}
        if self.path and self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    f = Fact(**json.loads(line))
                    self._facts[f.key] = f

    def add(self, claim: str, domain: str, evidence: list[str], source: str) -> Fact:
        if not claim.strip():
            raise KnowledgeError("事实不能为空")
        if not evidence:
            raise KnowledgeError("没有证据的事实不收——底座只存已验证内容")
        fact = Fact(claim.strip(), domain.strip(), list(evidence), source)
        if fact.key in self._facts:
            return self._facts[fact.key]
        self._facts[fact.key] = fact
        if self.path:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(fact), ensure_ascii=False) + "\n")
        return fact

    def search(self, query: str, domain: str | None = None, limit: int = 5) -> list[Fact]:
        q = query.lower()
        hits = [f for f in self._facts.values()
                if (domain is None or f.domain == domain)
                and (q in f.claim.lower() or any(q in e.lower() for e in f.evidence))]
        return sorted(hits, key=lambda f: len(f.claim))[:limit]

    def domains(self) -> list[str]:
        return sorted({f.domain for f in self._facts.values()})

    def count(self, domain: str | None = None) -> int:
        return sum(1 for f in self._facts.values() if domain is None or f.domain == domain)