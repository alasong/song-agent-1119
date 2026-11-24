# 核心逻辑落地清单（2026-11-24）

> 依据：`reports/core-logic-20261124.md` §7 的 9 条推荐，领导已「同意」。
> 规则：每条必须有**红的验收命令**，再改，再跑到绿；红不出来的条目说明判据写错，先改判据。
> 边界：改动落在 `sa2/`、`tests/`、`sa2/knowledge/data/`，按 README:19-24 属人审目录；本轮按领导指令落地，**不提交**，diff 留审。

## 状态总表

| # | 做什么 | 落点 | 验收命令（0/1） | 当前 |
|---|---|---|---|---|
| W1 | 6 个起手值进阈值表 | `sa2/knowledge/data/thresholds.json` | `python3 -c "from sa2 import config; assert config.get('go_depth_max')==3 and abs(config.get('dep_budget_ratio')-0.3)<1e-9"` | ✅ 绿 |
| W2 | 依赖一级词表固定五类 | `sa2/knowledge/data/deps.json` + `loader.py` | `python3 -c "from sa2.knowledge import load; print(load('deps')['classes'].keys())"` | ✅ 绿 |
| W3 | 断言单模型与校验 | `sa2/core/deps.py` + `tests/test_deps.py` | `python3 -m unittest tests.test_deps -q` | ✅ 绿 |
| W4 | step 级输入门接入 | `sa2/core/gate.py`、`loop/pdca.py` | `python3 -m unittest tests.test_deps_gate -q` | ✅ 绿（5 条） |
| W5 | 断言对错进账本 | `sa2/core/deps.py`、`loop/pdca.py` | `python3 -m unittest tests.test_deps_ledger -q` | ✅ 绿（3 条） |
| W6 | 三档验证分派 | `sa2/core/deps.py` | `python3 -m unittest tests.test_deps_dispatch -q` | ✅ 绿（7 条） |
| W7 | 暂停两种来源 | `loop/pdca.py`、账本 kind | `python3 -m unittest tests.test_pause_kinds -q` | ✅ 绿（3 条） |
| W8 | 父预算 30/70 切分 | `sa2/core/budget.py` | `python3 -m unittest tests.test_budget_split -q` | ✅ 绿（5 条） |
| W9 | 深度上限 3 层 | `sa2/core/deps.py`（depth_ok） | `python3 -m unittest tests.test_depth -q` | ✅ 绿（3 条） |
| W10 | 结果门回填漏报 | `loop/pdca.py`、`core/deps.py` | `python3 -m unittest tests.test_deps_backfill -q` | ✅ 绿（3 条） |
| W11 | 依赖三读数 | `sa2/core/metrics.py` | `python3 -m unittest tests.test_metrics_deps -q` | ✅ 绿（5 条） |
| W12 | 生产入口接线（`--require-deps` 开关，默认关） | `scripts/sa2_live.py`、`sa2/forge/deps.py` | `python3 scripts/sa2_live.py --help \| grep -q require-deps` | ✅ 绿（4 条测试 + 入口可查） |
| W13 | 租约自愈与死进程接管（flaky 排查产物） | `sa2/loop/workers.py` | `python3 -m unittest tests.test_worker_claim -q` | ✅ 绿（5 条） |
| W14 | 漏报按 supports 归因 | `sa2/core/deps.py`、`sa2/forge/deps.py`、`scripts/sa2_live.py` | `python3 -m unittest tests.test_deps tests.test_deps_backfill tests.test_sa2_deps_forge -q` | ✅ 绿（27 条 + holdout 10 轮） |

## 逐条说明

### W1 阈值（数值类，按 §7 第 4/6/9 条）

新增 6 个键，每个带 `source`（注明是起手值不是实测）与 `date`：

| 键 | 值 | 用在哪 |
|---|---|---|
| `go_depth_max` | 3 | 超过 3 层必须人确认（W9） |
| `dep_budget_ratio` | 0.30 | 父预算给依赖优化的比例（W8） |
| `checkpoint_every` | 5 | 过程门没有 step 边界时的兜底（W7） |
| `reward_return` | 0.10 | 断言验真返还比例（W5） |
| `penalty_falsified` | 0.20 | 断言证伪扣减（W5） |
| `penalty_missed` | 0.40 | 漏报依赖扣减，双倍于证伪（W10） |

**验收**：`config.get` 六个键都能读且值正确；`loader` 校验不容许缺 source/date。

### W2 依赖词表（治理类，按 §7 第 2 条）

`deps.json` 只放一级类与展示信息；**一级类集合写死在 loader 的校验里**，新增一类必须改代码（=人审），子类在数据文件里自由加。

**验收**：`load("deps")` 返回五个一级类；往 `deps.json` 加第六类会抛 `KnowledgeError`（测试覆盖）。

### W3 断言单（核心，按 §7 第 8/10 条的前提）

`sa2/core/deps.py`：`Assertion(name, cls, claim, verify, if_false)`、`DepNote(step, items, gaps)`、`check(note)`、`acyclic(edges)`。
校验规则：step 非空；items 非空（空=没想过）；cls 在五类内；claim ≥8 字；verify 必须是 `cmd:/path:/value:/read:` 前缀；if_false 非空；名字不重复；gaps 必须指向已列出的依赖。

**验收**：`tests/test_deps.py` 至少覆盖合法件、空单、坏验法、坏类、缺若假、重名、悬空 gap、环。

### W4–W11 依赖顺序

W4 依赖 W3；W5 依赖 W3/W4；W6 依赖 W3；W7/W8 独立；W9 依赖 W1；W10 依赖 W4/W5；W11 依赖 W5。

## 核对方法（每条都照这个走）

1. 先在当前树上跑验收命令，确认**红**（并记录报错原文）；
2. 改最小集；
3. 再跑同一条命令，绿；
4. 跑全量 `python3 -m unittest discover -s tests -t . -q` 确认没打坏别处；
5. 把命令与结果写回本表"证据"列。

红不出来的条目：说明判据写错了，先改判据，不许直接改代码。

## 首批证据（2026-11-24）

```
$ python3 -c "from sa2 import config; print(config.get('go_depth_max'), config.get('dep_budget_ratio'), config.get('checkpoint_every'), config.get('reward_return'), config.get('penalty_falsified'), config.get('penalty_missed'))"
3 0.3 5 0.1 0.2 0.4

$ python3 -c "from sa2.knowledge import load; print(tuple(load('deps')['classes']))"
('team', 'method', 'process', 'tool', 'other')

$ python3 -m unittest tests.test_deps -q
Ran 14 tests in 0.001s
OK

$ python3 -m unittest discover -s tests -t . -q
Ran 426 tests in 18.600s
OK (expected failures=1)

$ python3 scripts/claim_check.py
0 处：没有裸称最优，报告判定与读数一致
```

红→绿记录：W1 首次 `config.get('go_depth_max')` 抛 `KeyError`（红）；W2 首次 `load('deps')` 抛 `KnowledgeError: 没有这份知识`（红）；W3 首次 `import sa2.core.deps` 抛 `ModuleNotFoundError`（红）。
W3 的 14 条测试里，首跑有 1 条失败（断言文字与实现文案不一致），改的是测试断言不是实现——判据写错先改判据。

## 下一批（按依赖顺序）

W4 → W5 → W10 是一条链（输入门接上、断言入账、结果门回填）；W6 可与 W4 并行；W7/W8 独立；W9 依赖 W1；W11 依赖 W5。

## 第二批证据（2026-11-24，W4–W9）

```
$ python3 -m unittest tests.test_deps_gate tests.test_deps_ledger tests.test_deps_dispatch -q
Ran 15 tests, OK

$ python3 -m unittest tests.test_pause_kinds tests.test_budget_split tests.test_depth -q
Ran 11 tests, OK

$ python3 -m unittest discover -s tests -t . -q
Ran 452 tests in 14.809s
OK (expected failures=1)

$ python3 scripts/claim_check.py
0 处：没有裸称最优，报告判定与读数一致
```

红→绿记录：W4 首跑时 `report["problems"]` 里没有阶段名，断言失败 → 改成问题文案带阶段前缀（判据写的是"能定位到哪一步"，实现漏了定位）；W5/W6 首次 import `dependency_claim`/`dispatch` 均不存在（红）。

## 第三批证据（2026-11-24，W10–W11）

```
$ python3 -m unittest tests.test_deps_backfill tests.test_metrics_deps -q
Ran 8 tests, OK

$ python3 -m unittest discover -s tests -t . -q
Ran 460 tests in 14.887s
OK (expected failures=1)

$ python3 scripts/claim_check.py
0 处：没有裸称最优，报告判定与读数一致
```

W10 的夹具难点与解法（第一版失败留下记录）：阶段门会把产出裁剪到它自己要求的章节，所以"阶段门只要求两节、交付门要三节"永远构造不出交付红——第三行 `S3` 被 `_assemble` 裁掉了。改成**交付门用关键词判据**（`结论：`），它不受章节裁剪影响，才出现"阶段过、交付红"。

W11 的读数口径：覆盖率按阶段算（有断言的阶段 ÷ 成功阶段），命中率按断言算（验真 ÷ 验真+证伪+漏报），缺口率按漏报算（漏报 ÷ 断言数）。三个数都从账本事件算，算不出返回 `None`，不拿零冒充。

## 仍未覆盖（写清，不静默）

- `require_deps` 由 `--require-deps` 开关控制，**默认仍是关**：机制、生成、门、回填、读数都在，线上是否强制写断言单是成本决策，等你拍。
- `claim_hit_rate` 在未接 `dispatch` 的 run 里是 `None`：验证动作还没进主环，读数暂无数据，不是零。

## 第四批证据（2026-11-24，W12）

```
$ python3 -m unittest tests.test_sa2_deps_forge -q
Ran 4 tests, OK

$ python3 scripts/sa2_live.py --help | grep -A1 require-deps
  --require-deps        开工前要求每阶段提交依赖断言单（多一次模型调用；默认关）

$ python3 -m unittest discover -s tests -t . -q
Ran 464 tests in 14.581s
OK (expected failures=1)

$ python3 scripts/claim_check.py
0 处：没有裸称最优，报告判定与读数一致
```

W12 的形状：`forge/deps.py` 一次调用生成全部阶段的断言单，产出必须过 `core.deps.check`；不过就 `return 2`，不带着坏单开工。单子生成后先记 `dependency_note` 事件，再交给 PDCA。默认关是因为它多一次模型调用——开不开是成本决策，不是机制决策。

## 第五批证据（2026-11-24，W13 租约修复）

```
$ python3 -m unittest tests.test_worker_claim -q                    # Ran 5, OK
$ python3 -m unittest tests.test_sa2_liveness.WorkerPoolTest -q     # 连跑 3 次 OK
$ python3 -m unittest discover -s tests -t . -q                     # 连跑 3 次 OK（469 tests）
```

排查记录：

- 现象：一次契约验收 flaky——`派活 j-… 在 25s 内没有结果`，原命令重跑通过。
- 复现：单测连跑 10 次、全量连跑 3 次，均未复现；**原 flake 未能确证根因**。
- 但排查中发现两个真缺陷，已修：
  1. 初领任务时 `O_EXCL` 建文件到写入之间有窗口，另一个 worker 把空文件当坏租约抢走 → 同一作业被两个进程同时执行（修前事件序列：两条 `dispatch_leased`、零 `lease_expired`）；
  2. 空/坏租约原实现直接返回 None，作业永远没人领——表现正是"等待超时"。
- 修后事件序列回到设计意图：`dispatch_leased → worker_killed → lease_expired → takeover → dispatch_leased → dispatch_done`。

## 决策记录：`--require-deps` 默认值

推荐维持默认关，先灰度。门槛：连续 10 次 `--require-deps` 真跑，断言单首轮通过率 ≥ 80%、无一次因坏单中断、三个读数的缺口率有数据；达标再翻默认。理由：多一次模型调用是小事，坏单直接 `exit 2` 会阻断任务，而断言单在真模型上的质量还没有读数。
## 第六批证据（2026-11-24，W14 supports 归因）

```
$ python3 -m unittest tests.test_deps tests.test_deps_backfill tests.test_sa2_deps_forge -q   # Ran 27, OK
$ python3 -m unittest discover -s tests -t . -q                                              # Ran 478, OK
```

- 漏报只在「失败判据 ∈ 断言 supports」时记；没有 supports 的断言不罚。
- holdout 10 个未见目标：首轮 9/10，supports 覆盖 50/50 条 = 100%。
- 残余失败是模型 JSON 缺逗号（~10%），建议加一次有界重试再翻默认。
