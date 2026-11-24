"""LLM 通道的重试边界：网络抖动要重试，认证失败不许重试（否则把 401 变成延迟）。"""
from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sa2 import llm


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def payload(text: str = "ok") -> bytes:
    return json.dumps({
        "choices": [{"message": {"content": text}}],
        "usage": {"completion_tokens": 1, "prompt_cache_hit_tokens": 0,
                  "prompt_cache_miss_tokens": 1},
    }).encode()


class RetryTest(unittest.TestCase):
    def setUp(self):
        self.key = mock.patch.object(llm, "resolve_key", return_value="sk-test")
        self.key.start()

    def tearDown(self):
        self.key.stop()

    def test_network_error_then_success(self):
        calls = {"n": 0}

        def flaky(req, timeout):
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionResetError("IncompleteRead(0 bytes read)")
            return FakeResponse(payload("成功"))

        with mock.patch.object(llm.urllib.request, "urlopen", side_effect=flaky), \
                mock.patch.object(llm.time, "sleep"):
            self.assertEqual(llm.complete([{"role": "user", "content": "hi"}]), "成功")
        self.assertEqual(calls["n"], 3)

    def test_gives_up_after_cap(self):
        with mock.patch.object(llm.urllib.request, "urlopen",
                               side_effect=ConnectionResetError("boom")) as op, \
                mock.patch.object(llm.time, "sleep"):
            with self.assertRaises(llm.LLMError):
                llm.complete([{"role": "user", "content": "hi"}])
        self.assertEqual(op.call_count, llm.MAX_ATTEMPTS, "重试必须有上限，不能无限等")

    def test_http_401_is_not_retried(self):
        import urllib.error
        err = urllib.error.HTTPError(llm.DEFAULT_URL, 401, "unauthorized", {},
                                     io.BytesIO(b'{"error":"bad key"}'))
        with mock.patch.object(llm.urllib.request, "urlopen", side_effect=err) as op, \
                mock.patch.object(llm.time, "sleep"):
            with self.assertRaises(llm.LLMError):
                llm.complete([{"role": "user", "content": "hi"}])
        self.assertEqual(op.call_count, 1, "401 重试只是把错误拖慢，不会变好")

    def test_usage_variant_also_retries(self):
        calls = {"n": 0}

        def flaky(req, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TimeoutError("timed out")
            return FakeResponse(payload("带用量"))

        with mock.patch.object(llm.urllib.request, "urlopen", side_effect=flaky), \
                mock.patch.object(llm.time, "sleep"):
            text, usage = llm.complete_usage([{"role": "user", "content": "hi"}])
        self.assertEqual(text, "带用量")
        self.assertEqual(usage["completion_tokens"], 1)

    def test_http_500_is_retried_then_succeeds(self):
        import urllib.error
        err = urllib.error.HTTPError(llm.DEFAULT_URL, 500, "server error", {},
                                     io.BytesIO(b"boom"))
        calls = {"n": 0}

        def flaky(req, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                raise err
            return FakeResponse(payload("成功"))

        with mock.patch.object(llm.urllib.request, "urlopen", side_effect=flaky), \
                mock.patch.object(llm.time, "sleep"):
            self.assertEqual(llm.complete([{"role": "user", "content": "hi"}]), "成功")
        self.assertEqual(calls["n"], 2, "5xx 要重试，且第二次成功就返回")


if __name__ == "__main__":
    unittest.main()