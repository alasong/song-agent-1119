"""把模型接进环：角色 + 阶段 + 上游 + 上次被拒原因 → 提示词 → 正文。

不在这里做的事（都推给已经有解的那一层）：
- 重试与 usage 记账 → 模型通道。只要它符合 `llm(messages, max_tokens) -> str` 这个形状，
  把同一个 usage 列表同时交给 Scribe 和 PDCA，预算闸读到就是真数。
- 判据与门 → 不碰。生成方只产正文，产完由 core 判。

验证角色默认不产正文：它只判不写，这是编制约定，不是模型能改的事。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

LLM = Callable[..., str]

FIRST = "这是第 1 次尝试。"
RETRY = "这是第 {attempt} 次尝试，上一次这一阶段被拒。"


@dataclass
class Scribe:
    llm: LLM
    usage: list[dict] = field(default_factory=list)
    spec: str = ""              # 任务规格：所有角色共用，判据按它判
    max_tokens: int = 1200
    upstream_chars: int = 1200
    calls: int = 0

    def __call__(self, role, stage, upstream: str, attempt: int, feedback: str = "",
                requirements: str = "") -> str:
        if role.kind == "verifier":
            return ""
        self.calls += 1
        text = self.llm([{"role": "user", "content": self.prompt(role, stage, upstream, attempt,
                                                                feedback, requirements)}],
                        self.max_tokens)
        return text or ""

    def prompt(self, role, stage: str, upstream: str, attempt: int, feedback: str = "",
               requirements: str = "") -> str:
        upstream_body = (upstream or "").strip()[: self.upstream_chars] or "（无，你是第一个）"
        lines = []
        if self.spec.strip():
            lines.append(f"## 任务规格\n{self.spec.strip()}")
        lines += [
            f"## 你的角色\n你是「{role.name}」，职责：{role.duty}\n验收方式：{role.criteria}",
            f"## 当前阶段\n{stage}\n" + (FIRST if attempt <= 1 else RETRY.format(attempt=attempt)),
            f"## 上游交付\n```\n{upstream_body}\n```",
        ]
        if requirements.strip():
            lines.append(f"## 本阶段的验收要求（逐条满足，判据按它判）\n{requirements.strip()}")
        if feedback.strip():
            lines.append(f"## 上次被拒的原因（重做时必须逐条修掉）\n{feedback.strip()}")
        lines.append("## 引用规范\n"
                     "正文里的每条外部事实都要带引用编号，形如 [S1]，编号只能用上游给出的；"
                     "没有对应证据的地方，不许写「最新」「近期」这类时间判断，也不许自己编日期。")
        lines.append("只写这一阶段的交付物本身，不要解释你在做什么，不要复述要求。")
        return "\n\n".join(lines)