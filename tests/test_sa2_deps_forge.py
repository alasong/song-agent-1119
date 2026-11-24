"""W12：断言单由生成方 propose，必须过 core.deps.check 才准用。"""
import json
import unittest
from types import SimpleNamespace

from sa2.core import deps
from sa2.forge import deps as forge_deps


def plan(*stages):
    return SimpleNamespace(stages=[SimpleNamespace(name=s) for s in stages])


def item(verify="cmd:true", supports=()):
    return {"name": "抓取工具", "cls": "tool",
            "claim": "能取回至少 2 条真实记录", "verify": verify,
            "if_false": "换成 hn 源", "supports": list(supports)}


def llm_for(payload):
    return lambda messages, max_tokens=1200: json.dumps(payload, ensure_ascii=False)


class ProposeTest(unittest.TestCase):
    def test_two_stages_are_parsed_and_valid(self):
        payload = {"stages": {"起草": {"items": [item()]},
                              "成稿": {"items": [item("path:tests/test_deps.py")]}}}
        notes = forge_deps.propose("目标", plan("起草", "成稿"), llm_for(payload))
        self.assertEqual(set(notes), {"起草", "成稿"})
        for note in notes.values():
            self.assertEqual(deps.check(note), [])

    def test_missing_stage_is_rejected(self):
        payload = {"stages": {"起草": {"items": [item()]}}}
        with self.assertRaises(deps.DepError):
            forge_deps.propose("目标", plan("起草", "成稿"), llm_for(payload))

    def test_no_json_is_rejected(self):
        with self.assertRaises(deps.DepError):
            forge_deps.propose("目标", plan("起草"), lambda m, max_tokens=0: "随便写写")

    def test_unknown_supports_rejected(self):
        payload = {"stages": {"起草": {"items": [item(supports=("没这份判据",))]}}}
        with self.assertRaises(deps.DepError) as caught:
            forge_deps.propose("目标", plan("起草"), llm_for(payload), criteria=("交付·引用",))
        self.assertIn("supports", str(caught.exception))

    def test_supports_in_criteria_passes(self):
        payload = {"stages": {"起草": {"items": [item(supports=("交付·引用",))]}}}
        notes = forge_deps.propose("目标", plan("起草"), llm_for(payload), criteria=("交付·引用",))
        self.assertEqual(notes["起草"].items[0].supports, ("交付·引用",))

    def test_bad_verify_is_rejected(self):
        payload = {"stages": {"起草": {"items": [item("跑一下看看")]}}}
        with self.assertRaises(deps.DepError) as caught:
            forge_deps.propose("目标", plan("起草"), llm_for(payload))
        self.assertIn("验法", str(caught.exception))

    def test_broken_json_is_rejected(self):
        with self.assertRaisesRegex(deps.DepError, "JSON 解析失败"):
            forge_deps.propose("目标", plan("起草"),
                               lambda m, max_tokens=0: "{这不是 JSON}")

    def test_stages_must_be_object(self):
        with self.assertRaisesRegex(deps.DepError, "缺 stages 对象"):
            forge_deps.propose("目标", plan("起草"),
                               lambda m, max_tokens=0: json.dumps({"stages": []}))


if __name__ == "__main__":
    unittest.main()