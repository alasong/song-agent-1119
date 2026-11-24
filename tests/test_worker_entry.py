"""worker 进程入口：参数不对要说用法，stop 文件在就立刻退出。

`python -m sa2.loop.worker` 是 WorkerPool 起子进程的唯一入口（workers.py 用同一命令）。
这里用真子进程跑它，因为「入口能被 python -m 找到并正确退出」本身就是要测的能力。
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_entry(*args, timeout: float = 30):
    return subprocess.run([sys.executable, "-m", "sa2.loop.worker", *args],
                          capture_output=True, text=True, cwd=str(ROOT), timeout=timeout)


class WorkerEntryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_wrong_argument_count_prints_usage(self):
        proc = run_entry(str(self.root), "w1")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("用法", proc.stderr)

    def test_exits_immediately_when_stop_file_exists(self):
        (self.root / "stop").touch()
        proc = run_entry(str(self.root), "w1", "1.0")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_ledger_path_is_accepted_as_fourth_argument(self):
        (self.root / "stop").touch()
        proc = run_entry(str(self.root), "w1", "1.0", str(self.root / "ledger.jsonl"))
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()