# sa2 测试覆盖与接口报告

> 一次性盘点，不是常驻门禁：读数是踩在 2026-11-25 的 187 个提交上取的。

## 结论

sa2 当前 763 个测试全绿（预期失败 1 条按设计保留），46 个模块、5677 行代码里进程内未覆盖行只剩 `sa2/loop/worker.py` 的 9 行（子进程入口，由三个真子进程用例覆盖）；对外接口 181 个公开符号、24 个 CLI 入口。[S1][S3][S4]

## 依据

- 全量回归 763 条（`python3 -m unittest discover -s tests -t . -q`，exit 0），覆盖探针按 `co_lines` 口径只有 `worker.py` 9/9 未命中，其余模块为 0；**否掉**“用断言数量或文件名估计覆盖率”的做法——读数是逐行探针跑出来的。
- 接口面用 AST 抽取：46 个模块中 45 个有公开符号，共 181 个；24 个脚本带 CLI 入口；**不采用**“README 列了什么就算什么”，以代码定义为准。
- 门禁侧 `scripts/claim_check.py` 返回 0 处；证据台账 `[S1]–[S4]` 每条都能在台账里查到取回记录与内容摘要。

## 证据

- [S1] `python3 -m unittest discover -s tests -t . -q`：`Ran 763 tests`、`OK (expected failures=1)`，exit 0。
- [S2] `python3 scripts/claim_check.py`：`0 处：没有裸称最优，报告判定与读数一致`，exit 0。
- [S3] AST 盘点：46 个模块 / 5677 行 / 181 个公开符号 / 24 个 CLI 入口 / 79 个测试文件 / 187 个提交。
- [S4] 覆盖探针表：`sa2/loop/worker.py` 9/9，其余模块 0 miss；探针口径见下文盘点节。
- 关键位置：`sa2/core/judge.py:90`、`sa2/loop/pdca.py:70`、`sa2/forge/org.py:68`、`sa2/loop/workers.py:247`。
- 台账：`~/xm-runs/sa2/demo-evidence/20261125.jsonl`（[S1]–[S4] 的取回记录与内容摘要）。

## 盘点：测试与覆盖

| 指标 | 读数 | 来源 |
|---|---|---|
| 测试用例 | 763 条，全绿（预期失败 1 条） | [S1] |
| 测试文件 | 79 个 | [S3] |
| sa2 模块 | 46 个（不含 `__init__`）/ 5677 行 | [S3] |
| 进程内未覆盖行 | 仅 `sa2/loop/worker.py` 9 行 | [S4] |
| 公开符号 / CLI 入口 | 181 / 24 | [S3] |
| claim_check | 0 处 | [S2] |

口径说明：覆盖率是一次性 `sys.settrace` 探针（开启 `threading.settrace`）跑全量测试得到，按 `co_lines` 统计；`worker.py` 的 9 行只在子进程里执行，进程内探针看不到，由 `tests/test_worker_entry.py` 的三个真子进程用例覆盖。探针脚本放在 `/tmp`，不在仓库里，所以这不是可复现门禁。

## 接口面（关键契约）

| 接口 | 位置 | 契约 |
|---|---|---|
| `Judge.register(crit, proposer)` | `sa2/core/judge.py:90` | proposer 不在判定权名单 → `Unauthorized`；同名重登升版本 |
| `PDCA.run(decl, seed, evidence)` | `sa2/loop/pdca.py:70` | 返回 report；阶段门红了只重做该阶段，交付门红了回退最后一阶段一次 |
| `gate.pre_flight(decl, judge, vocab)` | `sa2/core/gate.py:116` | 开跑前把声明与判据问题一次报全 |
| `delivery.check(text)` | `sa2/delivery.py:71` | 五条规则，返回 `{ok, missing, reasons}` |
| `deps.parse / check / dispatch` | `sa2/core/deps.py:54` / `:82` / `:171` | 断言单形状 → 问题列表 → 三档验证；pending 不等于通过 |
| `evidence.stamp / check_citations` | `sa2/core/evidence.py:59` / `:157` | 内容寻址落盘 + 系统打戳；引用要查台账与时效 |
| `org.parse_plan(raw, cap, ...)` | `sa2/forge/org.py:68` | 编制硬校验：≥3 角色、独立 verifier、非全连接、预算上限 |
| `WorkerPool.submit(...)` | `sa2/loop/workers.py:247` | 派活到子进程；结果文件先到先得，租约过期可接管 |
| `Harness.advance(item, to, artifacts)` | `sa2/core/harness.py:104` | 只按证据与注册的校验命令推进；处理器异常记 reject 再抛 |
| `ResourceBook.request(amount, purpose)` | `sa2/core/resources.py:53` | 超阈值只入队不扣款；批准时复核余额 |

接口面的边界：AST 只能证明“这个符号存在且签名如此”，证明不了调用方是否兼容；破坏性改名仍可能漏过去。

## 缺口与整改

1. `worker.py` 的 9 行只有子进程覆盖：保留三个真子进程用例，不为数字在进程内造分支。
2. 24 个 CLI 入口里只有 12 个有专门演示或测试：其余靠单元用例覆盖，没有参数冒烟；要防参数漂移，应加 `--help` 冒烟矩阵。
3. `close_with_delivery` 已实现但 `sa2_live` 没接线：机制有了没接上，接线前要补一条端到端用例。
4. 覆盖率探针在 `/tmp`、不入仓：要长期跟踪覆盖，应落成 `scripts/coverage_probe.py` 并加一条门；本案没做。
5. 接口面只做定义统计、不做调用兼容：应补接口签名快照（未做）。