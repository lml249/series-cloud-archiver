# Series Cloud Archiver

中文 | [English](README.en.md)

这是一个用 Spec Kit 驱动的媒体库自动化方案项目，目标是把已经完结的剧集从本地做种盘安全迁移到云盘 STRM 入库，释放本地空间，同时尽量避免误删。

项目当前阶段是 **方案、规格和实现计划**，还不是可直接运行的生产代码。

## 它要解决什么

当订阅的剧集完结后，本地剧集盘会越来越满。这个项目计划实现一套自动化流程：

1. 判断订阅剧集是否已经真正完结。
2. 通过 MV3 在云盘中查找或转存完整可播放版本。
3. 生成 STRM，并刷新 Emby 媒体库。
4. 验证 Emby 里云端 STRM 剧集完整且可播放。
5. 确认原 qBittorrent 任务已经至少做种 7 天。
6. 只有所有安全条件都满足后，才删除本地 torrent 任务、本地内容文件、种子文件和对应 hlink。

## 架构选择

v1 采用 **独立编排器**，而不是纯 MoviePilot 插件。

MoviePilot、Emby、qBittorrent、MediaVault/MV3 和云盘都被视为外部系统。编排器负责保存状态、收集证据、判断是否安全、生成 dry-run 报告和执行清理。

后续可以补一个 MoviePilot 薄插件，但它只负责：

- 触发检查
- 展示状态
- 转发通知
- 打开 dry-run 报告

它不作为最终决策中心，也不直接执行危险删除。

## 第一阶段不做什么

- 不包含生产运行代码。
- 不提交真实媒体库结构、真实路径、真实 IP、token、cookie、pickcode 或 STRM 直链。
- 不允许跳过 dry-run 和验证门禁直接自动删除。
- 不强制云盘版本和本地 release group 完全一致，只要求完整且可播放。

## 安全原则

这个项目默认保守：

- 证据缺失，不删。
- 证据冲突，不删。
- Provider 调用失败，不偷偷继续删。
- 所有清理动作必须可审计、可恢复、可重复执行。
- 默认 dry-run。
- 第一阶段危险操作必须人工批准。

## 当前文档

- [项目宪法](.specify/memory/constitution.md)
- [功能规格](specs/001-series-cloud-archiver/spec.md)
- [实现计划](specs/001-series-cloud-archiver/plan.md)
- [研究决策](specs/001-series-cloud-archiver/research.md)
- [数据模型](specs/001-series-cloud-archiver/data-model.md)
- [适配器契约](specs/001-series-cloud-archiver/contracts/adapter-contracts.md)
- [验证 quickstart](specs/001-series-cloud-archiver/quickstart.md)
- [实现任务](specs/001-series-cloud-archiver/tasks.md)
- [安全策略](docs/security.md)
- [十轮审查记录](docs/ten-pass-review.md)
- [架构决策](docs/architecture.md)

## 验证计划

```bash
bash scripts/validate-plan.sh
```

这个脚本会做公开安全扫描，并重复检查十类关键漏洞：

- 公开仓库卫生
- 独立编排器边界
- 完结判断
- 云端 STRM 验证
- 清理门禁
- 幂等和恢复
- 外部系统适配器边界
- qBittorrent 与 hlink 清理范围
- 可观测性和审计
- 可测试性

## 只读扫描 MVP

当前仓库已经开始加入只读扫描器。它只做候选识别，不转存、不生成 STRM、不删除。

本地试跑：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver scan \
  --media-root /media/local-series \
  --no-qb \
  --min-age-days 0 \
  --format markdown
```

DSM 上可以用本地 `.env` 提供真实路径和服务地址，但 `.env` 不要提交。

如果人工复核确认某批剧季已经完结，可以把确认结果写到独立 JSON 文件，并在 `.env` 里配置：

```bash
ARCHIVER_MANUAL_COMPLETION_FILE=/media/config/manual-completions.json
```

文件格式见 [manual-completions.example.json](examples/manual-completions.example.json)。扫描器会把命中的路径标记为 `manual_completion_confirmed`，这只代表“完结证据已人工确认”，不会跳过后续 MV3、Emby、qB 做种和人工删除审批门禁。

## 编排器第一版

第一版编排器提供 SQLite 状态库和审计记录，但仍然不会执行删除。

```bash
PYTHONPATH=src python3 -m series_cloud_archiver evaluate \
  --media-root /media/local-series \
  --no-qb \
  --min-age-days 0 \
  --db data/series-cloud-archiver.sqlite3

PYTHONPATH=src python3 -m series_cloud_archiver status \
  --db data/series-cloud-archiver.sqlite3 \
  --limit 20

PYTHONPATH=src python3 -m series_cloud_archiver plan-cleanup "Some Series" \
  --db data/series-cloud-archiver.sqlite3
```

`plan-cleanup` 当前只会生成 blocked dry-run 计划。缺少 MV3 STRM 证据、Emby STRM 验证、播放探测、qB 做种时长和人工批准时，删除目标必须为空。

## 云端 STRM 只读检查

完结候选进入下一关时，可以先检查 MV3/云盘已经生成的 STRM 文件是否覆盖预期集数：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver identity-resolve \
  --scan-report reports/volume3-tv-manual-completion-full.json \
  --output data/identity-overrides.json

PYTHONPATH=src python3 -m series_cloud_archiver cloud-check \
  --scan-report reports/volume3-tv-manual-completion-full.json \
  --strm-root /media/cloud-strm \
  --identity-file data/identity-overrides.json \
  --format markdown
```

`identity-resolve` 只调用 MoviePilot 的媒体识别接口补齐 TMDB ID/季号，不触发下载或转存。`cloud-check` 只扫描 `.strm` 文件名里的 `tmdbid`、季号和集号，不读取 STRM 里的直链，也不会触发 MV3 转存、生成 STRM 或删除本地文件。`cloud_strm_complete` 只表示云端 STRM 文件名覆盖预期集数，后续仍要经过 Emby 入库、播放探测、qB 做种和人工审批。

## MV3 转存待办 dry-run

云端 STRM 复核后，可以把 `cloud_strm_not_found` 的项目整理成“待转存清单”：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver plan-mv3-transfer \
  --cloud-report reports/volume3-tv-cloud-strm-check-with-identity-full.json \
  --format markdown \
  --output reports/mv3-transfer-plan.md
```

这一步只读取 `cloud-check` 的 JSON 报告并排序，不调用 MV3，也不生成 STRM。默认只纳入已有 TMDB ID 和季号、但云端完全没有 STRM 的剧集；季号不清的多季合集会继续留在人工复核里。

## MV3 预览 manifest dry-run

拿到待转存清单、MV3 能力报告和 MV3 实例报告后，可以先生成“小批量预览 manifest”：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver plan-mv3-preview \
  --transfer-plan reports/mv3-transfer-plan.json \
  --instances-report reports/mv3-instances.json \
  --capabilities-report reports/mv3-capabilities.json \
  --limit 10 \
  --cloud-root /series \
  --format markdown \
  --output reports/mv3-preview-manifest.md
```

`plan-mv3-preview` 仍然只是读取 JSON 报告并生成下一步清单，不调用 MV3 的 `preview`、`execute` 或 `strm/generate` 接口。它会为每条剧季写出：

- 预计云端目录，例如 `/series/剧名 {tmdbid=123}/Season 01`
- 需要调用的预览接口：`POST /api/v1/media-transfer/preview`
- 目前缺失的 MV3 `source_library_id`、`source_item_id`、`target_library_id`
- 明确禁止自动调用的执行/删除类接口

只有当 library/item ID 能只读查到、预览接口对单条记录成功、并且人工批准后，才允许进入真正的 `--execute --limit 1` 试运行。

## MV3 只读探针

正式接入 MV3 转存前，先确认 MV3 的地址、鉴权方式和可用接口：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-check \
  --env-file .env \
  --format markdown \
  --output reports/mv3-check.md
```

`mv3-check` 只会访问少量 GET 路径，例如 `/openapi.json` 和 `/api/v1/openapi.json`。它不会调用转存、保存、移动、重命名、生成 STRM 或删除接口；如果 `.env` 中还没有 `MV3_BASE_URL`，报告会直接标记为未配置。

## MV3 能力报告

确认 API key 可用之后，可以让编排器读取 MV3 的 OpenAPI，并把接口按风险分组：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-capabilities \
  --env-file .env \
  --format markdown \
  --output reports/mv3-capabilities.md
```

`mv3-capabilities` 只读取 `/openapi.json` 或 `/api/v1/openapi.json`，不会调用真实的转存、接收分享、生成 STRM、移动、重命名、清理或删除接口。报告会把接口分成：

- `Readonly GET`：通常可直接用来确认网盘实例、转存实例、任务状态和历史记录。
- `Preview/Search POST`：看起来像搜索或预览，但因为是 POST，后续仍要逐个验证是否完全无副作用。
- `Transfer/Write POST`：可能创建转存、离线下载、STRM 或其他写入任务，必须等人工批准后才能接入。
- `Destructive/Cleanup`：可能删除、清空、移动、重命名、取消或清理，默认永远不会自动调用。

这份报告的作用是先把 MV3 能做什么讲清楚，再决定第一批只读查询和第一条 `--execute --limit 1` 试运行该怎么设计。

## MV3 实例只读探测

能力报告确认接口存在后，可以读取 MV3 当前配置了哪些网盘实例、转存实例、媒体库、STRM 配置和任务状态：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-instances \
  --env-file .env \
  --timeout 30 \
  --retry-failed-once \
  --format markdown \
  --output reports/mv3-instances.md
```

`mv3-instances` 只调用 GET 接口。默认读取：

- `/api/v1/cloud-drive/instances`
- `/api/v1/media-transfer/instances`
- `/api/v1/media-transfer/libraries`
- `/api/v1/media-transfer/status`
- `/api/v1/media-transfer/records?page=1&page_size=5`
- `/api/v1/strm/config`
- `/api/v1/strm/generate/status`
- `/api/v1/strm/records/dirs`
- `/api/v1/strm/records/stats`
- `/api/v1/files/115/offline/quota`
- `/api/v1/files/115/offline/tasks`

报告样本会自动打码 token、cookie、password、pickcode、key 类字段和 URL 类字段。它的目的只是搞清楚“下一步转到哪里、用哪个实例、STRM 输出在哪里”，不会创建转存任务，也不会生成 STRM 或清理本地文件。
