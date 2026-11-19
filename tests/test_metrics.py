"""健康指标采集验收测试（M0b-3 第一部分）。"""
import unittest

from xm.metrics import Metrics, MetricsError

NAMES = ["目标偏离度", "校验通过率", "通信效率", "资源利用率", "假设证伪率"]


class MetricsTest(unittest.TestCase):
    def setUp(self):
        self.m = Metrics()

    def test_record_and_value(self):
        self.m.record("目标偏离度", 0.12)
        self.assertEqual(self.m.value("目标偏离度"), 0.12)

    def test_unknown_indicator_rejected(self):
        with self.assertRaises(MetricsError):
            self.m.record("拍脑袋指标", 1.0)

    def test_value_of_unrecorded_is_none(self):
        self.assertIsNone(self.m.value("通信效率"))

    def test_trend_rising_and_falling(self):
        for v in (1.0, 2.0, 3.0):
            self.m.record("目标偏离度", v)
        self.assertEqual(self.m.trend("目标偏离度"), "rising")
        for v in (1.0, 1.0, 1.0):
            self.m.record("通信效率", v)
        self.assertEqual(self.m.trend("通信效率"), "flat")

    def test_snapshot_covers_all_names(self):
        self.m.record("目标偏离度", 0.1)
        snap = self.m.snapshot()
        self.assertEqual(set(snap), set(NAMES))
        self.assertEqual(snap["目标偏离度"]["last"], 0.1)
        self.assertEqual(snap["目标偏离度"]["n"], 1)
        self.assertIsNone(snap["校验通过率"]["last"])


if __name__ == "__main__":
    unittest.main()