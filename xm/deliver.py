"""交付入口：先一个人干，判不过再组队。

依据（同任务的 A/B 实测）：组织臂多花 2 次调用、2645 个 prompt token，只换来更少轮数，
在一个一次性交付任务上没有证明自己更好。所以默认单 agent；组织只在三种情况下上场：
跨 ≥2 个技能域、结果不可逆需要独立复核、单 agent 判据没过。

这两件事必须能分开验证——「该组队时组了」和「不该组队时真没组」，后者更容易被忽略。
所以 single_fn / org_fn 由调用方注入：测试可以塞假实现，直接看组织有没有被误触发。
"""
from __future__ import annotations

import time
from pathlib import Path

from xm import delivery

ORG_TRIGGERS = "任务声明需要 ≥2 个技能域 / stakes 标记为 irreversible / 单 agent 未过判据"


def pre_triggers(task: dict) -> list[str]:
    """还没开干就能看出来该组队的理由。"""
    reasons: list[str] = []
    needs = sorted({str(n).strip() for n in (task.get("needs") or []) if str(n).strip()})
    if len(needs) >= 2:
        reasons.append(f"跨 {len(needs)} 个技能域：{'、'.join(needs)}")
    if str(task.get("stakes", "")).strip() == "irreversible":
        reasons.append("结果不可逆，需要独立复核")
    return reasons


def deliver(goal: str, task: dict, single_fn, org_fn) -> dict:
    attempts: list[dict] = []

    reasons = pre_triggers(task)
    if reasons:
        attempts.append({"mode": "org", "via": "pre", **dict(org_fn())})
        return _report(goal, "org", reasons, attempts)

    single = dict(single_fn())
    attempts.append({"mode": "single", **single})
    if single.get("passed"):
        return _report(goal, "single", ["单 agent 首轮过判据，不组队"], attempts)

    attempts.append({"mode": "org", "via": "escalation", **dict(org_fn())})
    return _report(goal, "org", ["单 agent 未过判据，升级组队"], attempts)


def _report(goal: str, mode: str, reasons: list[str], attempts: list[dict]) -> dict:
    # 交付自证（DNA #9）：判据过了只说明"东西对"，还得说明"话说清"
    final = attempts[-1].get("artifact")
    text = Path(final).read_text(encoding="utf-8") if final and Path(final).exists() else ""
    dcheck = delivery.check(text)
    criteria_ok = bool(attempts[-1].get("passed"))
    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "goal": goal,
        "decision": {"mode": mode, "reasons": reasons, "trigger_doc": ORG_TRIGGERS},
        "attempts": [{k: v for k, v in a.items() if k != "text"} for a in attempts],
        "passed": criteria_ok and dcheck["ok"],
        "criteria_passed": criteria_ok,
        "delivery": dcheck,
        "mode": mode,
        "org_called": any(a["mode"] == "org" for a in attempts),
        "final_artifact": attempts[-1].get("artifact"),
    }