"""预算闸：发一次请求扣一次账，超了就不许再发。

口径与 sa 1.0 的 daemon 一致：有真实 usage 用真值，没有就按字符数估
（4 字符 ≈ 1 token）。估出来的数不是真上限，所以 `exact` 要对外暴露，
谁看报告谁就该知道这次的数是怎么来的。

**嵌套只有一池钱**：子任务不再 `Budget(自己的上限)`，而是 `父.child(份额)`——
份额被夹在父池剩余里，所以「子任务给自己加预算」在结构上做不到。
`spent` 是本层花的（根层就是全部），`total` 是连同祖先的池子账。
估算口径下父子各自记自己的字符数，同时向祖先转记一次，池子才不会被低估。
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
    parent: "Budget | None" = None   # 嵌套：父池；子层只能在这条链里花钱
    usage_start: int = 0       # 共享 usage 列表时，本层从哪一条开始算自己的

    def note(self, text: str) -> None:
        self.calls += 1
        self.chars += len(text or "")
        if self.parent is not None:
            # 估算口径不共享列表，得把本层花的转记给祖先，否则池子被低估
            self.parent.calls += 1
            self.parent.chars += len(text or "")

    @property
    def exact(self) -> bool:
        return bool(self.usage)

    @property
    def spent(self) -> int:
        """本层花的。根层没有父，所以它就是全部。"""
        if self.usage:
            now = sum(int(u.get("total_tokens") or u.get("completion_tokens") or 0)
                      for u in self.usage[self.usage_start:])
        elif self.calls:
            now = max(1, self.chars // 4)
        else:
            now = 0
        return self.spent_seed + now

    @property
    def total(self) -> int:
        """池子总额：取最外层那一层的账。

        父子共享同一个 `usage` 列表（估算口径下子层会向祖先转记），所以最外层
        天然看得到全部。**不能**写成 `self.spent + parent.total`——那会把子层
        花的算两遍。
        """
        return self.chain()[-1].spent

    def chain(self) -> list["Budget"]:
        node, out = self, []
        while node is not None:
            out.append(node)
            node = node.parent
        return out

    def exhausted(self) -> bool:
        """本层超了自己的份额，或链上任何一层超了池子，都算用尽。"""
        if self.tokens <= 0:
            return True
        return any(node.spent > node.tokens for node in self.chain())

    def child(self, limit: int) -> "Budget":
        """开一个子任务的份额：夹在父池剩余里，**不能**给自己加额度。"""
        remaining = max(0, self.tokens - self.spent)
        return Budget(tokens=min(int(limit), remaining), usage=self.usage,
                      parent=self, usage_start=len(self.usage))

    def why(self, where: str = "") -> str:
        tail = f"，停在 {where}" if where else ""
        head = f"预算用尽：本层已花 {self.spent} > 本层上限 {self.tokens} tokens"
        if self.parent is not None:
            head += f"（池子已花 {self.total} / 上限 {self.chain()[-1].tokens}）"
        return f"{head}{tail}"

    def snapshot(self) -> dict:
        return {"tokens": self.tokens, "spent": self.spent, "total": self.total,
                "exact": self.exact, "calls": self.calls}