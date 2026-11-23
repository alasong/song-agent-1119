# @local/dsh-asset-index

DSH 工具插件：把「先骨架 → 增量刷新 → 细节」变成模型可直接调用的 `asset_index` 工具。
零第三方依赖：Node 入口只用内置模块，Python 引擎随包自带（`asset_index.py`），
不依赖任何仓库路径。

## 装进一个 profile

```bash
dsh plugin --profile desktop add /Users/song/1github/song-agent-1119/plugins/dsh-asset-index
```

包声明了 `dsh.bundle`，`dsh plugin add` 会把它追加进该 profile 的
`dsh.profile.bundles`；profile 启动时应用 `cordis.patch.yml` 里那一行 loader：

```yaml
- insert:
    - id: asset-index
      name: "@local/dsh-asset-index"
```

卸载：`dsh plugin --profile desktop remove @local/dsh-asset-index`。

## 工具契约

`asset_index`，五个 action：

| action | 行为 | 关键参数 |
|---|---|---|
| `build` | 全量重建 `<root>/.asset-index/` | `root` |
| `refresh` | 增量刷新：stat 判脏，只重算变了的文件 | `root`、`verify_hashes` |
| `get` | 出骨架；带 `section` 时返回 `path:start-end` | `root`、`path`、`section`、`first` |
| `check` | 校验索引与磁盘一致：漂移 exit 1，验不了 exit 4 | `root`、`verify_hashes`、`allow_unverified` |
| `stats` | 资产数、索引体积、节数 | `root` |

`ok` 只在退出码为 0 时为真；`rc=1` 是漂移，`rc=4` 是「有文件验不了」（>8MB 无 sha），不是漂移。
`get` 自己先 stat：文件删了报错、索引过期现场重算、≤4KB 不加载索引直接现算。

## 测试

```bash
node tests 等价入口：node plugins/dsh-asset-index/test.mjs
# 期望：ASSET-INDEX-PLUGIN-TEST 18/18
```

测试不启动 DSH：用假 `ctx` 拿注册表，直接调 `execute`，覆盖 build/refresh/check 的 rc 语义、
`get` 行区间与实物一致、`direct-thin` / `direct-stale` 两条现场抽取路径、无索引也能出骨架。

## 维护

- `asset_index.py` 是 `scripts/asset_index.py` 的副本（插件要自包含）。改引擎后重新 `cp`，
  `test.mjs` 最后一条会比对两者 sha256，漂了就红。
- 插件目录随仓库提交；安装动作只改 profile，不进仓库。