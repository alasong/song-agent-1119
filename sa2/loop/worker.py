"""worker 进程入口：python -m sa2.loop.worker <root> <name> <ttl>。"""
from __future__ import annotations

import sys

from .workers import worker_main

if __name__ == "__main__":
    if len(sys.argv) not in (4, 5):
        raise SystemExit("用法：python -m sa2.loop.worker <root> <name> <ttl> [ledger]")
    worker_main(sys.argv[1], sys.argv[2], float(sys.argv[3]),
                sys.argv[4] if len(sys.argv) == 5 else None)