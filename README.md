# sa：AI 自治科研组织（准超级智能系统）

**`sa` 是本系统本身**——要长成的那个活性组织。**用户是 sa 的领导**：下任务，sa 自主执行，按三段标准交付（结论 / 依据 / 证据，见 `AGENTS.md`）。
`sa` 不是包名，也不用来改目录或 import 路径——它是这个组织的名字，不是代码里的一层。

一套"能自己长出组织、能自我检测腐烂、能自我重构"的活性组织实验工程。
设计文档在 `docs/`，执行顺序以 `docs/ROADMAP.md` 为准。

**一句话现状**：能力验收 5/6（`python3 scripts/bench.py`）。交付入口默认**单 agent**，判据不过才组队；判据能机检也能盲评打分；知识能从公开源取、进提示词、过判据才回写。差的那一条是 G1——真实 24 小时常驻还没跑满。还不会自己找目标，也还没有跨阶段自举。

---

## 目录与边界

| 目录 | 谁写 | 放什么 | 禁令 |
|---|---|---|---|
| `docs/` | **只能人审后改** | 设计文档、论证、ROADMAP、ARCHITECTURE | 系统不得写入 |
| `xm/` | **只能人审后改** | 运行时：账本、判据、准出、总线、调度、daemon、模型通道 | 系统不得写入 |
| `tests/` | **只能人审后改** | 机检判据，一切「完成」的唯一标准 | 系统不得写入，也不得改断言 |
| `scripts/` | **只能人审后改** | 入口脚本（跑实验、自举） | 系统不得写入 |
| `~/xm-runs/` | 系统写 | **项目之外**：任务包、产物、任务判据（check.py）、账本 | 不入库；可用 `XM_RUNS` 改位置 |
| `sandbox/` | 系统写 | 自举用的隔离副本，改完出 diff 交人审 | 不得直接改项目目录 |
| `reports/` | 审计方写 | 实验读数与账本（证据） | 只增不改 |

**这条边界是硬的**：`DaemonConfig` 会拒绝任何写到 `artifacts_root`（默认 `~/xm-runs`，即项目外）以外的任务；项目目录（`docs/`、`xm/`、`tests/`、`scripts/`）只能由人审过的变更修改。一见即测的守卫在 `tests/test_isolation.py`。

**任务判据跟着任务走**：一次性任务的 `check.py` 放在 `~/xm-runs/<任务>/` 里，不进项目 `tests/`——`tests/` 只放长期有效的项目判据（如 M1 的里程碑判据）。

---

## 怎么跑

```bash
# 全部测试（176 条，必须全绿）
python3 -m unittest discover -s tests -t . -q

# 能力验收：六条判据，退出码 0 = 够了
python3 scripts/bench.py

# 交付：先一个人干，判不过才组队（决策与读数落 reports/deliver-*.json）
DEEPSEEK_API_KEY=... python3 scripts/deliver.py --task ~/xm-runs/<任务> --goal "<目标>"

# 同任务 A/B 对照；--judge-existing 只给已有产物做盲评（1 次调用）
python3 scripts/ab_test.py --judge --task ~/xm-runs/<任务>
python3 scripts/ab_test.py --judge-existing reports/ab-<ts>.json

# 常驻：跑满 24h 才会写 reports/liveness-*.json
python3 scripts/resident_run.py --hours 24 --interval 600

# 从 ROADMAP 取下一个任务，生成任务包（没有机检判据就拒绝执行）
python3 scripts/bootstrap_run.py
```

模型通道：`xm/llm.py` 只做一次 chat completion，密钥不落盘——先读 `DEEPSEEK_API_KEY`，实验环境回退到正在运行的 DSH 进程环境；网络错误有界重试，4xx 不重试。

---

## 验收口径（认读数不认感觉）

六条能力判据在 [`docs/ACCEPTANCE.md`](docs/ACCEPTANCE.md)，由 `scripts/bench.py` 机检，**当前 5/6**：
G2 组织性 / G3 判据 / G4 知识 / G5 不漂移 / G6 成本 绿；G1（真实 24h 常驻）还在跑墙钟。

「更优」怎么判见 [`docs/OPTIMALITY.md`](docs/OPTIMALITY.md)：开放任务上只能声称 **L1 占优**或
**L2 未发现更优**，不能声称「最优」。L1 的实现是 `xm/quality.py` 的 5 维盲评 + `scripts/ab_test.py` 的 Pareto 裁定。

设计细节见 `docs/`，架构与决策理由见 `docs/ARCHITECTURE.md`。

---

## 演进规矩

1. **没有机检判据的任务不接**——判据先写，再动手。
2. **结构性变更走人审**：系统只能改 `sandbox/`，改完出 diff，人看 diff 决定合入。
3. **失败要大声**：跳过、降级、没覆盖都写进 `reports/` 与 `unmeasured` 字段，不静默通过。
---

能力验收（什么算够了）：见 `docs/ACCEPTANCE.md`，跑 `python3 scripts/bench.py`。
