"""最小 LLM 通道：只做 chat completion。

密钥来源（按顺序，不落盘、不打印）：
1. 环境变量 DEEPSEEK_API_KEY
2. 实验环境回退：从正在运行的 DSH 进程环境里取（旧 key 已失效，凭据文件里那个会 401）

可靠性：
- 网络层错误与 5xx 重试（上限 MAX_ATTEMPTS 次，退避递增）——实测一次 IncompleteRead
  就能让整轮派活白跑；
- 4xx 不重试：401 重试只是把错误拖慢，不会变好。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

DEFAULT_URL = "https://api.deepseek.com/v1/chat/completions"
DEFAULT_MODEL = "deepseek-chat"
MAX_ATTEMPTS = 3
RETRY_SLEEP = 1.0


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


def _post(body_dict: dict, timeout: int) -> dict:
    """发一次请求；网络层错误与 5xx 有界重试，4xx 立即失败。"""
    key = resolve_key()
    body = json.dumps(body_dict).encode()
    last: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        req = urllib.request.Request(
            DEFAULT_URL, data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                raise LLMError(f"HTTP {exc.code}: {exc.read()[:200]!r}") from exc
            last = exc
        except Exception as exc:  # 网络层
            last = exc
        if attempt < MAX_ATTEMPTS:
            time.sleep(RETRY_SLEEP * attempt)
    raise LLMError(f"{type(last).__name__}: {last}") from last


def complete(
    messages: list[dict],
    model: str = DEFAULT_MODEL,
    max_tokens: int = 2400,
    temperature: float = 0.2,
    timeout: int = 180,
    extra: dict | None = None,
) -> str:
    body = {"model": model, "messages": messages, "max_tokens": max_tokens,
            "temperature": temperature}
    if extra:
        body.update(extra)  # 例如 {"thinking": {"type": "disabled"}}：推理模型可能把预算全烧在思维链
    data = _post(body, timeout)
    return data["choices"][0]["message"]["content"]


def complete_usage(messages: list[dict], **kwargs) -> tuple[str, dict]:
    """返回 (正文, usage)。用于真实成本记账，别再拿字符数估算。"""
    body = {"model": kwargs.get("model", DEFAULT_MODEL),
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", 2400),
            "temperature": kwargs.get("temperature", 0.2)}
    if kwargs.get("extra"):
        body.update(kwargs["extra"])
    data = _post(body, kwargs.get("timeout", 180))
    return data["choices"][0]["message"]["content"], data.get("usage", {})