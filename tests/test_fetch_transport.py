"""取数的默认通道与便捷入口：真 urlopen 走一次（用假响应，不碰网络），hn 要透传。

`test_sa2_fetch` 盖的是注入 transport 的路径；这里补「默认通道」与 hn 便捷函数的转发，
否则线上那条路是唯一没人跑过的分支。
"""
import unittest
from unittest import mock

from sa2 import fetch


class FakeResponse:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._body


ATOM = """<feed><entry><id>https://arxiv.org/abs/2611.00001v1</id>
<title>  一篇  论文 </title><published>2026-11-18T00:00:00Z</published>
<summary>摘要</summary></entry></feed>"""

HN = '{"hits":[{"objectID":1,"title":"一条新闻","url":"https://example.org/x"}]}'


class DefaultTransportTest(unittest.TestCase):
    def test_default_transport_uses_urlopen_and_parses(self):
        with mock.patch("sa2.fetch.urllib.request.urlopen",
                        return_value=FakeResponse(ATOM)) as opened:
            entries = fetch.fetch("arxiv", "agent evaluation", 2)
        self.assertEqual(entries[0]["title"], "一篇 论文")
        url = opened.call_args[0][0]
        self.assertIn("max_results=2", url)
        self.assertIn("agent+evaluation", url)

    def test_hn_convenience_wrapper_forwards(self):
        with mock.patch("sa2.fetch.urllib.request.urlopen",
                        return_value=FakeResponse(HN)) as opened:
            entries = fetch.hn("agent", 1)
        self.assertEqual(entries[0]["id"], "hn-1")
        self.assertIn("query=agent", opened.call_args[0][0])


if __name__ == "__main__":
    unittest.main()