"""工具库的落点与入库前检查：目录跟着 registry 走，脚本不存在当场拒。

工具库是「角色手上有没有能用的手」的凭据；落点错位或收进一个不存在的脚本，
后面的编制校验会拿假工具当真手。
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sa2.memory import tools


class ToolRootTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.registry = Path(self.tmp.name) / "registry"
        self._env = mock.patch.dict(os.environ, {"XM_SA2_REGISTRY": str(self.registry)})
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_tool_root_lives_under_registry_and_is_created(self):
        path = tools.root()
        self.assertEqual(path, self.registry / "tools")
        self.assertTrue(path.is_dir(), "取落点时就把目录建好")

    def test_store_refuses_missing_script(self):
        store = tools.ToolStore(self.registry / "tools")
        with self.assertRaisesRegex(tools.ToolError, "要入库的脚本不存在"):
            store.store(self.registry / "没有这个脚本.py", name="取数", owner="leader",
                        self_test={"ok": True})


if __name__ == "__main__":
    unittest.main()