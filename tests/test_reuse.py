"""D4 知识过手：检索要真的进提示词，回写要只收过判据的结论。

「知识扩展」现在只证明取到了（G4），没证明用上了。这两个断言就是在补这一半：
- 检索出来的事实必须出现在角色提示词里；
- 没过判据的交付绝不能回写，否则底座变成垃圾桶。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xm import kb as kbmod


class RetrieveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kb = kbmod.KnowledgeBase(Path(self.tmp.name) / "kb.jsonl")
        self.kb.add("RLHF 用人类偏好训练奖励模型", "rl", ["https://arxiv.org/abs/1"], "arxiv")
        self.kb.add("知识图谱补全可以用图神经网络", "nlp", ["https://arxiv.org/abs/2"], "arxiv")

    def tearDown(self):
        self.tmp.cleanup()

    def test_relevant_fact_ranks_first(self):
        hits = self.kb.retrieve("奖励模型怎么训练", limit=2)
        self.assertTrue(hits)
        self.assertIn("RLHF", hits[0].claim)

    def test_unrelated_query_returns_nothing(self):
        self.assertEqual(self.kb.retrieve("烘焙面包的温度", limit=3), [])

    def test_limit_respected(self):
        self.assertLessEqual(len(self.kb.retrieve("arxiv 训练 模型 图", limit=1)), 1)


class PromptBlockTest(unittest.TestCase):
    def test_empty_gives_empty_string(self):
        self.assertEqual(kbmod.as_prompt_block([]), "", "没有事实就不要留一个空标题占位")

    def test_block_contains_key_and_source(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        kb = kbmod.KnowledgeBase(Path(tmp.name) / "kb.jsonl")
        fact = kb.add("缓存命中率可按前缀复用提升", "infra", ["https://x/1"], "cache-doc")
        block = kbmod.as_prompt_block([fact])
        self.assertIn(fact.key, block)
        self.assertIn("cache-doc", block)
        self.assertIn("[ref:", block)


class WritebackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kb = kbmod.KnowledgeBase(Path(self.tmp.name) / "kb.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_failed_delivery_is_not_written_back(self):
        before = self.kb.count()
        got = kbmod.writeback_if_passed(self.kb, False, "## 结论\n没过的内容", ["artifact:x"])
        self.assertIsNone(got)
        self.assertEqual(self.kb.count(), before, "没过判据的结论回写 = 把错的记成已验证")

    def test_passed_delivery_is_written_back_once(self):
        text = "## 一、结论\n组织只是在跨域时才值得组"
        first = kbmod.writeback_if_passed(self.kb, True, text, ["artifact:x", "check:y"])
        again = kbmod.writeback_if_passed(self.kb, True, text, ["artifact:x", "check:y"])
        self.assertIsNotNone(first)
        self.assertEqual(first.key, again.key, "同一结论重复回写必须去重")
        self.assertEqual(self.kb.count(), 1)
        self.assertIn("组织只是在跨域时才值得组", first.claim, "标题符号不该进事实内容")

    def test_writeback_requires_evidence(self):
        with self.assertRaises(kbmod.KnowledgeError):
            kbmod.writeback_if_passed(self.kb, True, "结论", [])


class SaTaskPromptTest(unittest.TestCase):
    """派活提示词必须真的带检索结果，而不是只存不用。"""

    def test_role_prompt_carries_facts(self):
        from xm import sa_task
        prompt = sa_task.role_prompt(
            spec="写一份文档", goal="RSI 怎么做", role={"name": "研究员", "duty": "查文献",
                                                    "criteria": "每条都有出处"},
            stage="调研", upstream=None,
            fact_block=kbmod.as_prompt_block([
                kbmod.Fact("RSI 依赖可验证的自我改进闭环", "rsi", ["https://x/3"], "arxiv")]),
        )
        self.assertIn("已验证事实", prompt)
        self.assertIn("自我改进闭环", prompt)


if __name__ == "__main__":
    unittest.main()