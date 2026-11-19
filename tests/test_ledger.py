import tempfile
import unittest
from pathlib import Path

from xm.ledger import Ledger, LedgerError


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_and_read(self):
        led = Ledger(self.path)
        e1 = led.append("fact", "alice", {"x": 1})
        e2 = led.append("fact", "bob")
        self.assertEqual(e1["seq"], 1)
        self.assertEqual(e2["seq"], 2)
        self.assertEqual(e1["kind"], "fact")
        self.assertEqual(len(led.read()), 2)

    def test_non_auditor_cannot_write(self):
        led = Ledger(self.path, role="executor")
        with self.assertRaises(LedgerError):
            led.append("fact", "alice")

    def test_append_only(self):
        led = Ledger(self.path)
        led.append("fact", "alice")
        size1 = self.path.stat().st_size
        led.append("fact", "alice")
        self.assertGreater(self.path.stat().st_size, size1)
        self.assertEqual(len(led.read()), 2)

    def test_count_filters(self):
        led = Ledger(self.path)
        led.append("fact", "alice")
        led.append("rejected", "alice")
        led.append("fact", "bob")
        self.assertEqual(led.count("fact"), 2)
        self.assertEqual(led.count("fact", actor="alice"), 1)
        self.assertEqual(led.count(), 3)


if __name__ == "__main__":
    unittest.main()