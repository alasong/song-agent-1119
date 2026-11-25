"""sa2_live 的单元测试：检索语句整形、工具能力表、手、证据块。

被测实现：scripts/sa2_live.py。scripts/ 没有 __init__.py，按文件路径加载，
做法与 tests/test_sa2_hand_fallback.py 相同。全程不触网：llm 与
`sa2_live.fetch.search` 都由测试提供假对象。
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_MODULE_PATH = ROOT / "scripts" / "sa2_live.py"

# 按路径加载：与工作目录、sys.path 顺序无关。加载只执行模块级 import 与常量定义，
# 不发网络请求、不写文件。
_spec = importlib.util.spec_from_file_location("sa2_live_units_under_test", _MODULE_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover - 路径写死不会走到
    raise ImportError(f"无法按路径加载 {_MODULE_PATH}")
sa2_live = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = sa2_live
_spec.loader.exec_module(sa2_live)

from sa2 import fetch                                    # noqa: E402
from sa2.core.evidence import EvidenceBook, stamp        # noqa: E402


class _Role:
    """角色只需要 duty（写检索意图）与 tools（挂了哪几件手）。"""

    def __init__(self, tools=()):
        self.duty = "找相关工作"
        self.tools = tools


class _FakeLLM:
    """记录调用形状的假 llm：`llm(messages, max_tokens=...)`。"""

    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[tuple] = []

    def __call__(self, messages, max_tokens: int = 1200):
        self.calls.append((messages, max_tokens))
        return self.reply


class SourceQueryTest(unittest.TestCase):
    """`_source_query`：按源的 query_style 决定保不保留 `all:"..."` 形态。"""

    def _call(self, source: str, reply: str) -> tuple[str, _FakeLLM]:
        llm = _FakeLLM(reply)
        return sa2_live._source_query(llm, "写一份方案", _Role(), source), llm

    # arXiv 是 field-prefixed：模型已经给出 all:"..."，原样保留。
    def test_arxiv_keeps_field_prefix_when_model_returns_it(self):
        out, _ = self._call("arxiv", 'all:"recursive self improvement"')
        self.assertEqual(out, 'all:"recursive self improvement"')

    # arXiv：模型只给裸短语，补成 all:"..."；否则 Atom 接口会把它拆成多个词。
    def test_arxiv_wraps_plain_phrase(self):
        out, _ = self._call("arxiv", "recursive self improvement")
        self.assertEqual(out, 'all:"recursive self improvement"')

    # HN 是 plain：字段前缀会被当成关键词的一部分，剥掉它。
    # 读实现：第 96 行 `re.sub(r"\s*[A-Za-z]+:", " ", query)` 只删前缀，
    # 模型自带的引号不动——所以结果保留了引号，这是当前实现的事实。
    def test_hn_strips_field_prefix(self):
        out, _ = self._call("hn", 'all:"agent eval"')
        self.assertEqual(out, '"agent eval"')
        self.assertNotIn("all:", out)

    # 纯中文剥成 ASCII 后为空：当场报 FetchError，不硬查一个必然零命中的查询。
    def test_pure_chinese_raises_fetch_error(self):
        with self.assertRaises(fetch.FetchError):
            self._call("arxiv", "递归自我改进方案")

    # 调用形状：位置参数 messages + 关键字 max_tokens=80（第 87 行）。
    def test_llm_call_shape(self):
        _, llm = self._call("arxiv", "recursive self improvement")
        self.assertEqual(len(llm.calls), 1)
        messages, max_tokens = llm.calls[0]
        self.assertIsInstance(messages, list)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "user")
        self.assertIsInstance(messages[0]["content"], str)
        # 提示词带上了目标与角色职责（读实现第 84–86 行）。
        self.assertIn("写一份方案", messages[0]["content"])
        self.assertIn("找相关工作", messages[0]["content"])
        self.assertEqual(max_tokens, 80)


class _FakeStore:
    """`_tool_caps` 只用到 store.all()。"""

    def all(self):
        return {"t1": {"capability": "checker"}}


class ToolCapsTest(unittest.TestCase):
    def test_known_tool_and_every_fetch_source_are_listed(self):
        caps = sa2_live._tool_caps(_FakeStore())
        self.assertEqual(caps["t1"], "checker")
        for name in fetch.source_names():
            key = f"fetch:{name}"
            self.assertIn(key, caps)
            self.assertEqual(caps[key], fetch.config(name)["capability"])
        # 显式钉住一个非默认标签：crossref 是检索源，不是取数源。
        self.assertEqual(caps["fetch:crossref"], "search")


class MakeHandTest(unittest.TestCase):
    """`make_hand`：每个源每轮只取一次，取回内容走真实 record 入台账。"""

    _ENTRIES = [
        {"title": "T1", "published": "2024-01-02",
         "url": "https://example.org/a", "summary": "摘要 A"},
        {"title": "T2", "published": "2024-02-03",
         "url": "https://example.org/b", "summary": "摘要 B"},
    ]

    def test_each_source_fetched_once_per_round_and_hand_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = EvidenceBook(root / "evidence.jsonl")
            calls: list[tuple] = []

            def fake_search(source: str, query: str, n: int = 5) -> list[dict]:
                calls.append((source, query, n))
                # 两个源返回同一批条目：内容寻址的账本按 digest 去重，
                # 同一份材料不会因为多跑一件手就变成两条证据。
                return [dict(entry) for entry in self._ENTRIES]

            llm = _FakeLLM("agent evaluation")
            hand = sa2_live.make_hand(llm, "写一份方案", book, root / "content")
            role = _Role(("fetch:arxiv", "fetch:hn"))

            with mock.patch.object(sa2_live.fetch, "search", fake_search):
                first = hand(role, "阶段一")

                # 两个源各查一次，顺序与 role.tools 一致（search 拿到的是源名）。
                self.assertEqual([c[0] for c in calls], ["arxiv", "hn"])
                self.assertEqual(len(calls), 2)
                # 每源每轮只让模型写一次查询。
                self.assertEqual(len(llm.calls), 2)
                self.assertEqual(first, "", "素材由 evidence_block 统一给，手不返回文本")
                rows = book.all()
                self.assertEqual(len(rows), 2)
                self.assertEqual({r.uri for r in rows},
                                 {"https://example.org/a", "https://example.org/b"})
                for row in rows:
                    self.assertTrue(Path(row.content_path).is_file(),
                                    "证据必须真的落盘")

                # 同一个 hand 再跑一轮：fetched 集合生效，不再查。
                second = hand(role, "阶段二")
                self.assertEqual(len(calls), 2, "每源每轮只取一次")
                self.assertEqual(len(llm.calls), 2)
                self.assertEqual(second, "")
                self.assertEqual(len(book.all()), 2, "重复派活不重复入账")


class EvidenceBlockTest(unittest.TestCase):
    """`evidence_block`：台账里的每条证据都要以 `[Sx] ... uri` 出现。"""

    def test_block_lists_every_evidence_id_and_uri(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = EvidenceBook(root / "evidence.jsonl")
            entries = [
                ("S1", "https://example.org/a", "标题 A"),
                ("S2", "https://example.org/b", "标题 B"),
            ]
            for evidence_id, uri, title in entries:
                content = f"{title}\n2024-01-02\n{uri}\n摘要句。"
                book.add(stamp(uri, content, "leader", evidence_id, root / "content"))

            text = sa2_live.evidence_block(book)
            for evidence_id, uri, _ in entries:
                self.assertIn(f"[{evidence_id}]", text)
                self.assertIn(uri, text)

    def test_empty_book_gives_empty_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = EvidenceBook(Path(tmp) / "evidence.jsonl")
            self.assertEqual(sa2_live.evidence_block(book), "")

class OrgCriteriaTest(unittest.TestCase):
    """造编制时“一条判据都没登记”要传 None，不能传空列表（否则模型写的门全判未登记）。"""

    def test_empty_registry_means_none(self):
        class EmptyJudge:
            def names(self):
                return []
        self.assertIsNone(sa2_live._org_criteria(EmptyJudge()))

    def test_names_pass_through(self):
        class Judge:
            def names(self):
                return ["交付·章节", "交付·体量"]
        self.assertEqual(sa2_live._org_criteria(Judge()), ["交付·章节", "交付·体量"])

class HandForProfileTest(unittest.TestCase):
    """annotation 档（evidence_min=0）没有引用义务，不该挂手出网。"""

    def args(self, evidence_min):
        from types import SimpleNamespace
        return SimpleNamespace(evidence_min=evidence_min)

    def test_annotation_profile_has_no_hand(self):
        self.assertIsNone(sa2_live._hand_for(self.args(0), None, "目标", None, None))

    def test_citation_profile_gets_a_hand(self):
        sentinel = object()
        with mock.patch.object(sa2_live, "make_hand", return_value=sentinel):
            self.assertIs(sa2_live._hand_for(self.args(3), None, "目标", None, None), sentinel)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()