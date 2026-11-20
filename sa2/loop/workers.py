"""S4：B 载体——多 worker 进程 + 文件租约 + 心跳。

三条协议都落在文件上，跨进程才成立：
- 派活：`dispatch/<id>.json`，一次一行事，谁认领谁执行；
- 认领：`lease/<id>.json`，`O_EXCL` 建文件＝拿到租约；心跳线程续 `expires_at`；
- 结果：`result/<id>.json`，先写到的算数（at-least-once，不假装 exactly-once）。

kill -9 一个 worker 后：心跳停 → 租约过期 → 另一个 worker 抢占并重跑该作业，
账本记 `lease_expired` + `takeover`（from/to 不同进程）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from importlib import import_module
from pathlib import Path

from ..core.ledger import Ledger

REPO_ROOT = Path(__file__).resolve().parents[2]
CLAIM_POLL = 0.05


def _now() -> float:
    return time.time()


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError, ValueError, TypeError):
        return True


def _claim(lease_path: Path, worker: str, pid: int, ttl: float) -> dict | None:
    """返回 {} = 首次认领；旧租约 = 抢占；None = 没抢到。"""
    payload = {"worker": worker, "pid": pid, "expires_at": _now() + ttl,
               "claimed_at": _now()}
    try:
        fd = os.open(lease_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        current = _read(lease_path)
        if current and float(current.get("expires_at") or 0) < _now():
            _write(lease_path, payload)
            return current
        return None
    else:
        os.close(fd)
        _write(lease_path, payload)
        return {}


def _heartbeat(lease_path: Path, worker: str, ttl: float, stop: threading.Event) -> threading.Thread:
    def beat() -> None:
        while not stop.wait(max(0.05, ttl / 3)):
            current = _read(lease_path)
            if not current or current.get("worker") != worker:
                return
            current["expires_at"] = _now() + ttl
            _write(lease_path, current)

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    return thread


def _run_job(job: dict):
    module = import_module(str(job["module"]))
    func = getattr(module, str(job["func"]))
    return func(*job.get("args", []), **job.get("kwargs", {}))


def worker_main(root: str, name: str, ttl: float) -> None:
    """worker 进程主循环：认领 → 心跳 → 执行 → 写结果。"""
    root = Path(root)
    ledger = Ledger(root / "ledger.jsonl")
    stop_file = root / "stop"
    while not stop_file.exists():
        worked = False
        for path in sorted((root / "dispatch").glob("*.json")):
            job = _read(path)
            if not job:
                continue
            dispatch_id = str(job["id"])
            result_path = root / "result" / f"{dispatch_id}.json"
            if result_path.exists():
                continue
            lease_path = root / "lease" / f"{dispatch_id}.json"
            previous = _claim(lease_path, name, os.getpid(), ttl)
            if previous is None:
                continue
            worked = True
            if previous:
                ledger.append("lease_expired", str(previous.get("worker")),
                              {"id": dispatch_id, "pid": previous.get("pid")})
                ledger.append("takeover", name,
                              {"from": previous.get("worker"), "to": name,
                               "dispatch": dispatch_id})
            ledger.append("dispatch_leased", name, {"id": dispatch_id, "pid": os.getpid()})
            stop = threading.Event()
            beat = _heartbeat(lease_path, name, ttl, stop)
            try:
                out = _run_job(job["job"])
                _write(result_path, {"id": dispatch_id, "ok": True, "out": out,
                                     "worker": name, "pid": os.getpid()})
                ledger.append("dispatch_done", name, {"id": dispatch_id})
            except Exception as exc:
                _write(result_path, {"id": dispatch_id, "ok": False,
                                     "error": f"{type(exc).__name__}: {exc}",
                                     "worker": name, "pid": os.getpid()})
                ledger.append("dispatch_failed", name,
                              {"id": dispatch_id, "error": str(exc)})
            finally:
                stop.set()
                beat.join(timeout=1)
                try:
                    lease_path.unlink()
                except FileNotFoundError:
                    pass
            break
        if not worked:
            time.sleep(CLAIM_POLL)


class WorkerPool:
    def __init__(self, root, ledger: Ledger | None = None, workers: int = 2, ttl: float = 1.5):
        self.root = Path(root)
        for sub in ("dispatch", "lease", "result"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self.ledger = ledger if ledger is not None else Ledger(self.root / "ledger.jsonl")
        self.workers = workers
        self.ttl = ttl
        self._procs: dict[str, subprocess.Popen] = {}
        self._logs: list = []

    def start(self) -> "WorkerPool":
        try:
            (self.root / "stop").unlink()
        except FileNotFoundError:
            pass
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        for index in range(self.workers):
            name = f"w{index + 1}"
            log = (self.root / f"worker-{name}.log").open("ab")
            self._logs.append(log)
            self._procs[name] = subprocess.Popen(
                [sys.executable, "-m", "sa2.loop.worker",
                 str(self.root), name, str(self.ttl)],
                cwd=str(REPO_ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
        self.ledger.append("pool_start", "pool",
                           {"workers": list(self._procs), "ttl": self.ttl})
        return self

    def put(self, module: str, func: str, *args, **kwargs) -> str:
        dispatch_id = f"j-{uuid.uuid4().hex[:10]}"
        _write(self.root / "dispatch" / f"{dispatch_id}.json",
               {"id": dispatch_id, "created_at": _now(),
                "job": {"module": module, "func": func,
                        "args": list(args), "kwargs": kwargs}})
        self.ledger.append("dispatch_submitted", "pool", {"id": dispatch_id, "func": func})
        return dispatch_id

    def wait_lease(self, dispatch_id: str, timeout: float = 5.0) -> dict | None:
        deadline = _now() + timeout
        while _now() < deadline:
            lease = _read(self.root / "lease" / f"{dispatch_id}.json")
            if lease:
                return lease
            time.sleep(0.02)
        return None

    def wait(self, dispatch_id: str, timeout: float = 30.0) -> dict:
        deadline = _now() + timeout
        path = self.root / "result" / f"{dispatch_id}.json"
        while _now() < deadline:
            result = _read(path)
            if result:
                return result
            time.sleep(0.02)
        raise TimeoutError(f"派活 {dispatch_id} 在 {timeout}s 内没有结果")

    def submit(self, module: str, func: str, *args, timeout: float = 30.0, **kwargs) -> dict:
        return self.wait(self.put(module, func, *args, **kwargs), timeout=timeout)

    def kill_holder(self, dispatch_id: str) -> str | None:
        lease = _read(self.root / "lease" / f"{dispatch_id}.json")
        if not lease:
            return None
        pid = lease.get("pid")
        for name, proc in self._procs.items():
            if proc.pid == pid:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                self.ledger.append("worker_killed", name, {"pid": pid, "dispatch": dispatch_id})
                return name
        return None

    def stop(self) -> None:
        (self.root / "stop").touch()
        for name, proc in self._procs.items():
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
        for log in self._logs:
            log.close()
        self._logs.clear()
        self._procs.clear()