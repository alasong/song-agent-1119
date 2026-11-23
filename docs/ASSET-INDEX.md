# 全资产「骨架 → 增量刷新 → 细节」

> 状态：核心已落地（`scripts/asset_index.py` + `tests/test_asset_index.py`，21 条机检）。
> 非文件资产、PDF、并发锁是设计或明确未覆盖（§6、§7 明写，不装作有）。
> 触发：希望 agent 读**任何**项目资产都先拿骨架、按索引定位、增量刷新，而不是整读。

## 0. 结论

**能泛化，但泛化的对象是「三个动词」，不是「一张索引」。**

| 动词 | 对所有资产都成立 | 为什么 |
|---|---|---|
| 骨架 | 先拿结构，不拿正文 | 骨架代价近似常量，整读随体量线性涨；读第二次就赚 |
| 定位 | 由骨架给出 `path:start-end` / 主键 / 分页游标 | 让「细节」变成一次有界读取，而不是重开整份 |
| 增量 | 只重算变化的条目 | 变化是稀疏的；全量重建付的是没变的 99% 的钱 |

**不能泛化的是「每次读都先刷一遍索引」这一步。** 本仓实测：全量重建 ≈226ms，
无变化刷新 ≈15.7ms（14.4×），但单次 `get` 有 ≈50ms 的进程启动固定成本
（`cat` 一个 950 字节文件 3.7ms）——对小文件，先建索引再读是净亏。
`~/.dsh/notes/read-discipline.md` 记过同一结论（查索引 96ms vs 直接扫 6ms）。
所以落地判据是：

> **骨架无条件（现算也便宜），持久化索引有条件（见 §3）。**

代码里这两条都有对应实现：`get` 对未登记/过期/小文件一律现场抽取（不返回旧行号），
`build/refresh` 对 ≤4KB 的文件不落 sections（`THIN_BYTES`）。

## 1. 一条协议，六类资产

同一份记录形状，`adapter` 只决定「结构从哪来」：

```json
{"path","kind","adapter","size","mtime_ns","sha256","lines",
 "sections":[{"label","kind","start","end"}],"note"}
```

| 资产 | kind | adapter | 骨架是什么 | 定位方式 |
|---|---|---|---|---|
| 代码 | `code` | `python_ast` / `code_regex:<lang>` | 类/函数 + 行区间 | `path:start-end` |
| 文档 | `doc` | `markdown` | 章节树（含子节） | `path:start-end` |
| 数据 | `data` | `json_keys` / `config_keys` / `jsonl_keys` | 顶层键 + 行区间 | `path:start-end` |
| 表格 | `data` | `csv_table` | 列名 | 列名 → 取列 |
| 纯文本 | `text` | `text_chunks` | 200 行分块 | `path:start-end` |
| Office | `office` | `defer_outline` | 调 `~/.dsh/bin/outline` 出段目录 | 段号 |
| 二进制 | `binary` | `binary_summary` | 无（只有 size/sha） | 不读 |

`kind` 决定「值不值得深读」，`adapter` 决定「怎么切」。加一类资产 = 加一个 adapter，
协议不动；这是「泛化到全部」唯一不改调用方的地方。三类边界写在这里，不藏：

- **JS/TS/Ruby 等正则语言只出顶层符号**，类内缩进方法会漏。行号错了比没有更坏，
  所以宁可少给：查不到时用 `grep -n` 拿行号再 `read`。
- **PDF 未覆盖**：outline 直接拒收 PDF（要求先转文本），本工具跟着失败并给 note。
- **二进制只有指纹**，没有骨架——它本来就没有「先骨架后细节」可谈。

## 2. 增量刷新怎么算

```
stat 全部资产（O(n) 次 stat，不读内容）
  ├─ size+mtime 都没变 → 直接复用旧记录（0 次读）
  ├─ 变了 → 算 sha256
  │    ├─ sha 与旧记录相同 → 只更新 mtime（不算重建）
  │    └─ sha 不同        → 重抽这一个文件的骨架
  ├─ 新文件 → 抽
  └─ 消失的文件 → 从索引删
```

读取侧同样先 stat，避免「按旧行号读」：

```
get <file>
  ├─ 文件不存在但索引里有 → 明确报「已删除，跑 refresh」，exit 3（不返回旧骨架）
  ├─ ≤4KB                → 不加载索引，现场抽取，stderr 标 direct-thin
  ├─ 未登记              → 现场抽取，stderr 标 direct-unindexed
  ├─ size/mtime 变了      → 现场抽取，stderr 标 direct-stale（不信旧行号）
  └─ 一致                → 用索引
```

两个必须说清的边界：

- **索引只是缓存**，可随时删。骨架行号在读取时必须由 `read` 现场核对；
  拿索引改文件是禁止动作（行号会漂）。
- **快模式有盲区**：保留 mtime 的同长度改写查不出来。这是刻意的取舍（否则每次
  都要重算全部 sha，增量就没了）。`check --verify-hashes` 补这个盲区，
  机检里有一条测试专门断言「快模式查不出、深检查得出」。

## 3. 代价模型：什么时候才把索引落盘

实测（本仓 239 个资产 / 1,033,241 字节，含本文；机器抖动 ±5%）：

| 指标 | 读数 | 复现 |
|---|---|---|
| 全量重建 | ≈226ms（234.0 / 223.6 / 220.4） | `asset_index.py build` |
| 无变化刷新 | ≈15.7ms（15.4 / 15.7 / 16.0） | `asset_index.py refresh` |
| 改 1 个文件后刷新 | ≈16.5ms，`rebuilt=1 hashed=1 unchanged=238` | 改一行再 `refresh` |
| 进程内拆账 | `load_index` 2.5ms + `walk_assets` 7.5ms | §8 |
| 索引体积 | 150,508 字节 = 语料 14.6%，1,168 节，630 字节/条 | `stats` |
| 骨架 vs 整读 | `docs/SA2.md` 2,292 vs 44,746 字节（19.5×）；大 JSON 391 vs 56,500（144×） | `get \| wc -c` |
| 单次 `get` 固定成本 | ≈50ms（Python 启动占大头）；`cat` 同文件 3.7ms | `/usr/bin/time -p` |
| 小文件占比 | ≤4KB：167 个（70%）、27% 字节；这些文件不落 sections | §8 |

落盘判据（代码只实现第一条，其余是调用方策略）：

1. **代码已实现**：≤4KB 不落 sections（`THIN_BYTES`），`get` 现场算——
   小文件现算比读索引快，写进索引只让索引变大（实测索引占比 20.4% → 14.6%）。
2. 单文件 >50KB：值得落盘，重建时只重抽它一个。
3. office/pdf：抽取贵，落盘；PDF 目前不支持。
4. 一次会话里要读 ≥2 次，或跨会话还要读：先 `build` 一次，之后走增量。

不落盘的单次读：直接 `read`/`cat`，别调 `get`——50ms 启动比 3.7ms 读一个 1KB 文件贵。

## 4. 落地三阶段（每阶段都带能判红的门）

| 阶段 | 交付 | 判据（红=没落地） |
|---|---|---|
| P0 本仓可用 | CLI + 21 条测试 | `python3 -m unittest tests.test_asset_index` 全绿；改 1 个文件后 `rebuilt==1` |
| P1 全局入口 | `~/.dsh/bin/asset-index` + `notes/asset-index.md` 指针 | 任意目录 `~/.dsh/bin/asset-index get <file>` 出骨架 |
| P2 防漂移 | 提交前/CI 跑 `check --verify-hashes` | 手改内容不改 mtime，门必须 exit 1；只有验不了时 exit 4 |

P1 已完成：软链 + 指针；`~/.dsh/bin` 不在 PATH，调用要写全路径。
P2 是策略选择：频繁提交的仓适合 pre-commit，长跑仓适合定时；别两处都放。

## 5. 失效模式与门

| 失效 | 症状 | 门 / 处置 |
|---|---|---|
| 索引过期 | 按旧行号读，读歪一节 | `get` 先 stat，不一致现场重算并标 `direct-stale`；`check` exit 1 |
| mtime 盲区 | 同长改写被漏 | `check --verify-hashes` |
| 索引当真相 | 按骨架改文件，改错行 | 铁律：骨架只导航，改前读原文 |
| 索引膨胀 | 索引接近语料体量 | 已实现 ≤4KB 不落盘；超 40% 先阈值化 |
| 并发刷新 | 两个 agent 互相覆盖 | tmp 名带 pid+随机，`os.replace` 原子替换；4 进程并发测试 |
| 大文件 | >8MB 不算 sha | `check --verify-hashes` 报 `unverified` 并 exit 4（漂移才是 1；`--allow-unverified` 降为 0） |
| 多命中 | `--section 节` 同时命中两节 | 默认打印全部并 exit 1，`--first` 才取第一个 |
| 漏扫 | `.gitignore` 里的产物被索引 | `SKIP_DIRS` 兜住常见目录；自定义产物目录要显式加 |

## 6. 泛化到非文件资产（设计，未实现）

三个动词不变，只换 adapter。这是「泛化到全部」真正的边界测试：

| 资产 | 骨架（list/keys） | 增量 | 细节（有界读） |
|---|---|---|---|
| 数据库 | `information_schema`：表/列/行数 | 只对变更表重算统计 | `WHERE 主键` + `LIMIT` |
| HTTP API | OpenAPI `paths` | 只重取变更的 schema | 单 endpoint + 分页游标 |
| git 历史 | `log --oneline --graph` | 只取新 commit 的 diff | 单 commit / 单文件行区间 |
| 会话记录 | seq + 事件类型索引 | 只解析新 seq | 单事件原文 |

共同形状：**枚举 → 指纹 → 有界读取**。任何「一次拿不完、且会变」的东西都能套，
区别只在指纹用 sha、行数还是 etag。

## 7. 边界与退役条件

- 一次性读（只读一遍、不再回头）：不建索引，直接读——建骨架的钱摊不回来。
- 小于一次 read 上限的文件（≤200 行且 ≤50KB）：直接读，别索引。
- 50ms 的进程启动是固定成本：`get` 适合替代「整读 44KB」，不适合替代 `cat 1KB`。
- 退役触发：连续两周 agent 实际调用为 0，或刷新中位数 >50ms 且阈值化后仍不降，
  删工具、删指针，不留半套。理由和 `read-discipline.md` 记的 `.fat/index`
  负收益是同一个：**没有调用方的索引只是磁盘垃圾**。

## 8. 证据（照抄可复现）

```bash
# 全量 vs 增量
python3 scripts/asset_index.py build     # {"built":239,"elapsed_ms":226}
python3 scripts/asset_index.py refresh   # {"unchanged":239,"rebuilt":0,"elapsed_ms":15.7}

# 索引规模（239 个资产 / 1.03MB 语料）
python3 scripts/asset_index.py stats     # assets=239 index_bytes=150508 sections=1168

# 骨架成本
python3 scripts/asset_index.py get docs/SA2.md | wc -c      # 2292
wc -c docs/SA2.md                                            # 44746

# 进程内拆账
python3 -c "import sys;sys.path.insert(0,'scripts');import asset_index as A,time;from pathlib import Path;r=Path('.').resolve();t=time.perf_counter();[A.load_index(r) for _ in range(5)];print(round((time.perf_counter()-t)/5*1000,2),'ms load')"
python3 -c "import sys;sys.path.insert(0,'scripts');import asset_index as A,time;from pathlib import Path;r=Path('.').resolve();t=time.perf_counter();[A.walk_assets(r) for _ in range(5)];print(round((time.perf_counter()-t)/5*1000,2),'ms walk')"

# 小文件分布（≤4KB 的文件不落 sections）
python3 -c "import sys;sys.path.insert(0,'scripts');import asset_index as A;from pathlib import Path;r=Path('.').resolve();i=A.load_index(r);s=[x for x in i.values() if x['size']<=4096];print(len(s),sum(x['size'] for x in s),sum(len(x['sections']) for x in s))"

# 骨架无条件：删掉索引也要能出骨架
rm -rf .asset-index && python3 scripts/asset_index.py get docs/SA2.md --section 四道过程门
```

全局入口（P1）：

```bash
ln -sf /Users/song/1github/song-agent-1119/scripts/asset_index.py ~/.dsh/bin/asset-index
cd /tmp && ~/.dsh/bin/asset-index get /Users/song/1github/song-agent-1119/README.md | head -5
# 注意：~/.dsh/bin 不在 PATH 上，必须写全路径或 `ln -s ... ~/bin/asset-index`
```

锚点：`scripts/asset_index.py#cmd_refresh` · `scripts/asset_index.py#cmd_get` ·
`tests/test_asset_index.py#test_get_works_without_any_index` ·
`tests/test_asset_index.py#test_metadata_preserving_edit_is_a_documented_blind_spot`