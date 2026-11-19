"""真模型角色：调度器把活派给角色，角色用模型产出内容并交接给下游。

与 stub 的区别：产物里有真实内容，且带上游 id，下游能读到上游写了什么。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

LLM = Callable[[list[dict]], str]


@dataclass
class RoleWorker:
    llm: LLM
    max_tokens: int = 700
    log: list[dict] | None = None

    def __post_init__(self):
        if self.log is None:
            self.log = []

    def __call__(self, role: dict, stage: str, upstream: dict | None) -> dict:
        upstream_text = (upstream or {}).get("content", "")[:1200]
        prompt = f"""你是「{role['name']}」，职责：{role['duty']}
验收方式：{role['criteria']}

当前阶段：{stage}
上游产物：
```
{upstream_text or '（无，你是第一个）'}
```

请产出这一阶段你要交付的内容：不超过 200 字，只写交付物本身，不要解释你在做什么。"""
        content = self.llm([{"role": "user", "content": prompt}]).strip()
        artifact = {
            "id": f"{stage}:{role['name']}",
            "upstream": (upstream or {}).get("id"),
            "stage": stage,
            "role": role["name"],
            "content": content,
        }
        self.log.append(artifact)
        return artifact