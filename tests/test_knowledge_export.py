"""knowledge_export 契约测试：筛选导出、幂等、空库不建文件、去重、默认种子路径。

只新增测试，不改实现；所有子进程都显式传 `XM_SA2_REGISTRY` 指向
`tempfile.TemporaryDirectory()`，绝不落 `~/xm-runs`，也不写仓库默认 seed 路径。

与题面的对应关系：
  T1 阈值筛选 + 计数措辞（print 原文）
  T2 幂等（同一命令再跑，不重复追加，新导出 0）
  T3 空库 / 全不够格：退出码 0、out 不创建、有提示
  T4 按 id 去重合并（out 里已有同 id 旧条目）
  T5 默认 --out 字符串落在仓库内 sa2/knowledge/seed（只读常量，不执行写盘）
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "knowledge_export.py"


def make_lesson(lesson_id: str, *, injected: int, ok: int, text: str = "") -> dict:
    """造一条最小可用的经验行；字段形状照 lessons.add() 的落盘结果。"""
    return {
        "id": lesson_id,
        "when": {"failure_kind": "criteria_rejected"},
        "text": text or f"经验正文 {lesson_id}",
        "fix": "补一条",
        "origin": "test",
        "stats": {"injected": injected, "ok": ok, "bad": 0},
        "status": "active",
        "ts": "2026-11-20T00:00:00",
    }


class KnowledgeExportTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp = Path(self._tmpdir.name)
        self.registry = self.tmp / "registry"
        self.registry.mkdir()
        self.lessons = self.registry / "lessons.jsonl"
        self.out = self.tmp / "out" / "lessons.jsonl"
        # 唯一的环境覆盖点：子进程只认这个临时 registry，不碰 ~/xm-runs。
        self.env = {**os.environ, "XM_SA2_REGISTRY": str(self.registry)}

    def write_lessons(self, rows: list[dict]) -> None:
        self.lessons.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )

    def run_export(self, min_injected: str = "2", min_rate: str = "0.8"):
        return subprocess.run(
            [sys.executable, str(SCRIPT),
             "--min-injected", min_injected,
             "--min-rate", min_rate,
             "--out", str(self.out)],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def read_out(self) -> list[dict]:
        return [json.loads(line) for line in
                self.out.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_threshold_filter_and_counts(self):
        """T1：只导出 injected>=2 且 rate>=0.8 的那条，计数措辞照源码 print。"""
        self.write_lessons([
            make_lesson("Lkeep", injected=3, ok=3),   # rate 1.0，够格
            make_lesson("Ldrop", injected=3, ok=0),   # rate 0.0，不够格
        ])
        proc = self.run_export()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(self.out.exists())
        rows = self.read_out()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "Lkeep")
        # 源码第 58 行原文：经验 N 条，够格 M 条，新导出 K 条 → path
        self.assertIn(f"经验 2 条，够格 1 条，新导出 1 条 → {self.out}", proc.stdout)
        # 源码第 59 行的固定 review 提示
        self.assertIn("这是给人 review 的", proc.stdout)

    def test_idempotent_second_run_adds_nothing(self):
        """T2：同一命令再跑一次，仍 1 行，且 stdout 显示新导出 0 条。"""
        self.write_lessons([make_lesson("Lkeep", injected=3, ok=3)])
        first = self.run_export()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(len(self.read_out()), 1)

        second = self.run_export()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(len(self.read_out()), 1, "第二次运行不应重复追加")
        self.assertIn(f"经验 1 条，够格 1 条，新导出 0 条 → {self.out}", second.stdout)

    def test_empty_registry_does_not_create_out(self):
        """T3a：lessons.jsonl 为空 → rc 0，不创建 out，stdout 有提示。"""
        self.lessons.write_text("", encoding="utf-8")
        proc = self.run_export()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(self.out.exists(), "没有够格条目时不应创建输出文件")
        self.assertIn(f"经验 0 条，够格 0 条：没有可导出的，不动 {self.out}", proc.stdout)

    def test_all_below_threshold_does_not_create_out(self):
        """T3b：所有条目都不够格 → rc 0，不创建 out。"""
        self.write_lessons([
            make_lesson("Lfew", injected=1, ok=1),    # injected < min-injected
            make_lesson("Lbad", injected=3, ok=1),    # rate 0.33 < min-rate
        ])
        proc = self.run_export()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(self.out.exists(), "全不够格时不应创建输出文件")
        self.assertIn(f"经验 2 条，够格 0 条：没有可导出的，不动 {self.out}", proc.stdout)

    def test_dedup_by_id_keeps_existing_row(self):
        """T4：out 已有同 id 旧条目 → 按 id 去重，仍 1 行且保留旧内容。"""
        self.write_lessons([make_lesson("Lkeep", injected=3, ok=3, text="新正文")])
        old = make_lesson("Lkeep", injected=3, ok=3, text="旧正文")
        self.out.parent.mkdir(parents=True)
        self.out.write_text(json.dumps(old, ensure_ascii=False) + "\n", encoding="utf-8")

        proc = self.run_export()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = self.read_out()
        self.assertEqual(len(rows), 1, "同 id 不应追加成第二行")
        self.assertEqual(rows[0]["id"], "Lkeep")
        self.assertEqual(rows[0]["text"], "旧正文", "已有条目不应被覆盖")
        self.assertIn("够格 1 条，新导出 0 条", proc.stdout)

    def test_default_out_is_repo_seed_constant(self):
        """T5：只断言模块常量 SEED 指向仓库内 seed，不执行任何写仓库的调用。"""
        spec = importlib.util.spec_from_file_location("knowledge_export_under_test", SCRIPT)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)   # 只导入；不会调用 main()，不写任何文件

        seed = Path(module.SEED)
        self.assertTrue(seed.as_posix().endswith("sa2/knowledge/seed/lessons.jsonl"))
        self.assertEqual(seed, ROOT / "sa2" / "knowledge" / "seed" / "lessons.jsonl")


if __name__ == "__main__":
    unittest.main()