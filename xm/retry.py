import time


class RetrierError(Exception):
    pass


class Retrier:
    def __init__(self, max_attempts: int, base: float = None, factor: float = 2.0, sleep=time.sleep):
        if max_attempts < 1:
            raise RetrierError("max_attempts must be at least 1")
        if base is None or base <= 0:
            raise RetrierError("base must be greater than 0")
        if factor <= 1:
            raise RetrierError("factor must be greater than 1")

        self.max_attempts = max_attempts
        self.base = base
        self.factor = factor
        self.sleep = sleep

    def delays(self):
        return [self.base * (self.factor ** i) for i in range(self.max_attempts)]

    def run(self, fn):
        self.attempts = 0
        delays = self.delays()
        last_exc = None

        for i in range(self.max_attempts):
            self.attempts += 1
            try:
                return fn()
            except Exception as exc:
                last_exc = exc
                if i < self.max_attempts - 1:
                    self.sleep(delays[i])

        raise last_exc
