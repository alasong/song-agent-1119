"""S1–S3：活性（liveness）的判据层。

红先：本文件先于 `sa2/memory/profiles.py` 存在，import 即失败。
每个用例只断言一件可判红的事——档案在盘上、身份不丢、接管包带得走未偿承诺。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sa2.memory.profiles import RoleProfile, RoleStore


class RoleProfileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "roles.jsonl"
        self.store = RoleStore(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_unknown_role_is_loud(self):
        with self.assertRaises(KeyError):
            self.store.get("没有这个人")

    def test_save_and_get_roundtrip(self):
        profile = RoleProfile(id="r1", kind="researcher", duty="查文献与取数",
                              tools=("fetch:arxiv",), criteria_version="c1")
        self.store.save(profile)
        got = self.store.get("r1")
        self.assertEqual(got.kind, "researcher")
        self.assertEqual(got.duty, "查文献与取数")
        self.assertEqual(got.tools, ("fetch:arxiv",))
        self.assertEqual(got.criteria_version, "c1")
        # P0 的 calibration 是空壳：None 表示「还没有真值」，不是 0.0
        self.assertIsNone(got.calibration)

    def test_empty_store_is_empty_not_error(self):
        self.assertEqual(self.store.all(), [])

    def test_promises_survive_reload_and_can_resolve(self):
        profile = RoleProfile(id="r2", kind="writer", duty="写正文")
        promise = profile.add_promise("把第三节写完", goal="g-1")
        self.store.save(profile)
        got = RoleStore(self.path).get("r2")     # 换实例 = 重新读盘
        self.assertEqual([x["id"] for x in got.promises], [promise["id"]])
        self.assertTrue(got.resolve_promise(promise["id"]))
        self.assertFalse(got.resolve_promise("没有这条承诺"))
        self.store.save(got)
        self.assertEqual(RoleStore(self.path).get("r2").promises[0]["status"], "done")

    def test_record_counts_are_visible(self):
        profile = RoleProfile(id="r3", kind="verifier")
        profile.bump("done")
        profile.bump("done")
        profile.bump("rejected")
        self.store.save(profile)
        self.assertEqual(self.store.get("r3").record,
                         {"done": 2, "rejected": 1, "takeovers": 0})

    def test_latest_wins_for_same_id(self):
        self.store.save(RoleProfile(id="r4", kind="writer", duty="v1"))
        self.store.save(RoleProfile(id="r4", kind="writer", duty="v2"))
        self.assertEqual(self.store.get("r4").duty, "v2")
        self.assertEqual(len(self.store.all()), 1, "同一 id 只算一份档案，历史行不算第二个人")

    def test_by_kind_returns_latest_only(self):
        self.store.save(RoleProfile(id="r5", kind="researcher", duty="v1"))
        self.store.save(RoleProfile(id="r6", kind="researcher"))
        self.store.save(RoleProfile(id="r5", kind="researcher", duty="v2"))
        got = {p.id: p.duty for p in self.store.by_kind("researcher")}
        self.assertEqual(got, {"r5": "v2", "r6": ""})

    def test_broken_line_is_loud(self):
        self.path.write_text("{坏行}\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.all()

    def test_handover_carries_only_what_successor_needs(self):
        profile = RoleProfile(id="r7", kind="writer", duty="写第二节",
                              criteria_version="c2")
        pending = profile.add_promise("补上引用")
        done = profile.add_promise("已做完的事")
        profile.resolve_promise(done["id"])
        profile.bump("rejected")
        pack = profile.handover()
        self.assertEqual(pack["role_id"], "r7")
        self.assertEqual(pack["duty"], "写第二节")
        self.assertEqual([x["id"] for x in pack["promises"]], [pending["id"]],
                         "接管包只带未偿承诺，不带已了结的")
        self.assertEqual(pack["record"]["rejected"], 1)
        self.assertEqual(pack["criteria_version"], "c2")


class RoleStoreDurabilityTest(unittest.TestCase):
    def test_append_only_file_grows_but_identity_stays_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "roles.jsonl"
            store = RoleStore(path)
            store.save(RoleProfile(id="r8", kind="writer", duty="v1"))
            store.save(RoleProfile(id="r8", kind="writer", duty="v2"))
            lines = [x for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
            self.assertEqual(len(lines), 2, "档案是追加写，不覆盖历史")
            self.assertEqual(store.get("r8").duty, "v2")
            self.assertEqual(json.loads(lines[0])["duty"], "v1")


if __name__ == "__main__":
    unittest.main()