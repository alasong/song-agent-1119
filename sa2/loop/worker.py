"""worker 进程入口：python -m sa2.loop.worker <root> <name> <ttl>。"""
from __future__ import annotations

import sys

from .workers import worker_main

if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("用法：python -m sa2.loop.worker <root> <name> <ttl>")
    worker_main(sys.argv[1], sys.argv[2], float(sys.argv[3]))