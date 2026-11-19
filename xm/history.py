"""跨轮记录：让「这轮比上轮强在哪」有地方可查。

以前每轮的账本写在各自 run_dir 里，跑完就散——攒了 4 次 RSI 运行，没有一处能比较。
这里只做三件事：

- `append()`：一次运行落一条，含目标、编制签名、结果读数、质量分；
- `load()`：读全部记录，坏行跳过并计数（不静默吞）；
- `by_family()` / `growth()`：按任务族聚合，给出「最好的一次」与「最近一次」。

判不了的明说：没有质量分的记录只能比成本与通过率，不能算「能力增长」。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path


def history_path() -> Path:
    return Path(os.environ.get("XM_HISTORY",
                               str(Path.home() / "xm-runs" / "history" / "history.jsonl")))


@dataclass(frozen=True)
class Record:
    ts: str
    family: str            # 任务名，用来判断「同一族」
    goal: str
    org_signature: str     # 编制签名：角色 kind 序列 + 阶段数，用来分辨"哪套班子"
    mode: str              # single / org
    passed: bool
    quality: int | None    # 0–15，盲评分；None = 没打分
    calls: int
    prompt_tokens: int
    completion_tokens: int
    chars: int
    artifact: str

    @property
    def key(self) -> str:
        raw = f"{self.family}|{self.goal}|{self.org_signature}|{self.ts}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


def signature(roles: list | None = None, stages: int = 0) -> str:
    """编制签名：kind 序列（拿不到 kind 就用角色数）+ 阶段数。同样的班子只该一个签名。"""
    rows = roles or []
    if rows and isinstance(rows[0], dict):
        kinds = "-".join(str(r.get("kind", "?")) for r in rows)
    else:
        kinds = f"{len(rows)}roles" if rows else "none"
    return f"{kinds}/stages{stages}"


def append(record: Record, path: Path | None = None) -> Path:
    target = path or history_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
    return target


def load(path: Path | None = None) -> tuple[list[Record], int]:
    """返回 (记录, 坏行数)。坏行不静默：调用方要把数字报出来。"""
    target = path or history_path()
    if not target.exists():
        return [], 0
    rows, bad = [], 0
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(Record(**json.loads(line)))
        except (json.JSONDecodeError, TypeError):
            bad += 1
    return rows, bad


def by_family(records: list[Record]) -> dict[str, list[Record]]:
    groups: dict[str, list[Record]] = {}
    for rec in records:
        groups.setdefault(rec.family, []).append(rec)
    for rows in groups.values():
        rows.sort(key=lambda r: r.ts)
    return groups


def growth(records: list[Record]) -> dict:
    """每族给出：轮数、最近一次、最好质量分、是否退化、能否声称增长。"""
    out: dict[str, dict] = {}
    for family, rows in by_family(records).items():
        scored = [r for r in rows if r.quality is not None]
        best = max(scored, key=lambda r: r.quality) if scored else None
        last = rows[-1]
        regressed = bool(best and last.quality is not None and last.quality < best.quality)
        out[family] = {
            "runs": len(rows),
            "scored_runs": len(scored),
            "last": {"ts": last.ts, "quality": last.quality, "calls": last.calls,
                     "passed": last.passed, "signature": last.org_signature},
            "best": {"ts": best.ts, "quality": best.quality} if best else None,
            "regressed": regressed,
            # 只有「同族 ≥2 次且每次都有分」才谈得上增长
            "can_claim_growth": len(scored) >= 2,
        }
    return out


def now_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")