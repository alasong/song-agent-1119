"""S7 外环：用内环读数提出**一条**新因素候选，小预算试一次，决定落盘。

边界（诚实写在这里）：
- 只产候选，不自动改判据/流程——要过 registry 登记才算生效（判定权不在生成方）。
- 一条候选一个实验，预算硬上限；超限直接 refused，一次都不跑。
- 实验的 runner 是注入的：真跑一轮 PDCA 还是假的推进，由调用方决定。
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

RULES = (
    {"metric": "validation_pass_rate", "expect": "down",
     "when": lambda v: v is not None and v >= 0.99,
     "hypothesis": "通过率过高：加一条反例判据，看能否抓出旧门漏掉的错"},
    {"metric": "takeover_rate", "expect": "down",
     "when": lambda v: v is not None and v > 0.2,
     "hypothesis": "接管率偏高：给该角色加一个同 kind 备位"},
    {"metric": "communication_efficiency", "expect": "up",
     "when": lambda v: v is not None and v < 0.5,
     "hypothesis": "有效通信偏低：收紧派活提示词"},
)


def propose(metrics: dict) -> list[dict]:
    """按规则表提一条；没有命中就返回空列表（不硬凑候选）。"""
    for rule in RULES:
        if rule["when"](metrics.get(rule["metric"])):
            return [{
                "id": f"x-{uuid.uuid4().hex[:8]}",
                "hypothesis": rule["hypothesis"],
                "metric": rule["metric"],
                "baseline": metrics[rule["metric"]],
                "expect": rule["expect"],
                "budget": 5_000,
            }]
    return []


def adopt(record: dict, path: str | Path) -> dict:
    """把 adopted 的实验写成 active 的经验，下一轮读它。只收 adopted，别的状态直接拒。"""
    if record.get("status") != "adopted":
        raise ValueError(f"只采纳 status=adopted 的实验，收到 {record.get('status')!r}")
    row = {
        "id": record.get("id") or f"x-{uuid.uuid4().hex[:8]}",
        "kind": "prompt_note",
        "text": record.get("hypothesis") or "",
        "metric": record.get("metric"),
        "after": record.get("after"),
        "at": record.get("at") or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "active",
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def active(path: str | Path) -> list[dict]:
    """下一轮读到的经验：只认 status=active 的行。"""
    target = Path(path)
    if not target.exists():
        return []
    rows: list[dict] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("status") == "active":
            rows.append(row)
    return rows


def run(experiment: dict, runner, *, budget_cap: int = 20_000,
        path: str | Path | None = None) -> dict:
    """跑一次实验并落盘。返回的记录里 status ∈ adopted / rejected / refused。"""
    record = dict(experiment)
    record["id"] = record.get("id") or f"x-{uuid.uuid4().hex[:8]}"
    record["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if int(record.get("budget") or 0) > budget_cap:
        record["status"] = "refused"
        record["why"] = f"预算 {record.get('budget')} > 上限 {budget_cap}"
    else:
        after = runner(record) or {}
        value = after.get(record["metric"])
        record["after"] = value
        base = record.get("baseline")
        if value is None or base is None:
            record["status"] = "rejected"
            record["why"] = "实验没有给出该指标的读数"
        else:
            moved = value < base if record["expect"] == "down" else value > base
            record["status"] = "adopted" if moved else "rejected"
            record["why"] = "指标按预期方向移动" if moved else "指标没有按预期方向移动"
    if path is not None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record