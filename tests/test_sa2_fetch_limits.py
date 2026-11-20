"""sa2/fetch.py 的重试、上限与白名单：全部用 `transport=` 注入，不碰网络。

被测实现：sa2/fetch.py。对应机制注释在该文件第 6–9 行：网络层重试一次就停，
4xx 与解析失败不重试，失败就大声报。
"""
from __future__ import annotations

import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sa2 import fetch  # noqa: E402


class _CountingTransport:
    """记录每次调用的 transport；按给定异常/文本作答。"""

    def __init__(self, error=None, reply=""):
        self.calls: list[tuple[str, int]] = []
        self.error = error
        self.reply = reply

    def __call__(self, url: str, timeout: int):
        self.calls.append((url, timeout))
        if self.error is not None:
            raise self.error
        return self.reply


class RetryTest(unittest.TestCase):
    """网络层错误：失败 → 睡一下 → 再失败 → 报错，调用恰为 2 次。"""

    def _call_until_error(self, source: str, transport):
        with mock.patch.object(fetch, "RETRY_SLEEP", 0):  # 别让测试真等 2 秒
            with self.assertRaises(fetch.FetchError):
                fetch.fetch(source, "x", 2, transport=transport, timeout=1)

    def test_timeout_is_retried_exactly_once(self):
        transport = _CountingTransport(error=TimeoutError("timed out"))
        self._call_until_error("arxiv", transport)
        self.assertEqual(len(transport.calls), 2, "一次失败 + 一次重试就停")
        self.assertEqual([t for _, t in transport.calls], [1, 1])

    def test_http_429_is_retried_exactly_once(self):
        url_holder: list[str] = []

        def boom(url: str, timeout: int):
            url_holder.append(url)
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", None, None)

        with mock.patch.object(fetch, "RETRY_SLEEP", 0):
            with self.assertRaises(fetch.FetchError):
                fetch.fetch("arxiv", "x", 2, transport=boom, timeout=1)
        self.assertEqual(len(url_holder), 2, "429 也只重试一次，然后大声报")

    def test_parse_failure_is_final_and_not_retried(self):
        # HN 返回的不是 JSON：解析失败是定论，重试不会让接口变对（实现第 85–86 行）。
        transport = _CountingTransport(reply="this is not json")
        with mock.patch.object(fetch, "RETRY_SLEEP", 0):
            with self.assertRaises(fetch.FetchError):
                fetch.fetch("hn", "x", 2, transport=transport, timeout=1)
        self.assertEqual(len(transport.calls), 1, "解析失败不重试")


class QueryLimitTest(unittest.TestCase):
    def test_max_results_is_clamped_to_constant(self):
        url = fetch.query_url("x", 999)
        self.assertEqual(fetch.MAX_RESULTS, 50)
        self.assertIn("max_results=50", url)
        self.assertNotIn("999", url)


class WhitelistTest(unittest.TestCase):
    """`_check`：只走 https、host 必须在源配置里。"""

    def test_plain_http_is_refused(self):
        with self.assertRaises(fetch.FetchError):
            fetch._check("http://export.arxiv.org/x", "export.arxiv.org")

    def test_foreign_host_is_refused(self):
        with self.assertRaises(fetch.FetchError):
            fetch._check("https://evil.example/x", "export.arxiv.org")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()