"""`_simplify_candidates` 的纯函数测试：只测零命中后的降级候选，绝不触网。

被测实现：scripts/sa2_live.py。本文件不调用 fetch.arxiv，也不 mock 它——
只把候选字符串拿出来断言。
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_MODULE_PATH = ROOT / "scripts" / "sa2_live.py"

# scripts/ 下没有 __init__.py：`scripts` 不是常规包，`import scripts.sa2_live`
# 只有在仓库根恰好位于 sys.path[0] 时才靠命名空间包侥幸成立。这里按文件路径加载，
# 让测试与调用时的工作目录、sys.path 顺序无关。加载只执行模块级 import 与常量定义，
# 不发网络请求、不写文件。
_spec = importlib.util.spec_from_file_location("sa2_live_under_test", _MODULE_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover - 路径写死不会走到
    raise ImportError(f"无法按路径加载 {_MODULE_PATH}")
sa2_live = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = sa2_live
_spec.loader.exec_module(sa2_live)

_simplify = sa2_live._simplify_candidates


def _quoted_words(candidate: str) -> list[str]:
    """取出候选引号内的词，用来数词数。"""
    return candidate.split('"')[1].split()


class SimplifyCandidatesTest(unittest.TestCase):
    """按任务书的 6 条契约 + 边界用例组织，一条契约一个方法。"""

    # 契约 1：入参是 all:"..." 短语或长布尔式，两种都能给出候选。
    def test_contract_1_phrase_and_boolean_forms(self):
        phrase = _simplify('all:"AI research automation planning"')
        boolean = _simplify("AI and latest research automation planning")
        self.assertEqual(phrase, boolean)
        for candidate in phrase:
            self.assertRegex(candidate, r'^all:"[^"]+"$')

    # 契约 2：按词数递减；四词短语 → 三词、两词。
    def test_contract_2_four_word_phrase_descending(self):
        out = _simplify('all:"AI research automation planning"')
        self.assertEqual(out, ['all:"AI research automation"', 'all:"AI research"'])
        counts = [len(_quoted_words(c)) for c in out]
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertEqual(counts, [3, 2])

    # 契约 3：候选不含入参本身（strip 后比较），也不重复。
    def test_contract_3_excludes_input_and_dedups(self):
        for query in (
            'all:"AI research automation planning"',
            '  all:"AI research automation planning"  ',
            "all:AI research automation planning",
            'all:"AI AI research planning"',
        ):
            with self.subTest(query=query):
                out = _simplify(query)
                self.assertNotIn(query.strip(), [c.strip() for c in out])
                self.assertEqual(len(out), len(set(out)))

    # 契约 4：短语只剩两词或更少 → 空表。
    def test_contract_4_two_or_fewer_words_returns_empty(self):
        self.assertEqual(_simplify('all:"AI research"'), [])
        self.assertEqual(_simplify('all:"AI"'), [])

    # 契约 5：非 ASCII 剥掉；剥完不足三词 → 空表。
    def test_contract_5_non_ascii_stripped(self):
        self.assertEqual(
            _simplify('all:"AI 研究 automation planning"'), ['all:"AI automation"'])
        self.assertEqual(_simplify('all:"研究 自动化"'), [])

    # 契约 6：布尔式取实词，丢掉 and/or/not/all/latest/recent。
    def test_contract_6_boolean_stopwords_dropped(self):
        out = _simplify("all:AI and latest research OR automation NOT planning")
        self.assertEqual(out, ['all:"AI research automation"', 'all:"AI research"'])
        self.assertEqual(_simplify("and or not all latest recent"), [])

    # 边界：空串与纯空白。
    def test_boundary_empty_query(self):
        self.assertEqual(_simplify(""), [])
        self.assertEqual(_simplify("   "), [])

    # 边界：引号内恰好两词，没有更松的一档。
    def test_boundary_two_word_quoted_phrase(self):
        self.assertEqual(_simplify('all:"large language"'), [])

    # 边界：全中文查询，ASCII 剥完为空。
    def test_boundary_all_chinese_query(self):
        self.assertEqual(_simplify("研究自动化"), [])
        self.assertEqual(_simplify('all:"自动化 科研 规划"'), [])

    # 已知缺陷（未改实现）：词正则 [A-Za-z][A-Za-z\-]+ 不吞数字，`GPT-4` 被切成
    # `GPT-`，候选里出现悬空连字符（如 all:"GPT- large"）。这里断言期望行为，
    # 用 expectedFailure 把缺陷标出来；实现修好后这条会变成 unexpected success，
    # 那时删掉 expectedFailure 即可。
    @unittest.expectedFailure
    def test_known_bug_hyphen_digit_tokenization(self):
        out = _simplify('all:"GPT-4 large language model"')
        for candidate in out:
            self.assertNotIn("- ", candidate, msg=f"悬空连字符：{candidate}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()