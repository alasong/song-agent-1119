"""密钥解析：环境变量优先，实验环境回退到 DSH 进程环境；都拿不到就抛。

这一段以前被标成「依赖本机进程表所以测不了」——其实只要把 `ps` 的两次输出换成假数据，
三条分支都能确定性判红，而且不用真去读别人的进程环境。
"""
import os
import unittest
from unittest import mock

from sa2 import llm

PS_LIST = """  PID COMMAND
 1001 /Applications/DeepSeek Harness.app/Contents/MacOS/dsh
 1002 /usr/bin/some-other-thing
"""
PS_ENV = "DEEPSEEK_API_KEY=sk-from-process OTHER=1\n"


def fake_run(calls: list):
    def run(argv, **kw):
        calls.append(argv)
        if argv[:2] == ["ps", "-Ao"]:
            return mock.Mock(stdout=PS_LIST)
        return mock.Mock(stdout=PS_ENV)

    return run


class ResolveKeyTest(unittest.TestCase):
    def test_env_key_wins_and_ps_is_not_consulted(self):
        calls: list = []
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-env"}), \
                mock.patch.object(llm.subprocess, "run", fake_run(calls)):
            self.assertEqual(llm.resolve_key(), "sk-env")
        self.assertEqual(calls, [])

    def test_falls_back_to_process_env_of_dsh(self):
        calls: list = []
        env = {k: v for k, v in os.environ.items() if k != "DEEPSEEK_API_KEY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(llm.subprocess, "run", fake_run(calls)):
            self.assertEqual(llm.resolve_key(), "sk-from-process")
        self.assertEqual(len(calls), 2, "先列进程，再读那个进程的环境")

    def test_no_key_anywhere_is_loud(self):
        calls: list = []
        env = {k: v for k, v in os.environ.items() if k != "DEEPSEEK_API_KEY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(llm.subprocess, "run",
                                  lambda argv, **kw: mock.Mock(stdout="  PID COMMAND\n")):
            with self.assertRaisesRegex(llm.LLMError, "找不到可用的 DEEPSEEK_API_KEY"):
                llm.resolve_key()


if __name__ == "__main__":
    unittest.main()