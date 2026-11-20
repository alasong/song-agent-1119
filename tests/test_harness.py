"""M5：WorkItem 状态机 —— 一台所有活都能挂上来的 harness。

四条判红：
- 处理器声称 passed 推不动状态（判定权不在生成方）；
- 类型没注册校验命令，不许结项；
- 校验命令非零，拒绝结项且必须走 failed 边；
- 半路崩了从账本重放续跑，已走过的边不重跑。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sa2.core.harness import ARTIFACT, Harness, HarnessRefused


class HarnessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.h = Harness(self.root)
        self.art = self.root / "down.md"
        self.art.write_text("结论：可判。\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _walk(self, item_id="w1", task_type="document", verify="true"):
        self.h.register(task_type, handler=lambda item, to: {"passed": True},
                        verify_cmd=verify)
        self.h.declare(task_type=task_type, criteria=["有结论"], item_id=item_id)
        for to in ("routed", "running"):
            self.h.advance(item_id, to)
        self.h.advance(item_id, "checked", artifacts={ARTIFACT: str(self.art)})
        return item_id

    def test_happy_path_reaches_done(self):
        item = self._walk()
        self.h.advance(item, "done")
        self.assertEqual(self.h.state(item), "done")
        walked = [e["payload"]["to"] for e in self.h.history(item)
                  if e["kind"] == "advance"]
        self.assertEqual(walked, ["routed", "running", "checked", "done"], "每条边恰好一次")

    def test_cheat_claim_cannot_advance(self):
        # 处理器每次都声称 passed：账本留痕，但对状态没有任何作用
        self.h.register("liar", handler=lambda item, to: {"passed": True}, verify_cmd=None)
        item = self.h.declare(task_type="liar", criteria=["有结论"], item_id="cheat")
        for to in ("routed", "running"):
            self.h.advance(item, to)
        with self.assertRaises(HarnessRefused):
            self.h.advance(item, "checked")           # 没交产物
        self.h.advance(item, "checked", artifacts={ARTIFACT: str(self.art)})
        with self.assertRaises(HarnessRefused):
            self.h.advance(item, "done")              # 类型没注册校验命令
        self.assertEqual(self.h.state(item), "checked", "状态一步都没多走")
        claims = [e for e in self.h.history(item) if e["kind"] == "claim"]
        self.assertTrue(claims, "声称必须留痕")
        self.assertTrue(all(c["payload"]["claim"].get("passed") for c in claims))

    def test_failing_verifier_blocks_done(self):
        item = self._walk(verify="false")
        with self.assertRaises(HarnessRefused):
            self.h.advance(item, "done")
        self.assertEqual(self.h.state(item), "checked")
        self.h.advance(item, "failed", artifacts={"reason": "校验命令返回非零"})
        self.assertEqual(self.h.state(item), "failed")
        with self.assertRaises(HarnessRefused):
            self.h.advance(item, "done")              # 结了就是结了
        self.assertEqual(self.h.state(item), "failed")

    def test_registered_criteria_cannot_be_swapped(self):
        self.h.register("document", verify_cmd="true")
        with self.assertRaises(HarnessRefused):
            self.h.register("document", verify_cmd="false")
        again = Harness(self.root)                       # 注册也进账本，重启后判据还在
        self.assertEqual(again.routes["document"].verify_cmd, "true")

    def test_unknown_type_refused_at_routing(self):
        self.h.declare(task_type="ghost", criteria=["x"], item_id="g1")
        with self.assertRaises(HarnessRefused):
            self.h.advance("g1", "routed")
        self.assertEqual(self.h.state("g1"), "declared")

    def test_resume_after_crash_does_not_rerun_edges(self):
        item = self._walk()
        del self.h                                      # 进程没了
        again = Harness(self.root)                      # 新进程：状态只能从账本重放
        self.assertEqual(again.state(item), "checked")
        with self.assertRaises(HarnessRefused):
            again.advance(item, "checked")               # 走过的边不存在，不会重跑
        again.advance(item, "done")
        self.assertEqual(again.state(item), "done")
        edges = [(e["payload"]["from"], e["payload"]["to"])
                 for e in again.history(item) if e["kind"] == "advance"]
        self.assertEqual(len(edges), len(set(edges)), f"同一条边走了两次：{edges}")


if __name__ == "__main__":
    unittest.main()