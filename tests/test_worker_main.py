"""worker 主循环（进程内直调）：认领 → 执行 → 写结果 → 记账 → 删租约。

`test_sa2_liveness` 用真进程池盖端到端；这里把 `worker_main` 放进线程里直调，
能确定性地打到「坏派单跳过」「结果已存在不重跑」「作业抛异常写失败结果」这三个分支——
它们以前只在子进程里跑，进程内探针看不到，改坏了也没有单测能抓住。
"""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from sa2.core.ledger import Ledger
from sa2.loop import workers


def dispatch(root: Path, dispatch_id: str, func: str, *args) -> None:
    (root / "dispatch").mkdir(parents=True, exist_ok=True)
    (root / "dispatch" / f"{dispatch_id}.json").write_text(json.dumps({
        "id": dispatch_id,
        "job": {"module": "sa2.loop.jobs", "func": func, "args": list(args),
                "kwargs": {}},
    }, ensure_ascii=False), encoding="utf-8")


class WorkerMainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.thread: threading.Thread | None = None

    def tearDown(self):
        (self.root / "stop").touch()
        if self.thread is not None:
            self.thread.join(timeout=10)
        self.tmp.cleanup()

    def start(self, name: str = "w1") -> threading.Thread:
        self.thread = threading.Thread(
            target=workers.worker_main,
            args=(str(self.root), name, 2.0, str(self.root / "ledger.jsonl")),
            daemon=True)
        self.thread.start()
        return self.thread

    def wait_result(self, dispatch_id: str, timeout: float = 10.0) -> dict:
        path = self.root / "result" / f"{dispatch_id}.json"
        deadline = time.time() + timeout
        while time.time() < deadline:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
            time.sleep(0.02)
        self.fail(f"派活 {dispatch_id} 没有结果")

    def kinds(self) -> list[str]:
        return Ledger(self.root / "ledger.jsonl").kinds()

    def test_runs_a_job_and_cleans_the_lease(self):
        dispatch(self.root, "j-ok", "echo", "你好")
        self.start()
        result = self.wait_result("j-ok")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["out"], "你好")
        self.assertEqual(result["worker"], "w1")
        self.assertIn("dispatch_leased", self.kinds())
        self.assertIn("dispatch_done", self.kinds())
        self.assertFalse((self.root / "lease" / "j-ok.json").exists(),
                         "干完要删租约，否则接管逻辑会看到假占用")

    def test_failed_job_writes_a_failure_result(self):
        dispatch(self.root, "j-bad", "boom", "炸了")
        self.start()
        result = self.wait_result("j-bad")
        self.assertFalse(result["ok"])
        self.assertIn("RuntimeError", result["error"])
        self.assertIn("dispatch_failed", self.kinds())

    def test_existing_result_is_not_rerun(self):
        dispatch(self.root, "j-done", "echo", "旧结果")
        (self.root / "result").mkdir(parents=True, exist_ok=True)
        (self.root / "result" / "j-done.json").write_text('{"ok": true}', encoding="utf-8")
        self.start()
        time.sleep(0.3)
        self.assertNotIn("dispatch_leased", self.kinds(), "已有结果就不许再认领")
        self.assertEqual((self.root / "result" / "j-done.json").read_text(encoding="utf-8"),
                         '{"ok": true}')

    def test_corrupt_dispatch_is_skipped_not_fatal(self):
        (self.root / "dispatch").mkdir(parents=True, exist_ok=True)
        (self.root / "dispatch" / "j-corrupt.json").write_text("{坏", encoding="utf-8")
        dispatch(self.root, "j-good", "echo", "继续")
        self.start()
        result = self.wait_result("j-good")
        self.assertEqual(result["out"], "继续", "一份坏派单不许拖住整个循环")

    def test_expired_lease_is_taken_over_and_recorded(self):
        """上一个持有者已死、租约过期：新 worker 要抢过来，并记 lease_expired + takeover。"""
        dispatch(self.root, "j-take", "echo", "接手")
        (self.root / "lease").mkdir(parents=True, exist_ok=True)
        (self.root / "lease" / "j-take.json").write_text(json.dumps({
            "worker": "w-dead", "pid": 999999, "expires_at": 1,
        }), encoding="utf-8")
        self.start("w2")
        result = self.wait_result("j-take")
        self.assertEqual(result["out"], "接手")
        self.assertIn("lease_expired", self.kinds())
        self.assertIn("takeover", self.kinds())

    def test_live_worker_keeps_its_lease_via_heartbeat(self):
        """心搏断了，第二个 worker 就会以为租约过期并抢走同一单——这里必须不抢。"""
        dispatch(self.root, "j-long", "slow", 1.0, "长活")
        self.start("w1")
        second = threading.Thread(
            target=workers.worker_main,
            args=(str(self.root), "w2", 0.3, str(self.root / "ledger.jsonl")),
            daemon=True)
        second.start()
        result = self.wait_result("j-long", timeout=15)
        (self.root / "stop").touch()
        second.join(timeout=10)
        self.assertEqual(result["out"], "长活")
        self.assertNotIn("takeover", self.kinds(), "活人还持有的租约不许被抢")

    def test_kill_holder_without_lease_returns_none(self):
        pool = workers.WorkerPool(self.root, Ledger(self.root / "p.jsonl"), workers=0)
        self.assertIsNone(pool.kill_holder("j-没有"))


if __name__ == "__main__":
    unittest.main()