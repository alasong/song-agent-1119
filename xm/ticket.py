"""结构化工单：系统里唯一合法的通信形态（设计文档 §6）。

§6 只允许「结构化工单（JSON）、禁止自由聊天」，所以格式校验必须卡在入口：
非对象、缺字段、多字段、类型不对、未知 kind 一律拒收；fact 还必须带证据链
（§8 底线 1「所有通信仅结构化工单」、3「所有产出附带证据链」、
4「知识底座只存已验证事实」）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

REQUIRED_FIELDS = ("id", "kind", "sender", "receiver", "goal", "evidence")
TEXT_FIELDS = ("id", "kind", "sender", "receiver", "goal")
KINDS = ("task", "fact")
# 事实类工单会被归档进知识底座，没有证据链的事实不许流通。
EVIDENCE_REQUIRED_KINDS = ("fact",)


class TicketError(ValueError):
    """工单非法：非对象、缺字段、多字段、类型错、未知 kind、事实无证据。"""


@dataclass
class Ticket:
    id: str
    kind: str
    sender: str
    receiver: str
    goal: str
    evidence: list[str] = field(default_factory=list)

    @classmethod
    def parse(cls, payload: Any) -> "Ticket":
        if not isinstance(payload, dict):
            raise TicketError(f"工单必须是 JSON 对象，实际是 {type(payload).__name__}")
        missing = [name for name in REQUIRED_FIELDS if name not in payload]
        if missing:
            raise TicketError(f"工单缺必填字段：{', '.join(missing)}")
        unknown = sorted(set(payload) - set(REQUIRED_FIELDS))
        if unknown:
            raise TicketError(f"工单含未知字段：{', '.join(unknown)}")
        for name in TEXT_FIELDS:
            value = payload[name]
            if not isinstance(value, str) or not value.strip():
                raise TicketError(f"字段 {name} 必须是非空字符串")
        kind = payload["kind"]
        if kind not in KINDS:
            raise TicketError(f"未知工单类型：{kind!r}；允许 {', '.join(KINDS)}")
        evidence = payload["evidence"]
        if not isinstance(evidence, list):
            raise TicketError("字段 evidence 必须是列表")
        for item in evidence:
            if not isinstance(item, str) or not item.strip():
                raise TicketError("证据项必须是非空字符串")
        if kind in EVIDENCE_REQUIRED_KINDS and not evidence:
            raise TicketError(f"{kind} 类工单必须附带证据链")
        return cls(
            id=payload["id"],
            kind=kind,
            sender=payload["sender"],
            receiver=payload["receiver"],
            goal=payload["goal"],
            evidence=list(evidence),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "sender": self.sender,
            "receiver": self.receiver,
            "goal": self.goal,
            "evidence": list(self.evidence),
        }