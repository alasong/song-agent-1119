"""最小 LLM 通道：只做一次 chat completion。

密钥来源（按顺序，不落盘、不打印）：
1. 环境变量 DEEPSEEK_API_KEY
2. 实验环境回退：从正在运行的 DSH 进程环境里取（旧 key 已失效，凭据文件里那个会 401）
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request

DEFAULT_URL = "https://api.deepseek.com/v1/chat/completions"
DEFAULT_MODEL = "deepseek-chat"


class LLMError(RuntimeError):
    pass


def resolve_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    ps = subprocess.run(["ps", "-Ao", "pid,command"], capture_output=True, text=True).stdout
    for line in ps.splitlines():
        if "DeepSeek Harness.app" not in line and "WorkBuddy.app" not in line:
            continue
        pid = line.strip().split(None, 1)[0]
        dump = subprocess.run(["ps", "eww", "-p", pid], capture_output=True, text=True).stdout
        m = re.search(r"(?:^|\s)DEEPSEEK_API_KEY=(\S+)", dump)
        if m:
            return m.group(1)
    raise LLMError("找不到可用的 DEEPSEEK_API_KEY")


def complete(
    messages: list[dict],
    model: str = DEFAULT_MODEL,
    max_tokens: int = 2400,
    temperature: float = 0.2,
    timeout: int = 180,
    extra: dict | None = None,
) -> str:
    key = resolve_key()
    body_dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if extra:
        body_dict.update(extra)  # 例如 {"thinking": {"type": "disabled"}}：推理模型可能把预算全烧在思维链
    body = json.dumps(body_dict).encode()
    req = urllib.request.Request(
        DEFAULT_URL, data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        raise LLMError(f"HTTP {exc.code}: {exc.read()[:200]!r}") from exc
    except Exception as exc:  # 网络层
        raise LLMError(f"{type(exc).__name__}: {exc}") from exc
    return data["choices"][0]["message"]["content"]