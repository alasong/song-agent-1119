"""工单状态机的拒收面：重复声明、不存在的工单、处理器崩溃、校验超时。

`test_harness` 盖的是「声称 passed 推不动状态」等四条主判红；这里补的是
外壳边界——崩溃必须记 reject 再抛（不许静默推进），超时按 rc=124 记账，
相对路径的产物按 harness 根目录解析。
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sa2.core import harness as hs
from sa2.core.harness import ARTIFACT, Harness, HarnessRefused


class HarnessEdgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.h = Harness(self.root)
        (self.root / "down.md").write_text("结论：可判。\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def running(self, item="w1", verify="true", handler=None):
        self.h.register("document", handler=handler, verify_cmd=verify)
        self.h.declare(task_type="document", criteria=["有结论"], item_id=item)
        self.h.advance(item, "routed")
        self.h.advance(item, "running")
        return item

    def test_duplicate_item_id_is_refused(self):
        self.h.register("document", verify_cmd="true")
        self.h.declare(task_type="document", criteria=["有结论"], item_id="w1")
        with self.assertRaisesRegex(HarnessRefused, "工单已存在"):
            self.h.declare(task_type="document", criteria=["有结论"], item_id="w1")

    def test_advance_unknown_item_is_refused(self):
        with self.assertRaisesRegex(HarnessRefused, "没有这张工单"):
            self.h.advance("w-none", "routed")

    def test_state_and_history_of_unknown_item(self):
        self.assertIsNone(self.h.state("w-none"))
        self.assertEqual(self.h.history("w-none"), [])
        self.assertEqual(self.h.items(), [])

    def test_declared_items_are_listed(self):
        self.running("w1")
        self.running("w2")
        self.assertEqual(sorted(self.h.items()), ["w1", "w2"])

    def test_handler_crash_is_recorded_and_refused(self):
        def boom(item, to):
            raise ValueError("取回失败")

        self.h.register("document", handler=boom, verify_cmd="true")
        self.h.declare(task_type="document", criteria=["有结论"], item_id="w1")
        with self.assertRaisesRegex(HarnessRefused, "处理器异常"):
            self.h.advance("w1", "routed")
        self.assertEqual(self.h.state("w1"), "declared", "崩了不许前进")
        rejects = [e for e in self.h.ledger.read() if e["kind"] == "reject"]
        self.assertEqual(len(rejects), 1)
        self.assertIn("处理器异常", rejects[0]["payload"]["reason"])
        self.assertEqual([e for e in self.h.ledger.read() if e["kind"] == "advance"], [])

    def test_relative_artifact_is_resolved_against_root(self):
        item = self.running()
        self.h.advance(item, "checked", artifacts={ARTIFACT: "down.md"})
        self.assertEqual(self.h.state(item), "checked")

    def test_missing_artifact_file_is_refused(self):
        item = self.running()
        with self.assertRaisesRegex(HarnessRefused, "证据不全"):
            self.h.advance(item, "checked", artifacts={ARTIFACT: "没有这个文件.md"})
        self.assertEqual(self.h.state(item), "running")

    def test_verify_timeout_is_recorded_as_rc_124(self):
        item = self.running(verify="sleep 5")
        self.h.advance(item, "checked", artifacts={ARTIFACT: "down.md"})
        with mock.patch.object(hs, "VERIFY_TIMEOUT", 0.3):
            with self.assertRaisesRegex(HarnessRefused, "rc=124"):
                self.h.advance(item, "done")
        verify = [e for e in self.h.ledger.read() if e["kind"] == "verify"]
        self.assertEqual(verify[-1]["payload"]["rc"], 124)
        self.assertIn("超时", verify[-1]["payload"]["tail"])


if __name__ == "__main__":
    unittest.main()