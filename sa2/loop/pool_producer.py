"""S9：把 PDCA 的 produce 换成「经 worker 进程执行」的版本。

拆法：提示词在父进程拼（依赖角色/阶段/上游），worker 只收 messages + max_tokens
并调模型。这样跨进程的是数据，不是闭包——PDCA 的 produce 签名一个字不用改。

已知边界：worker 里失败会以 RuntimeError 抛回父进程，由 S2 的 supervisor 当角色死亡接住；
usage 随结果回传，预算读到的仍是真数（不是字符估算）。
"""
from __future__ import annotations


class PoolProducer:
    def __init__(self, pool, prompt_builder, max_tokens: int = 1200, timeout: float = 300,
                 job_module: str = "sa2.loop.jobs", job_func: str = "llm_complete",
                 usage: list[dict] | None = None):
        self.pool = pool
        self.prompt_builder = prompt_builder
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.job_module = job_module
        self.job_func = job_func
        self.usage = usage

    def __call__(self, role, stage, upstream: str, attempt: int,
                 feedback: str = "", requirements: str = "") -> str:
        # 验证者不产正文：这一层约定留在父进程，worker 不该为一次空调用付进程开销
        if getattr(role, "kind", "") == "verifier":
            return ""
        prompt = self.prompt_builder(role, stage, upstream, attempt, feedback, requirements)
        result = self.pool.submit(self.job_module, self.job_func,
                                  [{"role": "user", "content": prompt}],
                                  self.max_tokens, timeout=self.timeout)
        if not result.get("ok"):
            raise RuntimeError(f"worker 执行失败：{result.get('error')}")
        out = result.get("out")
        if isinstance(out, dict):
            if self.usage is not None and out.get("usage"):
                self.usage.append(out["usage"])
            return out.get("text") or ""
        return out or ""