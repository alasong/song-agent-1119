"""S8：资源账本与分档授权。

三条规则（设计 §11 的「判定权 vs 判断权」落在这里）：
- 账本是唯一真源：池子总额、花费、待批队列都由事件重放出来，没有第二份可改的余额；
- 分档授权：额度 ≤ 自花阈值直接记支出；**超阈值只进领导队列、不扣款**，
  调用方拿到 `pending` 就必须停——这就是「不能继续」的物理形态；
- 池不可超支：request 与 approve 都先查余额，超了就 refused。

边界：只做账本与审批，不接真支付通道；真花钱的适配器以后换，接口不变。
"""
from __future__ import annotations

import uuid

from .ledger import Ledger

POOL = "resource_pool"
SPEND = "resource_spend"
PENDING = "resource_pending"
REJECTED = "resource_rejected"


class ResourceBook:
    def __init__(self, ledger: Ledger, total: int | None = None, auto_ceiling: int = 100):
        self.ledger = ledger
        self.auto_ceiling = int(auto_ceiling)
        pools = [e for e in ledger.read() if e.get("kind") == POOL]
        if not pools:
            if total is None:
                raise ValueError("首次建立资源账本必须给总额")
            ledger.append(POOL, "leader", {"total": int(total), "currency": "credit"})
            self._total = int(total)
        else:
            self._total = int((pools[0].get("payload") or {}).get("total") or 0)

    def total(self) -> int:
        return self._total

    def spent(self) -> int:
        return sum(int((e.get("payload") or {}).get("amount") or 0)
                   for e in self.ledger.read() if e.get("kind") == SPEND)

    def remaining(self) -> int:
        return self._total - self.spent()

    def pending(self) -> list[dict]:
        events = self.ledger.read()
        resolved = {(e.get("payload") or {}).get("id")
                    for e in events if e.get("kind") in (SPEND, REJECTED)}
        return [dict(e.get("payload") or {}) for e in events if e.get("kind") == PENDING
                and (e.get("payload") or {}).get("id") not in resolved]

    def request(self, amount: int, purpose: str, *, by: str = "sa") -> dict:
        amount = int(amount)
        if amount <= 0:
            raise ValueError("金额必须为正")
        if amount > self.remaining():
            return {"status": "refused", "id": "", "amount": amount,
                    "reason": f"池不足：剩 {self.remaining()}，要 {amount}"}
        request_id = f"r-{uuid.uuid4().hex[:8]}"
        if amount <= self.auto_ceiling:
            self.ledger.append(SPEND, by, {"id": request_id, "amount": amount,
                                           "purpose": purpose, "approved_by": "auto"})
            return {"status": "approved", "id": request_id, "amount": amount,
                    "approved_by": "auto"}
        self.ledger.append(PENDING, by, {"id": request_id, "amount": amount,
                                         "purpose": purpose})
        return {"status": "pending", "id": request_id, "amount": amount,
                "reason": f"金额 {amount} > 自花阈值 {self.auto_ceiling}：等领导批"}

    def approve(self, request_id: str, *, by: str = "leader") -> dict:
        item = self._find(request_id)
        amount = int(item.get("amount") or 0)
        if amount > self.remaining():
            self.ledger.append(REJECTED, by, {"id": request_id, "amount": amount,
                                              "reason": "批准时池已不足"})
            return {"status": "refused", "id": request_id, "amount": amount,
                    "reason": f"池不足：剩 {self.remaining()}，要 {amount}"}
        self.ledger.append(SPEND, by, {"id": request_id, "amount": amount,
                                       "purpose": item.get("purpose"),
                                       "approved_by": by})
        return {"status": "approved", "id": request_id, "amount": amount,
                "approved_by": by}

    def reject(self, request_id: str, *, by: str = "leader") -> dict:
        item = self._find(request_id)
        amount = int(item.get("amount") or 0)
        self.ledger.append(REJECTED, by, {"id": request_id, "amount": amount})
        return {"status": "rejected", "id": request_id, "amount": amount}

    def _find(self, request_id: str) -> dict:
        for item in self.pending():
            if item.get("id") == request_id:
                return item
        raise KeyError(request_id)