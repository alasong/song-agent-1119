"""阶段准出流水线：按顺序过闸，失败即把单拒收回 sender（设计文档 §15.4）。

顺序由 ``xm.gates.STAGES`` 固定：跳阶段不是「加速」，是「没做」。任一阶段准出
失败，先把单退回 sender（理由带上失败阶段），再把异常原样往外抛；失败路径不
许把单留在 ``in_progress``——那等于「没人知道这活卡住了」。

单不存在时 ``BusError`` 直接往外抛，不吞。
"""
from __future__ import annotations

from typing import Any

from .bus import SUBMITTED
from .gates import STAGES


class Pipeline:
    """把「认领 → 逐阶段准出 → 完成」串成一条流水线；接收者来自工单本身。"""

    def __init__(self, bus, gate_chain):
        self.bus = bus
        self.gate_chain = gate_chain

    def run(self, ticket_id: str, artifacts: dict[str, Any]) -> None:
        receiver = self._receiver(ticket_id)
        if self.bus.status(ticket_id) == SUBMITTED:
            self.bus.claim(receiver, ticket_id)

        for stage in STAGES:
            # artifacts 按阶段分组：每阶段只拿自己那一份准出项。
            # 兼容直接给准出项名（如 {"判据": True}）的扁平写法。
            payload = artifacts[stage] if stage in artifacts else artifacts
            try:
                self.gate_chain.check(stage, payload)
            except Exception as exc:
                # 先拒收：单退回 sender 的 inbox，理由写明卡在哪个阶段。
                self.bus.reject(receiver, ticket_id, f"「{stage}」准出失败：{exc}")
                raise

        self.bus.complete(receiver, ticket_id)

    def _receiver(self, ticket_id: str) -> str:
        # Bus 没有按 id 取单的公开读口；submit 事件里带着 receiver。
        # 单不存在时 history 抛 BusError，正好原样往外传。
        return self.bus.history(ticket_id)[0]["receiver"]