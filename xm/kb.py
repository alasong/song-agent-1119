"""知识底座：只收**带证据**的事实，跨领域可检索（G4 的基础）。

设计约束：
- 没有证据的事实不收（否则底座会被幻觉污染）
- 只增不改；同一事实重复写入按内容去重
- 领域标签是数据，不是代码——换领域只换数据
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path


class KnowledgeError(RuntimeError):
    pass


def default_path() -> Path:
    return Path(os.environ.get("XM_KB_PATH", str(Path.home() / "xm-runs" / "kb" / "kb.jsonl")))


def terms(text: str) -> set[str]:
    """粗分词：英文按词、中文按二元组。不引入分词依赖，够做检索排序即可。"""
    low = (text or "").lower()
    out = set(re.findall(r"[a-z0-9_]{2,}", low))
    for chunk in re.findall(r"[\u4e00-\u9fff]+", low):
        out |= {chunk[i:i + 2] for i in range(len(chunk) - 1)} if len(chunk) > 1 else {chunk}
    return out


def as_prompt_block(facts: list["Fact"]) -> str:
    """把检索到的事实拼成提示词片段；没有事实就返回空串（不留空标题占位置）。"""
    if not facts:
        return ""
    lines = [f"- [{f.key}] {f.claim}（来源：{f.source}）" for f in facts]
    return ("## 已验证事实（来自知识底座）\n"
            "引用其中某条时写 [ref:<key>]，否则不要凭空引用。\n" + "\n".join(lines))


def conclusion_of(text: str, limit: int = 80) -> str:
    """从交付正文里取一句可当事实存的结论。

    先跳过 Markdown 标题行——标题是「一、结论」这种结构词，存进底座等于存了个目录。
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for line in lines:
        if not line.startswith("#"):
            return line[:limit]
    for line in lines:
        return line.lstrip("#").strip()[:limit]
    return ""


def writeback_if_passed(kb: "KnowledgeBase", passed: bool, text: str,
                        evidence: list[str], source: str = "delivery",
                        domain: str = "交付") -> "Fact | None":
    """过判据才回写。没过判据的结论收进底座，等于把错的记成已验证。"""
    if not passed:
        return None
    claim = conclusion_of(text)
    if not claim:
        return None
    if not evidence:
        raise KnowledgeError("回写必须带证据，否则底座会被自己的结论污染")
    return kb.add(claim, domain, list(evidence), source)


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

    def keys(self) -> set[str]:
        return set(self._facts)

    def retrieve(self, query: str, limit: int = 3) -> list[Fact]:
        """按词重叠排序取前几条。只检索等于买了书不对页码——派活时要真的用上。"""
        wanted = terms(query)
        if not wanted:
            return []
        scored = []
        for fact in self._facts.values():
            overlap = len(wanted & terms(f"{fact.claim} {' '.join(fact.evidence)}"))
            if overlap:
                scored.append((overlap, fact.claim, fact))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [fact for _, _, fact in scored[:limit]]

    def domains(self) -> list[str]:
        return sorted({f.domain for f in self._facts.values()})

    def count(self, domain: str | None = None) -> int:
        return sum(1 for f in self._facts.values() if domain is None or f.domain == domain)