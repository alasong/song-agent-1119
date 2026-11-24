"""跨运行资产登记：判据索引与目录落点。

`registry.py` 是「跑一次就从零开始」的反面——判据按 goal 的指纹跨运行复用。
这里钉三件事：落点可被环境变量换掉、指纹稳定、索引坏了不炸（返回空表）。
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sa2.memory import registry


class RegistryRootTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "registry"
        self._env = mock.patch.dict(os.environ, {"XM_SA2_REGISTRY": str(self.root)})
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_env_override_moves_every_path(self):
        self.assertEqual(registry.root(), self.root)
        for path in (registry.criteria_path(), registry.criteria_history_path(),
                     registry.cases_path(), registry.lessons_path(),
                     registry.candidates_path(), registry.goals_path(),
                     registry.plans_path(), registry.promotions_path()):
            self.assertEqual(path.parent, self.root, path)
            self.assertTrue(self.root.is_dir(), "取路径时就该把目录建好")
        self.assertEqual(len({registry.criteria_path(), registry.cases_path(),
                              registry.goals_path(), registry.plans_path()}), 4,
                         "不同资产不能落到同一个文件")


class FingerprintTest(unittest.TestCase):
    def test_stable_and_short(self):
        first = registry.fingerprint("写一份报告")
        self.assertEqual(first, registry.fingerprint("写一份报告"))
        self.assertEqual(len(first), 12)

    def test_whitespace_does_not_change_identity(self):
        self.assertEqual(registry.fingerprint("  写一份报告 \n"),
                         registry.fingerprint("写一份报告"))

    def test_different_goals_differ(self):
        self.assertNotEqual(registry.fingerprint("写一份报告"),
                            registry.fingerprint("写一份综述"))


class GoalIndexTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "registry"
        self._env = mock.patch.dict(os.environ, {"XM_SA2_REGISTRY": str(self.root)})
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_missing_index_reads_empty(self):
        self.assertEqual(registry.load_goal_index(), {})

    def test_remember_then_read(self):
        registry.remember_goal("写一份报告", ["结论", "引用"])
        index = registry.load_goal_index()
        self.assertEqual(index[registry.fingerprint("写一份报告")], ["结论", "引用"])

    def test_second_goal_is_appended_not_replaced(self):
        registry.remember_goal("写一份报告", ["结论"])
        registry.remember_goal("写一份综述", ["引用"])
        index = registry.load_goal_index()
        self.assertEqual(len(index), 2)
        self.assertEqual(index[registry.fingerprint("写一份综述")], ["引用"])

    def test_corrupt_index_reads_empty_instead_of_raising(self):
        registry.goals_path().write_text("{坏掉的 JSON", encoding="utf-8")
        self.assertEqual(registry.load_goal_index(), {})

    def test_index_keeps_chinese_literally(self):
        registry.remember_goal("写一份报告", ["结论"])
        raw = registry.goals_path().read_text(encoding="utf-8")
        self.assertIn("结论", raw, "落盘要人能读，不能用 \\u 转义")
        self.assertNotIn("\\u", raw)


if __name__ == "__main__":
    unittest.main()