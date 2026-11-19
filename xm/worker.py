"""真模型角色：调度器把活派给角色，角色用模型产出内容并交接给下游。

与 stub 的区别：产物里有真实内容，且带上游 id，下游能读到上游写了什么。
"""
from __future__ import annotations

import json
import re
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

@dataclass
class VerifierWorker(RoleWorker):
    """验证角色：必须给出机器可读裁决。解析不出来一律按拒绝处理（fail-closed）。"""

    def __call__(self, role: dict, stage: str, upstream: dict | None) -> dict:
        subject = (upstream or {}).get("content", "")[:1500]
        prompt = f"""你是独立验证员，不参与生产，只判断上游交付是否达标。

验收标准：{role['criteria']}

待验证的上游交付：
```
{subject or '（无上游产物）'}
```

只返回一个 JSON，不要写任何解释：
{{"verdict":"pass" 或 "reject","reason":"不超过 50 字的理由"}}"""
        text = self.llm([{"role": "user", "content": prompt}]).strip()
        artifact = {
            "id": f"{stage}:{role['name']}",
            "upstream": (upstream or {}).get("id"),
            "stage": stage,
            "role": role["name"],
            "content": text,
        }
        self.log.append(artifact)
        match = re.search(r"\{.*\}", text, re.S)
        verdict, reason = "reject", "裁决不可解析"
        if match:
            try:
                data = json.loads(match.group(0))
                verdict = "pass" if data.get("verdict") == "pass" else "reject"
                reason = str(data.get("reason", ""))[:200]
            except json.JSONDecodeError:
                pass
        artifact.update({"verdict": verdict, "reason": reason})
        return artifact
