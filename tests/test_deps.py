"""W3：依赖断言单的机械校验 + 依赖环检测。"""
import unittest

from sa2.core import deps
from sa2.knowledge.loader import _DEPS_CLASSES, _validate_deps, KnowledgeError


def good() -> deps.DepNote:
    return deps.DepNote("stage-1", (
        deps.Assertion("抓取工具", "tool",
                       "能取回至少 2 条 arxiv 记录",
                       "cmd:python3 -c 'print(1)'", "换成 hn 源"),
        deps.Assertion("验证角色", "team",
                       "验证方与写手不是同一个进程",
                       "path:tests/test_deps.py", "起独立 worker"),
    ))


class TestDepsNote(unittest.TestCase):
    def test_good_note_passes(self):
        self.assertEqual(deps.check(good()), [])

    def test_empty_items_is_thinking_nothing(self):
        problems = deps.check(deps.DepNote("stage-1", ()))
        self.assertTrue(any("没有登记任何依赖" in p for p in problems), problems)

    def test_empty_step_rejected(self):
        note = deps.DepNote("", good().items)
        self.assertTrue(any("步骤名" in p for p in deps.check(note)))

    def test_bad_verify_prefix_rejected(self):
        item = deps.Assertion("工具", "tool", "能取回至少 2 条记录", "跑一下看看", "换源")
        problems = deps.check(deps.DepNote("s", (item,)))
        self.assertTrue(any("验法" in p for p in problems), problems)

    def test_unknown_class_rejected(self):
        item = deps.Assertion("人", "people", "这个人能按期交付结果", "cmd:x", "换人")
        problems = deps.check(deps.DepNote("s", (item,)))
        self.assertTrue(any("不在" in p for p in problems), problems)

    def test_short_claim_rejected(self):
        item = deps.Assertion("工具", "tool", "能用", "cmd:x", "换源")
        problems = deps.check(deps.DepNote("s", (item,)))
        self.assertTrue(any("断言太短" in p for p in problems), problems)

    def test_missing_if_false_rejected(self):
        item = deps.Assertion("工具", "tool", "能取回至少 2 条记录", "cmd:x", "")
        problems = deps.check(deps.DepNote("s", (item,)))
        self.assertTrue(any("若假" in p for p in problems), problems)

    def test_duplicate_name_rejected(self):
        item = good().items[0]
        problems = deps.check(deps.DepNote("s", (item, item)))
        self.assertTrue(any("重名" in p for p in problems), problems)

    def test_gap_must_point_to_item(self):
        note = deps.DepNote("s", good().items, ("不存在的依赖",))
        self.assertTrue(any("没有对应的依赖条目" in p for p in deps.check(note)))

    def test_classes_are_five_fixed(self):
        self.assertEqual(deps.classes(), _DEPS_CLASSES)


class TestAcyclic(unittest.TestCase):
    def test_dag_has_no_cycle(self):
        self.assertEqual(deps.acyclic([("a", "b"), ("b", "c"), ("a", "c")]), [])

    def test_cycle_is_reported(self):
        cycle = deps.acyclic([("a", "b"), ("b", "a")])
        self.assertEqual(cycle[0], cycle[-1])
        self.assertEqual(set(cycle), {"a", "b"})

    def test_self_loop_is_reported(self):
        self.assertEqual(deps.acyclic([("a", "a")]), ["a", "a"])


class TestDepsKnowledge(unittest.TestCase):
    def test_sixth_class_needs_human(self):
        data = {"classes": {name: {"label": name, "why": name, "sub": []}
                            for name in _DEPS_CLASSES + ("money",)}}
        with self.assertRaises(KnowledgeError):
            _validate_deps("deps", data)


class MissedTest(unittest.TestCase):
    """漏报按 supports 归因：与依赖无关的交付失败不罚。"""

    def note(self, supports):
        item = deps.Assertion("抓取工具", "tool", "能取回至少 2 条记录",
                              "cmd:true", "换源", supports=supports)
        return deps.DepNote("s", (item,))

    def test_supports_failed_criterion_is_missed(self):
        self.assertEqual(deps.missed(self.note(("交付·引用",)), ["交付·引用: 0 条 < 3"]),
                         ["抓取工具"])

    def test_unrelated_failure_is_not_missed(self):
        self.assertEqual(deps.missed(self.note(("交付·引用",)), ["交付·体量: 700 < 1200"]), [])

    def test_no_supports_means_no_penalty(self):
        self.assertEqual(deps.missed(self.note(()), ["交付·引用: 0 条 < 3"]), [])

    def test_chinese_colon_prefix_also_works(self):
        self.assertEqual(deps.missed(self.note(("证据门",)), ["证据门：不可定位"]), ["抓取工具"])


class TestDepsParse(unittest.TestCase):
    """parse 是模型输出进系统的唯一入口：形状不对要当场抛，不能带着半张单往下走。"""

    def base(self) -> dict:
        return {"step": "抓取", "items": [{
            "name": "抓取工具", "cls": "tool", "claim": "能取回至少 2 条记录",
            "verify": "cmd:true", "if_false": "换源"}]}

    def test_non_object_is_refused(self):
        with self.assertRaisesRegex(deps.DepError, "必须是对象"):
            deps.parse(["不是 dict"])

    def test_items_must_be_list(self):
        with self.assertRaisesRegex(deps.DepError, "缺 items"):
            deps.parse({"step": "抓取", "items": "抓取工具"})

    def test_item_must_be_object(self):
        payload = self.base()
        payload["items"] = ["抓取工具"]
        with self.assertRaisesRegex(deps.DepError, "第 1 条依赖必须是对象"):
            deps.parse(payload)

    def test_item_missing_field_names_the_field(self):
        payload = self.base()
        payload["items"][0].pop("if_false")
        with self.assertRaisesRegex(deps.DepError, "缺字段"):
            deps.parse(payload)

    def test_supports_must_be_list(self):
        payload = self.base()
        payload["items"][0]["supports"] = "交付·引用"
        with self.assertRaisesRegex(deps.DepError, "supports 必须是数组"):
            deps.parse(payload)

    def test_gaps_must_be_list(self):
        payload = self.base()
        payload["gaps"] = "缺一个抓取工具"
        with self.assertRaisesRegex(deps.DepError, "gaps 必须是数组"):
            deps.parse(payload)

    def test_parse_strips_and_drops_empty_supports(self):
        payload = self.base()
        payload["items"][0]["supports"] = ["  交付·引用 ", ""]
        note = deps.parse(payload)
        self.assertEqual(note.step, "抓取")
        self.assertEqual(note.items[0].name, "抓取工具")
        self.assertEqual(note.items[0].supports, ("交付·引用",))


if __name__ == "__main__":
    unittest.main()