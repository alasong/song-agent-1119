"""过程资产的两条底线：造出来的工具有没有家，嵌套时钱是不是一个池子。

真跑（2026-11-20）暴露的两处：生成的检查器写在 run 目录、判据的 cmd 指着那串
绝对路径，run 目录一清就是断刀；预算每层 `Budget(自己的上限)` 各自新建，
子任务可以给自己加额度——嵌套一层就等于多印一份钱。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sa2.core.budget import Budget
from sa2.memory.tools import ToolError, ToolStore


class ToolStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ToolStore(self.tmp.name)
        self.src_dir = Path(self.tmp.name) / "run-tools"
        self.src_dir.mkdir()
        self.script = self.src_dir / "check.py"
        self.script.write_text("print('v1')\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def store_it(self) -> dict:
        return self.store.store(self.script, name="检查器", owner="leader",
                                signature="<script> <target.md>", self_test={"ok": True})

    def test_script_without_self_test_is_refused(self):
        with self.assertRaises(ToolError):
            self.store.store(self.script, name="检查器", owner="leader")
        self.assertEqual(self.store.all(), {}, "被拒的脚本不许留下半条登记")

    def test_same_script_twice_does_not_bump_version(self):
        first = self.store_it()
        second = self.store_it()
        self.assertEqual((first["version"], second["version"]), (1, 1))
        self.assertEqual(second["uses"], 1, "重复入库只该记一次使用")
        self.assertEqual(len(list(self.store.root.glob("*.py"))), 1, "同一份脚本只存一份")

    def test_changed_script_bumps_version_and_keeps_history(self):
        self.store_it()
        self.script.write_text("print('v2')\n", encoding="utf-8")
        entry = self.store_it()
        self.assertEqual(entry["version"], 2)
        lines = [json.loads(x) for x in
                 self.store.history_path.read_text(encoding="utf-8").splitlines() if x.strip()]
        self.assertEqual([x["action"] for x in lines], ["registered", "replaced"])
        self.assertEqual(lines[-1]["replaced_version"], 1)

    def test_asset_survives_deleting_the_run_dir(self):
        entry = self.store_it()
        self.script.unlink()
        self.src_dir.rmdir()
        self.assertTrue(Path(entry["path"]).is_file(), "入库后不该再依赖原来的目录")
        self.assertEqual(self.store.resolve("检查器"), Path(entry["path"]))

    def test_broken_blade_is_reported_not_silent(self):
        entry = self.store_it()
        Path(entry["path"]).unlink()
        with self.assertRaises(ToolError) as ctx:
            self.store.resolve("检查器")
        self.assertIn("断刀", str(ctx.exception))

    def test_unknown_tool_is_reported(self):
        with self.assertRaises(ToolError):
            self.store.get("不存在的工具")

    def test_capability_defaults_to_checker_and_is_recorded(self):
        entry = self.store_it()
        self.assertEqual(entry["capability"], "checker", "检查器是默认能力，别冒充成手")
        other = self.store.store(self.script, name="抓取器", owner="leader",
                                 capability="fetch", self_test={"ok": True})
        self.assertEqual(other["capability"], "fetch")

    def test_touch_records_use(self):
        self.store_it()
        entry = self.store.touch("检查器")
        self.assertEqual(entry["uses"], 1)
        self.assertTrue(entry["last_used"])


class NestedBudgetTest(unittest.TestCase):
    def test_child_share_is_capped_by_parent_remainder(self):
        parent = Budget(1000, usage=[{"total_tokens": 100}] * 3)
        child = parent.child(800)
        self.assertEqual(parent.spent, 300)
        self.assertEqual(child.tokens, 700, "800 的份额只能拿到父池剩下的 700")

    def test_child_cannot_mint_its_own_budget(self):
        parent = Budget(1000, usage=[{"total_tokens": 900}])
        child = parent.child(800)
        self.assertEqual(child.tokens, 100, "只剩 100 就只能给 100")

    def test_exhausted_pool_hands_out_nothing(self):
        parent = Budget(1000, usage=[{"total_tokens": 1100}])
        child = parent.child(500)
        self.assertEqual(child.tokens, 0)
        self.assertTrue(child.exhausted())

    def test_spend_is_not_double_counted(self):
        usage = [{"total_tokens": 300}]
        parent = Budget(1000, usage=usage)
        child = parent.child(700)
        usage.append({"total_tokens": 400})
        self.assertEqual(child.spent, 400, "子层只算自己花的")
        self.assertEqual(parent.spent, 700, "父层看总额")
        self.assertEqual(child.total, 700)

    def test_child_stops_at_its_share_while_pool_has_room(self):
        usage: list[dict] = []
        parent = Budget(1000, usage=usage)
        child = parent.child(100)
        usage.append({"total_tokens": 150})
        self.assertTrue(child.exhausted())
        self.assertFalse(parent.exhausted(), "份额超了不该把整池判死")

    def test_pool_over_limit_stops_the_child_too(self):
        usage: list[dict] = []
        parent = Budget(1000, usage=usage)
        child = parent.child(1000)
        usage.append({"total_tokens": 1100})
        self.assertTrue(child.exhausted(), "链上任何一层超了都算用尽")
        self.assertIn("池子", child.why("定稿"))

    def test_estimate_mode_counts_child_into_pool(self):
        parent = Budget(1000)
        child = parent.child(500)
        parent.note("x" * 40)
        child.note("y" * 40)
        self.assertEqual(child.spent, 10)
        self.assertEqual(parent.spent, 20, "估算口径也要把子层花的算进池子")

    def test_root_budget_keeps_old_semantics(self):
        b = Budget(100, usage=[{"total_tokens": 7}])
        b.note("x" * 40)
        self.assertEqual(b.spent, 7)
        self.assertEqual(b.total, 7)
        self.assertFalse(b.exhausted())


if __name__ == "__main__":
    unittest.main()