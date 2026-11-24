"""worker 的防御分支：进程探测看不清就当活着、文件状态读不到就按坏租约处理、
日志读不出来仍要给出诊断、结不掉的进程要 kill。

这些分支平时不出现，一出现都发生在「进程死/盘坏/卡住」的时候——正是最需要
日志可读、租约可回收的时候，所以它们也得有能判红的用例。
"""
import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from sa2.core.ledger import Ledger
from sa2.loop import workers


class PidAliveTest(unittest.TestCase):
    def test_permission_error_means_alive(self):
        with mock.patch.object(workers.os, "kill", side_effect=PermissionError):
            self.assertTrue(workers._pid_alive(1), "看不清就别抢别人的租约")

    def test_invalid_pid_means_alive(self):
        self.assertTrue(workers._pid_alive("不是数字"))

    def test_dead_pid_means_dead(self):
        self.assertFalse(workers._pid_alive(999999))


class ClaimFaultTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lease = Path(self.tmp.name) / "lease" / "j-1.json"
        self.lease.parent.mkdir(parents=True)

    def test_stat_failure_counts_as_long_broken(self):
        """坏租约连 mtime 都读不到：不能再等宽限，否则这一单永远没人领。"""
        self.lease.write_text("", encoding="utf-8")
        real_stat = Path.stat
        lease = self.lease

        def fake_stat(self, *args, **kw):
            if self == lease:
                raise OSError("盘坏")
            return real_stat(self, *args, **kw)

        with mock.patch.object(Path, "stat", fake_stat):
            self.assertEqual(workers._claim(self.lease, "w1", 1, ttl=1.0), {})
        self.assertEqual(workers._read(self.lease)["worker"], "w1")


class HeartbeatFaultTest(unittest.TestCase):
    def test_heartbeat_stops_when_lease_belongs_to_someone_else(self):
        with tempfile.TemporaryDirectory() as tmp:
            lease = Path(tmp) / "j.json"
            workers._write(lease, {"worker": "别人", "pid": 1, "expires_at": 0})
            stop = threading.Event()
            beat = workers._heartbeat(lease, "w1", 0.06, stop)
            beat.join(timeout=2)
            stop.set()
            self.assertFalse(beat.is_alive(), "看到别人持有就退出，不许替别人续租")


class PoolFaultTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ledger = Ledger(self.root / "ledger.jsonl")
        self.pool = workers.WorkerPool(self.root, self.ledger, workers=0)

    def test_wait_lease_times_out_with_none(self):
        self.assertIsNone(self.pool.wait_lease("j-没有", timeout=0.05))

    def test_diagnose_survives_unreadable_log(self):
        (self.root / "worker-w1.log").write_text("上一行\n", encoding="utf-8")
        with mock.patch.object(Path, "read_text", side_effect=OSError("读不了")):
            message = self.pool._diagnose("j-x")
        self.assertIn("派单存在=False", message)
        self.assertNotIn("日志尾", message)

    def test_kill_holder_without_matching_process_returns_none(self):
        workers._write(self.root / "lease" / "j-1.json",
                       {"worker": "w9", "pid": 424242, "expires_at": 0})
        self.assertIsNone(self.pool.kill_holder("j-1"))

    def test_kill_holder_tolerates_stubborn_process(self):
        class Stubborn:
            pid = 424242

            def __init__(self):
                self.killed = False

            def kill(self):
                self.killed = True

            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired(cmd="w", timeout=timeout)

        proc = Stubborn()
        self.pool._procs = {"w1": proc}
        workers._write(self.root / "lease" / "j-2.json",
                       {"worker": "w1", "pid": 424242, "expires_at": 0})
        self.assertEqual(self.pool.kill_holder("j-2"), "w1")
        self.assertTrue(proc.killed)
        self.assertEqual(self.ledger.count("worker_killed"), 1)

    def test_stop_escalates_when_terminate_does_not_land(self):
        class Slow:
            pid = 1

            def __init__(self):
                self.killed = False

            def poll(self):
                return None

            def terminate(self):
                pass

            def wait(self, timeout=None):
                if not self.killed:
                    raise subprocess.TimeoutExpired(cmd="w", timeout=timeout)
                return 0

            def kill(self):
                self.killed = True

        proc = Slow()
        self.pool._procs = {"w1": proc}
        self.pool.stop()
        self.assertTrue(proc.killed, "terminate 不落地就要 kill")
        self.assertEqual(self.pool._procs, {})


class WorkerMainFaultTest(unittest.TestCase):
    def test_missing_lease_file_on_cleanup_is_not_fatal(self):
        """心跳把租约删掉/别人抢走后 unlink 失败，不许把整个 worker 带走。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "dispatch").mkdir(parents=True)
            (root / "dispatch" / "j-1.json").write_text(json.dumps({
                "id": "j-1", "job": {"module": "sa2.loop.jobs", "func": "echo",
                                     "args": ["好"], "kwargs": {}}}), encoding="utf-8")
            errors: list[str] = []

            def run():
                try:
                    with mock.patch.object(Path, "unlink", side_effect=FileNotFoundError):
                        workers.worker_main(str(root), "w1", 2.0, str(root / "ledger.jsonl"))
                except BaseException as exc:  # 线程里的异常要带回主线程断言
                    errors.append(repr(exc))

            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            result = root / "result" / "j-1.json"
            deadline = time.time() + 10
            while time.time() < deadline and not result.exists():
                time.sleep(0.02)
            (root / "stop").touch()
            thread.join(timeout=10)
            self.assertEqual(errors, [])
            self.assertTrue(result.exists())
            self.assertEqual(json.loads(result.read_text(encoding="utf-8"))["out"], "好")


if __name__ == "__main__":
    unittest.main()