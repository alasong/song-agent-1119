"""跨运行资产：判据库、案例库、登记历史。

在此之前，`criteria.json` 与 `cases.jsonl` 都建在单次 run 目录下（`scripts/sa2_live.py:91-92`），
所以每跑一次都从零开始——判据不积累、教训不复用。这一层把它们挪到跨运行目录。

默认位置：`~/xm-runs/sa2/registry/`
环境变量：`XM_SA2_REGISTRY` 可整体换掉（测试用临时目录）。
"""
from __future__ import annotations

import os
from pathlib import Path


def root() -> Path:
    return Path(os.environ.get("XM_SA2_REGISTRY",
                               str(Path.home() / "xm-runs" / "sa2" / "registry"))).expanduser()


def ensure() -> Path:
    path = root()
    path.mkdir(parents=True, exist_ok=True)
    return path


def criteria_path() -> Path:
    return ensure() / "criteria.json"


def criteria_history_path() -> Path:
    return ensure() / "criteria-history.jsonl"


def cases_path() -> Path:
    return ensure() / "cases.jsonl"

def lessons_path() -> Path:
    return ensure() / "lessons.jsonl"


def candidates_path() -> Path:
    """经验提升出的「机制候选」：只写不生效，等 registry 登记。"""
    return ensure() / "candidates.jsonl"


def goals_path() -> Path:
    return ensure() / "goals.json"


def plans_path() -> Path:
    """编制与流程的跨运行库（复合键，和 goals 的 goal→判据名索引分开存）。"""
    return ensure() / "plans.json"


def promotions_path() -> Path:
    """外环采纳的经验：下一轮的写手/编制提示词从这里读。"""
    return ensure() / "promotions.jsonl"


def fingerprint(goal: str) -> str:
    import hashlib
    return hashlib.sha1((goal or "").strip().encode("utf-8")).hexdigest()[:12]


def load_goal_index() -> dict:
    path = goals_path()
    if not path.exists():
        return {}
    try:
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def remember_goal(goal: str, names) -> None:
    import json
    index = load_goal_index()
    index[fingerprint(goal)] = list(names)
    goals_path().write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
