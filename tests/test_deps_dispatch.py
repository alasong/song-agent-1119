"""W6：断言三档验证分派——执行事实自验，方法质量交验证方，其余挂起。"""
import unittest

from sa2.core import deps


def item(cls="tool", verify="cmd:true"):
    return deps.Assertion("抓取工具", cls, "能取回至少 2 条真实记录", verify, "换成 hn 源")


class DispatchTest(unittest.TestCase):
    def test_cmd_success_is_verified(self):
        result = deps.dispatch(item(verify="cmd:true"))
        self.assertEqual(result["status"], "verified")

    def test_cmd_failure_is_falsified(self):
        self.assertEqual(deps.dispatch(item(verify="cmd:false"))["status"], "falsified")

    def test_path_exists_is_verified(self):
        result = deps.dispatch(item(verify="path:tests/test_deps.py"))
        self.assertEqual(result["status"], "verified")

    def test_path_missing_is_falsified(self):
        result = deps.dispatch(item(verify="path:tests/没有这个文件.py"))
        self.assertEqual(result["status"], "falsified")

    def test_method_without_verifier_is_pending(self):
        result = deps.dispatch(item(cls="method", verify="read:对抗样本"))
        self.assertEqual(result["status"], "pending")
        self.assertIn("独立验证方", result["why"])

    def test_method_with_verifier_uses_it(self):
        seen = []
        result = deps.dispatch(item(cls="method", verify="read:对抗样本"),
                               verifier=lambda it: seen.append(it.name) or True)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(seen, ["抓取工具"])

    def test_value_without_reader_is_pending(self):
        self.assertEqual(deps.dispatch(item(verify="value:x=1"))["status"], "pending")


if __name__ == "__main__":
    unittest.main()