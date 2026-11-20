"""S4 演练用的作业：必须是模块级函数，worker 才能在另一个进程里 import 到它。"""
from __future__ import annotations

import time


def echo(text: str) -> str:
    return text


def slow(seconds: float, text: str) -> str:
    """睡够时间再返回——给「杀掉正在干活的 worker」留出窗口。"""
    time.sleep(float(seconds))
    return text


def boom(message: str = "boom") -> str:
    raise RuntimeError(message)


def llm_complete(messages, max_tokens: int = 1200, model: str = "deepseek-flash") -> dict:
    """worker 里真正调模型的作业：正文与 usage 一起回传。"""
    from .. import llm
    text, usage = llm.complete_usage(messages, model=model, max_tokens=int(max_tokens),
                                     extra={"thinking": {"type": "disabled"}})
    return {"text": text or "", "usage": usage or {}}


def fake_llm(messages, max_tokens: int = 1200) -> dict:
    """测试用：把最后一条消息原样回显，附一个可断言的 usage。"""
    last = (messages or [{}])[-1]
    return {"text": str(last.get("content") or ""), "usage": {"total_tokens": 7}}


def fail_llm(messages, max_tokens: int = 1200) -> dict:
    raise RuntimeError("模型通道断了")


def section_llm(messages, max_tokens: int = 1200) -> dict:
    """演示用：按提示词里的阶段名吐对应章节。走真 worker 进程，但不出网。"""
    text = str((messages or [{}])[-1].get("content") or "")
    if "起草" in text:
        body = "## 一、a\n## 二、b\n"
    else:
        body = "## 一、a\n## 二、b\n## 三、c\n"
    return {"text": body, "usage": {"total_tokens": 11}}