"""运行产物的落点：默认在项目之外，避免任务结果污染项目目录。

可用环境变量 XM_RUNS 覆盖（测试里会换成临时目录）。
"""
from __future__ import annotations

import os
from pathlib import Path


def runs_root() -> Path:
    return Path(os.environ.get("XM_RUNS", str(Path.home() / "xm-runs"))).expanduser().resolve()


def run_dir(slug: str) -> Path:
    path = runs_root() / slug
    path.mkdir(parents=True, exist_ok=True)
    return path