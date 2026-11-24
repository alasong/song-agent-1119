"""继任者选择：同 kind 的同伴先上；没有同伴才升代次；缺档的代次读 0。

`test_sa2_liveness` 盖的是派活链与接管；这里直接打 Supervisor 的两个内部选择，
它们是「谁死了、谁接」的分支，错了会静默换人却查不出来。
"""
import tempfile
import unittest
from pathlib import Path

from sa2.core.ledger import Ledger
from sa2.forge.org import Role
from sa2.loop.supervisor import DispatchQueue, Supervisor
from sa2.memory.profiles import RoleStore


def role(name: str, kind: str = "executor") -> Role:
    return Role(name=name, kind=kind, duty="写", criteria="齐", budget=10)


class SuccessorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.ledger = Ledger(root / "ledger.jsonl")
        self.store = RoleStore(root / "roles.jsonl")

    def supervisor(self, roles) -> Supervisor:
        return Supervisor(produce=lambda *a, **k: "", ledger=self.ledger,
                          store=self.store, queue=DispatchQueue(Path(self.tmp.name) / "d.jsonl"),
                          roles=roles)

    def test_peer_of_same_kind_takes_over_first(self):
        roles = (role("甲"), role("乙"))
        self.assertEqual(self.supervisor(roles)._successor(roles[0]).name, "乙")

    def test_without_peer_generation_bumps_and_keeps_identity(self):
        roles = (role("甲"),)
        sup = self.supervisor(roles)
        self.assertEqual(sup._successor(roles[0]).name, "甲")
        self.assertEqual(sup._generation(roles[0]), 2, "没有同伴就同一身份升一代")

    def test_generation_of_unknown_role_reads_zero(self):
        self.assertEqual(self.supervisor((role("甲"),))._generation(role("从未入册")), 0)


if __name__ == "__main__":
    unittest.main()