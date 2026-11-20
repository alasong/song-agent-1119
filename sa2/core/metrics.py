"""健康指标：只算账本与读数里真有的量；算不出的列进 `unavailable`，不拿零冒充健康。

已可算（都能从历史 run 复跑）：
- 校验通过率 = 阶段通过 / (阶段通过 + 拒收)
- 接管率 = takeover / dispatch
- 通信效率 = 有产出的 dispatch / dispatch
- 资源利用率 = 交付字数 × 1000 / 花费 token

暂不可算（需要新数据源，见 `unavailable`）：
- 目标偏离度（需要目标语义相似度）
- 假设证伪率（需要假设与推翻记录）

一条口径来自 §15.1：**通过率异常高才是异常**——它可能说明门太松，不是组织健康。
"""
from __future__ import annotations

import json
from pathlib import Path

UNAVAILABLE = (
    "目标偏离度（需要目标语义相似度，当前无数据源）",
    "假设证伪率（需要假设与推翻记录，当前无数据源）",
)


def compute(events: list[dict], readings: dict | None = None) -> dict:
    readings = readings or {}

    def count(kind: str) -> int:
        return sum(1 for e in events if e.get("kind") == kind)

    dispatches = count("dispatch")
    rejects = count("reject")
    stage_ok = count("stage_ok")
    takeovers = count("takeover")
    delivery = [e for e in events if e.get("kind") == "delivery"]
    passed = bool(delivery and (delivery[-1].get("payload") or {}).get("passed"))
    tokens = int(((readings.get("budget") or {}).get("spent")) or 0)
    chars = int(readings.get("chars") or 0)
    checks = stage_ok + rejects
    nonempty = sum(1 for e in events
                   if e.get("kind") == "dispatch"
                   and int((e.get("payload") or {}).get("chars") or 0) > 0)

    out = {
        "dispatches": dispatches,
        "rejects": rejects,
        "stage_ok": stage_ok,
        "takeovers": takeovers,
        "tokens": tokens,
        "chars": chars,
        "validation_pass_rate": (stage_ok / checks) if checks else None,
        "takeover_rate": (takeovers / dispatches) if dispatches else None,
        "communication_efficiency": (nonempty / dispatches) if dispatches else None,
        "resource_efficiency": (chars * 1000.0 / tokens) if tokens else None,
        "delivery_passed": passed if delivery else None,
        "flags": [],
        "unavailable": list(UNAVAILABLE),
    }
    if out["validation_pass_rate"] is not None and out["validation_pass_rate"] >= 0.99 and rejects == 0:
        out["flags"].append("校验通过率过高（≈100% 且零拒收）：门可能太松")
    if out["takeover_rate"] and out["takeover_rate"] > 0.2:
        out["flags"].append("接管率偏高：通道或角色不稳")
    if out["resource_efficiency"] is not None and out["resource_efficiency"] < 50:
        out["flags"].append("资源利用率偏低：每千 token 产出不足 50 字")
    if out["communication_efficiency"] is not None and out["communication_efficiency"] < 0.5:
        out["flags"].append("通信效率偏低：过半派活没有产出")
    return out


def from_run(run_dir: str | Path) -> dict:
    """复算一次历史 run：读 `ledger.jsonl` 与 `readings.json`，不重跑模型。"""
    run_dir = Path(run_dir)
    events: list[dict] = []
    ledger = run_dir / "ledger.jsonl"
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
    readings: dict = {}
    saved = run_dir / "readings.json"
    if saved.exists():
        readings = json.loads(saved.read_text(encoding="utf-8"))
    return compute(events, readings)