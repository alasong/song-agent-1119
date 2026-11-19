"""消息总线：结构化工单在角色之间的流转（设计文档 §15 / M0b-2）。

一条工单由 ``submit`` 进入 receiver 的 inbox，被 ``claim`` 后转为
``in_progress``，最后用 ``complete`` 或 ``reject`` 收口。``reject`` 不删除
原单：状态改为 ``rejected``、理由按顺序追加，并把同一张单退回 sender 的
inbox（sender 因此可以再认领它）。

同一 id 只允许 ``submit`` 一次：重复提交抛 ``BusError``，不产生第二条。
每次状态变化都追加一条事件到该单的 history，history 只增不改。
"""
from __future__ import annotations

from typing import Any

from .ticket import Ticket

SUBMITTED = "submitted"
IN_PROGRESS = "in_progress"
COMPLETED = "completed"
REJECTED = "rejected"

STATUSES = (SUBMITTED, IN_PROGRESS, COMPLETED, REJECTED)


class BusError(ValueError):
    """总线操作非法：id 重复、单不存在、已被认领、角色不对、状态不符。"""


class Bus:
    """单进程内的工单总线；无参构造。"""

    def __init__(self) -> None:
        self._tickets: dict[str, Ticket] = {}
        self._status: dict[str, str] = {}
        # 当前认领者；未认领时为 None。
        self._owner: dict[str, str | None] = {}
        # role -> 待领工单 id（按提交/退回的追加顺序）。
        self._inboxes: dict[str, list[str]] = {}
        self._rejections: dict[str, list[str]] = {}
        self._history: dict[str, list[dict[str, Any]]] = {}

    # --- 内部工具 ---

    def _inbox_ids(self, role: str) -> list[str]:
        return self._inboxes.setdefault(role, [])

    def _require(self, tid: str) -> Ticket:
        try:
            return self._tickets[tid]
        except KeyError:
            raise BusError(f"工单不存在：{tid}") from None

    def _record(self, tid: str, event_type: str, **fields: Any) -> None:
        event: dict[str, Any] = {"type": event_type, "ticket": tid}
        event.update(fields)
        self._history[tid].append(event)

    def _require_owner(self, role: str, tid: str, action: str) -> None:
        state = self._status[tid]
        if state != IN_PROGRESS:
            raise BusError(f"工单 {tid} 当前状态为 {state}，不能{action}")
        if self._owner[tid] != role:
            raise BusError(f"只有当前认领者能{action}工单 {tid}")

    # --- 对外接口 ---

    def submit(self, ticket: Ticket) -> None:
        """把工单放进 receiver 的 inbox；同一 id 重复提交直接报错。"""
        if not isinstance(ticket, Ticket):
            raise BusError(f"只接受 Ticket，实际是 {type(ticket).__name__}")
        tid = ticket.id
        if tid in self._tickets:
            raise BusError(f"工单 id 重复提交：{tid}")
        self._tickets[tid] = ticket
        self._status[tid] = SUBMITTED
        self._owner[tid] = None
        self._rejections[tid] = []
        self._history[tid] = []
        self._inbox_ids(ticket.receiver).append(tid)
        self._record(tid, SUBMITTED, sender=ticket.sender, receiver=ticket.receiver)

    def inbox(self, role: str) -> list[Ticket]:
        """该角色待领的工单，按进入 inbox 的顺序。"""
        return [self._tickets[tid] for tid in self._inboxes.get(role, [])]

    def claim(self, role: str, tid: str) -> None:
        """由当前持有该单的角色认领；认领后从 inbox 移除并转 in_progress。"""
        self._require(tid)
        if tid not in self._inboxes.get(role, []):
            state = self._status[tid]
            if state == IN_PROGRESS:
                raise BusError(f"工单已被认领：{tid}")
            if state in (COMPLETED, REJECTED):
                raise BusError(f"工单 {tid} 当前状态为 {state}，不在 {role} 的 inbox")
            raise BusError(f"角色 {role} 无权认领工单 {tid}")
        self._inboxes[role].remove(tid)
        self._status[tid] = IN_PROGRESS
        self._owner[tid] = role
        self._record(tid, "claimed", role=role)

    def complete(self, role: str, tid: str) -> None:
        """仅当前认领者可完成，状态转 completed。"""
        self._require(tid)
        self._require_owner(role, tid, "完成")
        self._status[tid] = COMPLETED
        self._record(tid, COMPLETED, role=role)

    def reject(self, role: str, tid: str, reason: str) -> None:
        """仅当前认领者可拒收；单据退回 sender 的 inbox，理由按序留存。"""
        ticket = self._require(tid)
        self._require_owner(role, tid, "拒收")
        if not isinstance(reason, str) or not reason.strip():
            raise BusError("拒收理由必须是非空字符串")
        self._status[tid] = REJECTED
        self._rejections[tid].append(reason)
        self._inbox_ids(ticket.sender).append(tid)
        self._record(tid, REJECTED, role=role, reason=reason)

    def status(self, tid: str) -> str:
        """返回工单当前状态；不存在则报错。"""
        self._require(tid)
        return self._status[tid]

    def stats(self) -> dict[str, int]:
        """按事件累计 submitted / completed / rejected 三个计数。"""
        counts = {SUBMITTED: 0, COMPLETED: 0, REJECTED: 0}
        for events in self._history.values():
            for event in events:
                if event["type"] in counts:
                    counts[event["type"]] += 1
        return counts

    def rejections(self, tid: str) -> list[str]:
        """该单被拒收的理由，按发生顺序。"""
        self._require(tid)
        return list(self._rejections[tid])

    def history(self, tid: str) -> list[dict[str, Any]]:
        """事件序列（每条至少含 type），只增不改；返回副本以防外部改写。"""
        self._require(tid)
        return [dict(event) for event in self._history[tid]]