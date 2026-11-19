"""异常重试策略验收测试（M0b-4：daemon 自主完成的判据）。"""
import unittest

from xm.retry import Retrier, RetrierError


class RetryTest(unittest.TestCase):
    def test_delays(self):
        r = Retrier(max_attempts=3, base=0.1, factor=2.0)
        self.assertEqual([round(d, 6) for d in r.delays()], [0.1, 0.2, 0.4])

    def test_bad_config(self):
        with self.assertRaises(RetrierError):
            Retrier(max_attempts=0)
        with self.assertRaises(RetrierError):
            Retrier(max_attempts=2, base=0)

    def test_success_first_try(self):
        r = Retrier(max_attempts=3, base=0.1, sleep=lambda s: None)
        self.assertEqual(r.run(lambda: 42), 42)
        self.assertEqual(r.attempts, 1)

    def test_retries_then_succeeds(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ValueError("boom")
            return "ok"

        sleeps = []
        r = Retrier(max_attempts=3, base=0.1, sleep=sleeps.append)
        self.assertEqual(r.run(fn), "ok")
        self.assertEqual(r.attempts, 3)
        self.assertEqual([round(s, 6) for s in sleeps], [0.1, 0.2])

    def test_exhausted_raises_last(self):
        def always():
            raise ValueError("last")

        r = Retrier(max_attempts=2, base=0.1, sleep=lambda s: None)
        with self.assertRaises(ValueError):
            r.run(always)
        self.assertEqual(r.attempts, 2)


if __name__ == "__main__":
    unittest.main()