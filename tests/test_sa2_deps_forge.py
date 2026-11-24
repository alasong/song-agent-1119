"""W12：断言单由生成方 propose，必须过 core.deps.check 才准用。"""
import json
import unittest
from types import SimpleNamespace

from sa2.core import deps
from sa2.forge import deps as forge_deps


def plan(*stages):
    return SimpleNamespace(stages=[SimpleNamespace(name=s) for s in stages])


def item(verify="cmd:true"):
    return {"name": "抓取工具", "cls": "tool",
            "claim": "能取回至少 2 条真实记录", "verify": verify,
            "if_false": "换成 hn 源"}


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

    def test_bad_verify_is_rejected(self):
        payload = {"stages": {"起草": {"items": [item("跑一下看看")]}}}
        with self.assertRaises(deps.DepError) as caught:
            forge_deps.propose("目标", plan("起草"), llm_for(payload))
        self.assertIn("验法", str(caught.exception))


if __name__ == "__main__":
    unittest.main()