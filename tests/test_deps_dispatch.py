"""W6：断言三档验证分派——执行事实自验，方法质量交验证方，其余挂起。"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sa2.core import deps
from sa2.core.ledger import Ledger


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


class DispatchLedgerTest(unittest.TestCase):
    """验完要记账：指标（验真率、证伪率）靠这两条事件，pending 不许混进来。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = Ledger(Path(self.tmp.name) / "ledger.jsonl")

    def test_verified_is_recorded_with_stage_and_kind(self):
        deps.dispatch(item(verify="cmd:true"), ledger=self.ledger, stage="抓取")
        events = [e for e in self.ledger.read() if e["kind"] == "claim_verified"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"]["name"], "抓取工具")
        self.assertEqual(events[0]["payload"]["stage"], "抓取")
        self.assertEqual(events[0]["payload"]["verify_kind"], "cmd")

    def test_falsified_is_recorded(self):
        deps.dispatch(item(verify="cmd:false"), ledger=self.ledger)
        self.assertEqual(self.ledger.count("claim_falsified"), 1)
        self.assertEqual(self.ledger.count("claim_verified"), 0)

    def test_pending_is_not_recorded(self):
        deps.dispatch(item(verify="value:x=1"), ledger=self.ledger)
        self.assertEqual(self.ledger.count("claim_verified"), 0)
        self.assertEqual(self.ledger.count("claim_falsified"), 0)

    def test_command_timeout_is_falsified_not_hung(self):
        real_get = deps.config.get
        with mock.patch.object(deps.config, "get",
                               lambda key: 0.05 if key == "tool_timeout" else real_get(key)):
            result = deps.dispatch(item(verify="cmd:sleep 5"))
        self.assertEqual(result["status"], "falsified")
        self.assertIn("超时", result["detail"])


if __name__ == "__main__":
    unittest.main()