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