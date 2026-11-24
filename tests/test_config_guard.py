"""配置面：数在数据文件里，环境变量可覆盖，但未登记的键与解析不了的值都要当场抛。

`test_sa2_infra` 盖的是「阈值来自 thresholds.json」；这里补 provenance 与
环境变量覆盖的失败面——配置静默落回默认值时最贵的失败。
"""
import os
import unittest
from unittest import mock

from sa2 import config


class ConfigValuesTest(unittest.TestCase):
    def test_values_come_from_thresholds_file(self):
        values = config.values()
        self.assertIn("single_floor", values)
        self.assertEqual(values["single_floor"], 20000)
        self.assertEqual(values["single_floor"],
                         config.load("thresholds")["values"]["single_floor"]["value"])

    def test_provenance_of_unknown_key_is_refused(self):
        with self.assertRaisesRegex(KeyError, "未登记的配置项"):
            config.provenance("不存在的阈值")

    def test_get_of_unknown_key_is_refused(self):
        with self.assertRaisesRegex(KeyError, "未登记的配置项"):
            config.get("不存在的阈值")

    def test_provenance_carries_source_and_date(self):
        info = config.provenance("single_floor")
        self.assertTrue(info["source"].strip(), "出处不许省")
        self.assertTrue(info["date"].strip(), "日期不许省")


class EnvOverrideTest(unittest.TestCase):
    def test_int_threshold_is_overridden_by_env(self):
        with mock.patch.dict(os.environ, {"XM_SA2_SINGLE_FLOOR": "123"}):
            self.assertEqual(config.get("single_floor"), 123)

    def test_float_threshold_is_overridden_by_env(self):
        with mock.patch.dict(os.environ, {"XM_SA2_REWARD_RETURN": "0.3"}):
            self.assertAlmostEqual(config.get("reward_return"), 0.3)

    def test_unparsable_override_is_named_not_silently_defaulted(self):
        for key in ("single_floor",):
            with mock.patch.dict(os.environ, {f"XM_SA2_{key.upper()}": "不是数字"}):
                with self.assertRaisesRegex(ValueError, "无法解析"):
                    config.get(key)


if __name__ == "__main__":
    unittest.main()