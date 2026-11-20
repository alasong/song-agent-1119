"""S1–S3：活性（liveness）的判据层。

红先：本文件先于 `sa2/memory/profiles.py` 存在，import 即失败。
每个用例只断言一件可判红的事——档案在盘上、身份不丢、接管包带得走未偿承诺。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sa2.core.gate import Declaration
from sa2.core.judge import Judge
from sa2.core.ledger import Ledger
from sa2.forge import criteria as fc
from sa2.forge import dims as fd
from sa2.forge import org as fo
from sa2.forge.org import Role
from sa2.loop.pdca import PDCA
from sa2.loop.supervisor import DispatchQueue, Supervisor
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


ORG_JSON = json.dumps({
    "roles": [
        {"name": "规划", "kind": "planner", "duty": "拆", "criteria": "可验收", "budget": 10},
        {"name": "执行", "kind": "executor", "duty": "写", "criteria": "齐全", "budget": 20},
        {"name": "验证", "kind": "verifier", "duty": "只判", "criteria": "有结论", "budget": 5},
    ],
    "stages": [
        {"name": "起草", "output": "草稿", "roles": ["规划", "执行"], "gate_criteria": ["起草齐全"]},
        {"name": "成稿", "output": "成稿", "roles": ["执行", "验证"], "gate_criteria": ["成稿齐全"]},
    ],
}, ensure_ascii=False)


def _judge():
    judge = Judge(authority=("leader",))
    for name, required in (("起草齐全", ["## 一、a", "## 二、b"]),
                           ("成稿齐全", ["## 一、a", "## 二、b", "## 三、c"])):
        judge.register(fc.tested(fc.propose_sections(name, required,
                                                    ("correctness", "test_quality"))),
                       proposer="leader")
    return judge


class SupervisorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ledger = Ledger(self.root / "ledger.jsonl")
        self.store = RoleStore(self.root / "roles.jsonl")
        self.queue = DispatchQueue(self.root / "dispatches.jsonl")
        self.roles = [Role(name="执行", kind="executor", duty="写", criteria="齐全", budget=10),
                      Role(name="验证", kind="verifier", duty="判", criteria="有结论", budget=5)]

    def tearDown(self):
        self.tmp.cleanup()

    def _sup(self, produce, max_takeovers=1):
        return Supervisor(produce, self.ledger, self.store, self.queue,
                          roles=self.roles, max_takeovers=max_takeovers)

    def test_clean_run_has_no_death(self):
        out = self._sup(lambda *a, **k: "ok").dispatch(self.roles[0], "起草", "上游", 1)
        self.assertEqual(out, "ok")
        self.assertEqual(self.ledger.count("role_died"), 0)
        self.assertEqual([d.state for d in self.queue.all()], ["done"])
        self.assertEqual(self.store.get("执行").record["done"], 1)

    def test_death_is_detected_and_successor_finishes(self):
        profile = RoleProfile(id="执行", kind="executor", duty="写")
        profile.add_promise("把第三节的引用补齐")
        self.store.save(profile)
        seen = []

        def produce(role, stage, upstream, attempt, feedback="", requirements=""):
            seen.append(feedback)
            if "接管包" not in feedback:
                raise RuntimeError("模型通道断了")
            return "写完了"

        out = self._sup(produce).dispatch(self.roles[0], "起草", "上游内容", 1,
                                          partial="已经写完的第一节")
        self.assertEqual(out, "写完了")
        self.assertEqual(self.ledger.count("role_died"), 1)
        self.assertEqual(self.ledger.count("takeover"), 1)
        event = [e for e in self.ledger.read() if e["kind"] == "takeover"][0]
        package = event["payload"]["package"]
        self.assertEqual(package["promises"][0]["text"], "把第三节的引用补齐")
        self.assertEqual(package["partial"], "已经写完的第一节")
        self.assertIn("模型通道断了", package["last_error"])
        self.assertEqual(self.store.get("执行").generation, 2, "继任是同一身份的第 2 代")
        self.assertEqual(sorted(d.state for d in self.queue.all()), ["done", "failed"])
        self.assertIn("接管包", seen[-1], "继任者必须收到接管包，不是盲重试")

    def test_death_twice_escalates_and_raises(self):
        def die(*a, **k):
            raise RuntimeError("一直断")

        with self.assertRaises(RuntimeError):
            self._sup(die).dispatch(self.roles[0], "起草", "上游", 1)
        self.assertEqual(self.ledger.count("role_died"), 2)
        self.assertEqual(self.ledger.count("escalated"), 1, "判不动就升级，不许无限重试")
        self.assertEqual([d.state for d in self.queue.all()], ["failed", "failed"])


class PDCATakeoverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ledger = Ledger(self.root / "ledger.jsonl")
        self.store = RoleStore(self.root / "roles.jsonl")
        self.queue = DispatchQueue(self.root / "dispatches.jsonl")
        self.plan = fo.parse_plan("目标", ORG_JSON)

    def tearDown(self):
        self.tmp.cleanup()

    def test_task_survives_one_role_death(self):
        profile = RoleProfile(id="执行", kind="executor", duty="写")
        profile.add_promise("补引用")
        self.store.save(profile)

        def produce(role, stage, upstream, attempt, feedback="", requirements=""):
            if role.kind != "executor":
                return ""
            if stage == "起草":
                if "接管包" not in (feedback or ""):
                    raise RuntimeError("通道断了")
                return "## 一、a\n## 二、b\n"
            return "## 一、a\n## 二、b\n## 三、c\n"

        supervisor = Supervisor(produce, self.ledger, self.store, self.queue,
                                roles=self.plan.roles)
        pdca = PDCA(_judge(), self.ledger, self.plan, produce, fd.VOCAB,
                    supervisor=supervisor)
        decl = Declaration(goal="写东西", dims=("correctness", "test_quality"),
                           criteria=("起草齐全", "成稿齐全"), budget_tokens=100_000)
        report = pdca.run(decl)
        self.assertTrue(report["passed"], report)
        self.assertEqual(self.ledger.count("role_died"), 1)
        self.assertEqual(self.ledger.count("takeover"), 1)
        self.assertEqual(self.store.get("执行").pending_promises()[0]["text"], "补引用",
                         "没做完的承诺还在档案上，下一任接着认")


if __name__ == "__main__":
    unittest.main()