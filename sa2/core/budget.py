"""预算闸：发一次请求扣一次账，超了就不许再发。

口径与 sa 1.0 的 daemon 一致：有真实 usage 用真值，没有就按字符数估
（4 字符 ≈ 1 token）。估出来的数不是真上限，所以 `exact` 要对外暴露，
谁看报告谁就该知道这次的数是怎么来的。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Budget:
    tokens: int
    usage: list[dict] = field(default_factory=list)
    chars: int = 0
    calls: int = 0
    spent_seed: int = 0        # 断点续跑：上一次运行已经花掉的部分

    def note(self, text: str) -> None:
        self.calls += 1
        self.chars += len(text or "")

    @property
    def exact(self) -> bool:
        return bool(self.usage)

    @property
    def spent(self) -> int:
        if self.usage:
            now = sum(int(u.get("total_tokens") or u.get("completion_tokens") or 0)
                      for u in self.usage)
        elif self.calls:
            now = max(1, self.chars // 4)
        else:
            now = 0
        return self.spent_seed + now

    def exhausted(self) -> bool:
        return self.spent > self.tokens

    def why(self, where: str = "") -> str:
        tail = f"，停在 {where}" if where else ""
        return f"预算用尽：已花 {self.spent} > {self.tokens} tokens{tail}"

    def snapshot(self) -> dict:
        return {"tokens": self.tokens, "spent": self.spent, "exact": self.exact,
                "calls": self.calls}