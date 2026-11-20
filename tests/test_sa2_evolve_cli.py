"""`scripts/evolve.py` 的黑盒 CLI 测试：经验够不够格、写不写候选、门槛是否真来自参数。

只新增测试，不改实现；所有写操作落在 `tempfile.TemporaryDirectory()`；不碰网络；
每个子进程都显式传 `XM_SA2_REGISTRY`，绝不读写真实 `~/xm-runs`。

与题面的对应关系：
  T1 不够格（1 条 injected=1, ok=0，--min-rate 0.8）→ rc=0、stdout「够格候选 0 条」、
     candidates.jsonl 不存在（这一条按实现现状**会红**，见方法内注释）
  T2 够格（2 条同 when，stats 都是 2/2）→ candidates.jsonl 恰 1 行，
     status=="proposed"、proposal.kind=="prompt_note"、support==2
  T3 --dry-run → stdout 有 dry-run、candidates.jsonl 不存在
  T4 幂等 → 同一数据连跑两次，candidates.jsonl 仍 1 行
  T5 门槛可调 → 同一条 0/1 经验在 --min-rate 0 --min-support 1 下出候选，
     默认参数（min-support=2）下不出

行为来源（读实现确认，不是按印象写）：
  - `scripts/evolve.py:23-43`：默认 `min-support=2`、`min-rate=0.8`；`--dry-run` 在写之前
    return；非 dry-run 一律 `evolution.write(registry.candidates_path(), found)`。
  - `sa2/memory/registry.py:15-17,37-43`：`XM_SA2_REGISTRY` 整体换掉 registry 根目录，
    `lessons.jsonl` / `candidates.jsonl` 都在它下面（`ensure()` 会建目录）。
  - `sa2/memory/lessons.py:52-73`：一条经验的字段与 stats 初值（injected/ok/bad 全 0），
    所以夹具先用 `lessons.add()` 造行、再回写 stats——字段不会跟生产形态漂移。
  - `sa2/memory/evolution.py:23-53`：够格判据是「同 when 条数 ≥ min_support、
    injected 合计 > 0、平均成功率 ≥ min_rate」；`write()` 以追加模式打开，
    按 (when, ids) 去重。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sa2.memory import lessons

# 仓库根：子进程里用相对脚本路径 "scripts/evolve.py"，所以 cwd 必须是仓库根。
REPO = Path(__file__).resolve().parents[1]
# vocab.json 里登记过的条件（sa2/knowledge/data/vocab.json 的 events.failure_kind）；
# 不许现编 when，否则 lessons.add 会抛 LessonError。
WHEN = {"failure_kind": "missing_heading"}


def run_evolve(registry: Path, *args: str) -> subprocess.CompletedProcess:
    """在仓库根跑一次 CLI；registry 由参数显式给出，不落默认 ~/xm-runs。"""
    env = {**os.environ, "XM_SA2_REGISTRY": str(registry)}
    return subprocess.run(
        [sys.executable, "scripts/evolve.py", *args],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=120,
    )


def seed_lessons(registry: Path, texts: list[str], stats: dict) -> list[dict]:
    """用 lessons.add 造经验（字段与生产一致），再把这些行的 stats 回写成指定值。"""
    path = registry / "lessons.jsonl"
    for text in texts:
        lessons.add(path, text=text, when=dict(WHEN), fix="补上缺的小节",
                    origin="unittest")
    rows = lessons.all(path)
    for row in rows:
        row["stats"] = dict(stats)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")
    return rows


def candidate_rows(registry: Path) -> list[dict]:
    """读候选文件；文件不存在时当 0 行（T5 默认参数下实现会建空文件，见 T1 注释）。"""
    path = registry / "candidates.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


class EvolveCliTest(unittest.TestCase):
    """五条 CLI 行为，每条一个方法。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.registry = self.tmp / "registry"

    def tearDown(self):
        self._tmp.cleanup()

    def test_t1_not_qualified_writes_no_candidate_file(self):
        """经验不够格时，不该产生候选文件。"""
        seed_lessons(self.registry, ["同类经验甲"], {"injected": 1, "ok": 0, "bad": 0})

        proc = run_evolve(self.registry, "--min-rate", "0.8")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("够格候选 0 条", proc.stdout)

        # 【预期会红——记录的实现 bug，不改实现】
        # scripts/evolve.py:38 无条件调用 evolution.write()，而 write() 以追加模式
        # open()（sa2/memory/evolution.py:72），即使 found=[] 也会建出一个 0 字节的
        # candidates.jsonl。需求是「没有够格经验时不写文件」，所以这里按需求断言；
        # 要修应该让 evolution.write() 在 found 为空时直接返回、不碰文件。
        self.assertFalse((self.registry / "candidates.jsonl").exists(),
                         "不够格时不该创建 candidates.jsonl（见本方法注释的实现 bug）")

    def test_t2_qualified_lessons_write_one_candidate(self):
        """够格时恰好写一条 proposed 的 prompt_note 候选。"""
        seed_lessons(self.registry, ["同类经验甲", "同类经验乙"],
                     {"injected": 2, "ok": 2, "bad": 0})

        proc = run_evolve(self.registry, "--min-rate", "0.8")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("够格候选 1 条", proc.stdout)
        # 写落点必须是我们显式指定的临时 registry（证明 XM_SA2_REGISTRY 真被读到）
        self.assertIn(str(self.registry), proc.stdout)
        lines = [line for line in
                 (self.registry / "candidates.jsonl").read_text(encoding="utf-8").splitlines()
                 if line.strip()]
        self.assertEqual(len(lines), 1, lines)
        row = json.loads(lines[0])
        self.assertEqual(row["status"], "proposed")
        self.assertEqual(row["proposal"]["kind"], "prompt_note")
        self.assertEqual(row["support"], 2)

    def test_t3_dry_run_writes_nothing(self):
        """--dry-run 只打印，不落候选文件。"""
        seed_lessons(self.registry, ["同类经验甲", "同类经验乙"],
                     {"injected": 2, "ok": 2, "bad": 0})

        proc = run_evolve(self.registry, "--min-rate", "0.8", "--dry-run")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("dry-run", proc.stdout)
        self.assertFalse((self.registry / "candidates.jsonl").exists())

    def test_t4_second_run_is_idempotent(self):
        """同一数据连跑两次，候选不重复追加。"""
        seed_lessons(self.registry, ["同类经验甲", "同类经验乙"],
                     {"injected": 2, "ok": 2, "bad": 0})

        first = run_evolve(self.registry, "--min-rate", "0.8")
        self.assertEqual(first.returncode, 0, first.stderr)
        second = run_evolve(self.registry, "--min-rate", "0.8")
        self.assertEqual(second.returncode, 0, second.stderr)

        self.assertIn("新写入候选 0 条", second.stdout)
        self.assertEqual(len(candidate_rows(self.registry)), 1)

    def test_t5_thresholds_come_from_args(self):
        """同一条 0/1 经验：默认门槛不出候选，放宽参数后出候选。"""
        seed_lessons(self.registry, ["同类经验甲"], {"injected": 1, "ok": 0, "bad": 0})

        default = run_evolve(self.registry)      # 默认 min-support=2
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertIn("够格候选 0 条", default.stdout)
        self.assertEqual(candidate_rows(self.registry), [])

        loosened_registry = self.tmp / "registry-loosened"
        seed_lessons(loosened_registry, ["同类经验甲"],
                     {"injected": 1, "ok": 0, "bad": 0})
        loosened = run_evolve(loosened_registry, "--min-rate", "0", "--min-support", "1")
        self.assertEqual(loosened.returncode, 0, loosened.stderr)
        self.assertIn("够格候选 1 条", loosened.stdout)
        self.assertEqual(len(candidate_rows(loosened_registry)), 1)


if __name__ == "__main__":
    unittest.main()