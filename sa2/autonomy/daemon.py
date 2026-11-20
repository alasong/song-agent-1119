"""M3：常驻调度的 drain 形态。

`tick_loop` 已经会「连着跑、空了停」；这一层补的是**能被启动的入口**：
记 `daemon_start/daemon_stop`、把这一轮的读数汇总出来。
状态不另存：完成/失败都写回 backlog，所以重启天然不重跑已完成的目标。

边界：空队列即退出（可按 cron 反复拉起）；「等新工单」的长驻是后面加 poll 的事。
"""
from __future__ import annotations

from .tick import tick_loop


def drain(backlog, ledger, judge, produce, vocab, *, max_ticks: int = 100, **kw) -> dict:
    ledger.append("daemon_start", "autonomy", {"max_ticks": max_ticks})
    results = tick_loop(backlog, ledger, judge, produce, vocab,
                        max_ticks=max_ticks, **kw)
    ran = [r for r in results if r.ran]
    passed = [r for r in ran if (r.report or {}).get("passed")]
    ledger.append("daemon_stop", "autonomy", {"ran": len(ran), "passed": len(passed)})
    return {"ticks": results, "ran": len(ran), "passed": len(passed)}