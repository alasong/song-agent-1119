"""角色档案的读回容错：空白行跳过，缺字段要带行内容报错。

档案是「谁死了、谁接」的凭据；静默丢一行等于让一个人凭空消失。
"""
import json
import tempfile
import unittest
from pathlib import Path

from sa2.memory import profiles


class RoleStoreReadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "roles.jsonl"
        self.store = profiles.RoleStore(self.path)

    def test_blank_lines_are_skipped(self):
        self.store.save(profiles.RoleProfile(id="执行", kind="executor"))
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write("\n")
        self.assertEqual([p.id for p in self.store.all()], ["执行"])

    def test_row_missing_fields_is_refused(self):
        self.path.write_text(json.dumps({"id": "执行"}) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "角色档案缺字段"):
            self.store.all()

    def test_corrupt_line_names_its_number(self):
        self.store.save(profiles.RoleProfile(id="执行", kind="executor"))
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write("{坏了\n")
        with self.assertRaisesRegex(ValueError, "第 2 行"):
            self.store.all()


if __name__ == "__main__":
    unittest.main()