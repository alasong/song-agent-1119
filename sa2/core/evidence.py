"""证据：一条「某次真实取回」的记录。判定只认记录，不认文本里的日期。

为什么要有它：上一版拿一条判据去查交付文本里的日期和占位符——那些日期是模型
自己打的，模型把 2025-05 改成 2026-11 就绿了，事实一点没变。那等于让生成方给
自己打分。证据原语把时间锚点从「模型写的字」搬到「系统打戳的记录」：

- `fetched_at` 由 `stamp()` 用系统时间打，模型无权写；
- `digest` 是取回落盘内容的 sha256，`add()` 会重新算一遍——记录被改过就进不来；
- 判据只问「正文里的 `[S1]` 能不能在台账里找到、且它的取回时间还在窗口内」。

**判到哪里为止（不假装更多）**：本模块证明「这条引用背后有一次取回，且内容与记录
一致」；它**不**证明取回的内容为真、为最新版本，也不证明引用位置恰当。那些要等
取数的工具与独立核验，不是台账能保证的。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

DEFAULT_MAX_AGE_DAYS = 180
MARKER = re.compile(r"\[([A-Za-z]{1,3}\d{1,3})\]")


class EvidenceError(RuntimeError):
    """台账拒绝：形状不对、内容对不上、或重复登记。"""


@dataclass(frozen=True)
class Evidence:
    evidence_id: str      # 正文里引用的标记：S1、E12
    uri: str              # 从哪取的
    fetched_at: str       # 系统打戳（ISO），模型无权写
    content_path: str     # 取回内容的落盘位置（按内容寻址）
    digest: str           # 内容 sha256 前 16 位，add 时复算
    verifier: str         # 谁记录的（登记方，不是生成方）
    note: str = ""


def digest_of(content: bytes | str) -> str:
    raw = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(raw).hexdigest()[:16]


def _parse(ts: str) -> date:
    try:
        return datetime.fromisoformat(ts).date()
    except ValueError as exc:
        raise EvidenceError(f"取回时间不是 ISO 时间：{ts!r}") from exc


def stamp(uri: str, content: bytes | str, verifier: str, evidence_id: str,
          root: str | Path, now: datetime | None = None) -> Evidence:
    """把一次取回写成证据：内容落盘 + 系统打戳。没有内容就没有证据。"""
    digest = digest_of(content)
    folder = Path(root)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{digest}.txt"
    if not target.exists():
        raw = content.encode("utf-8") if isinstance(content, str) else content
        target.write_bytes(raw)
    if not uri.strip():
        raise EvidenceError("证据缺 uri：不知道这份内容从哪来")
    stamp_at = (now or datetime.now()).replace(microsecond=0).isoformat()
    return Evidence(evidence_id=str(evidence_id).strip(), uri=uri.strip(),
                    fetched_at=stamp_at, content_path=str(target), digest=digest,
                    verifier=verifier)


class EvidenceBook:
    """只增不改的证据台账（JSONL），与账本同构。"""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def all(self) -> list[Evidence]:
        if not self.path.exists():
            return []
        out: list[Evidence] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            out.append(Evidence(**data))
        return out

    def ids(self) -> set[str]:
        return {ev.evidence_id for ev in self.all()}

    def get(self, evidence_id: str) -> Evidence | None:
        return next((ev for ev in self.all() if ev.evidence_id == evidence_id), None)

    def add(self, ev: Evidence) -> Evidence:
        """入账前重算 digest：记录说取回到了什么，盘上就得真是那个东西。"""
        if not ev.evidence_id:
            raise EvidenceError("证据缺 id：正文没法引用它")
        if ev.evidence_id in self.ids():
            raise EvidenceError(f"证据 id 重复：{ev.evidence_id}")
        path = Path(ev.content_path)
        if not path.is_file():
            raise EvidenceError(f"证据 {ev.evidence_id} 没有落盘内容：{path}")
        actual = digest_of(path.read_bytes())
        if actual != ev.digest:
            raise EvidenceError(f"证据 {ev.evidence_id} 的内容与 digest 不符"
                                f"（记录 {ev.digest}，实际 {actual}）——记录被改过")
        _parse(ev.fetched_at)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({**ev.__dict__}, ensure_ascii=False) + "\n")
        return ev


def markers(text: str) -> list[str]:
    """正文里出现过的引用标记，按首次出现顺序去重。"""
    seen: list[str] = []
    for found in MARKER.findall(text or ""):
        if found not in seen:
            seen.append(found)
    return seen


def citation_problems(text: str, book: EvidenceBook, today: date | None = None,
                      max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> list[str]:
    """每个引用都要在台账里，且取回时间撑得起「最新」。空 ⇒ 通过。"""
    now = today or date.today()
    problems: list[str] = []
    known = {ev.evidence_id: ev for ev in book.all()}
    for marker in markers(text):
        ev = known.get(marker)
        if ev is None:
            problems.append(f"引用 [{marker}] 不在证据台账里——它没有对应的取回记录")
            continue
        fetched = _parse(ev.fetched_at)
        age = (now - fetched).days
        if age < 0:
            problems.append(f"引用 [{marker}] 的取回时间 {ev.fetched_at} 晚于今天"
                            f"（{now.isoformat()}）——那是编的")
        elif age > max_age_days:
            problems.append(f"引用 [{marker}] 的取回时间 {ev.fetched_at}，距今 {age} 天"
                            f" > {max_age_days} 天——这份数据撑不起「最新」")
    return problems


def checker(book: EvidenceBook):
    """给 judge 当 callable 判据用：只传 text，台账由闭包带进来。"""
    def run(text: str) -> list[str]:
        return citation_problems(text, book)
    return run