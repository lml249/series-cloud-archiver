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
  --cloud-root /已整理/series \
  --format markdown \
  --output reports/mv3-preview-manifest.md
```

`plan-mv3-preview` 仍然只是读取 JSON 报告并生成下一步清单，不调用 MV3 的 `preview`、`execute` 或 `strm/generate` 接口。它会为每条剧季写出：

- 预计云端目录，例如 `/已整理/series/剧名 {tmdbid=123}/Season 01`
- 需要调用的预览接口：`POST /api/v1/media-transfer/preview`
- 目前缺失的 MV3 `source_library_id`、`source_item_id`、`target_library_id`
- 明确禁止自动调用的执行/删除类接口

只有当 library/item ID 能只读查到、预览接口对单条记录成功、并且人工批准后，才允许进入真正的 `--execute --limit 1` 试运行。

## MV3 115 离线 manifest dry-run

如果 MV3 的 `media-transfer` 取不到 Emby library/item ID，可以改走更贴近 qB 工作流的路线：从 qB 只读读取种子元数据，规划 115 离线任务，再等云端完成后生成 STRM。

```bash
PYTHONPATH=src python3 -m series_cloud_archiver plan-mv3-offline \
  --env-file .env \
  --transfer-plan reports/mv3-transfer-plan.json \
  --instances-report reports/mv3-instances.json \
  --limit 10 \
  --cloud-root /已整理/series \
  --min-seed-days 7 \
  --format markdown \
  --output reports/mv3-offline-manifest.md
```

`plan-mv3-offline` 会只读 qB 的 torrent 列表，匹配待转存剧集，并输出：

- qB 命中多少个种子
- 有多少个种子带 magnet
- 有多少个已经满足做种天数
- 预计的 115 云端目录
- 后续应调用的 MV3 离线接口和 STRM 生成接口模板

报告不会写出 magnet 原文，也不会调用 `/api/v1/files/115/offline/add`、`/api/v1/files/115/offline/add_bt` 或 `/api/v1/strm/generate`。真正执行前仍然需要单条人工批准。

## MV3 115 单条离线添加

`mv3-offline-add-one` 是第一个会真正创建 115 离线任务的命令。它只允许执行 manifest 里的一个 priority，并且必须同时提供 `--approve-offline-add` 和完全匹配的 `--expected-title`。

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-offline-add-one \
  --env-file .env \
  --manifest reports/mv3-offline-manifest-top10.json \
  --priority 5 \
  --expected-title 楚汉传奇 \
  --approve-offline-add \
  --format markdown \
  --output reports/mv3-offline-add-priority5.md
```

第一轮实测故意要求该行只能匹配到 1 个 qB magnet，避免一次把多版本、多分集、多来源批量送进 115。执行结果报告会记录 HTTP 状态、目标云端目录和 MV3 返回内容，但不会写出 magnet 原文。

如果 MV3 返回 `云盘目录不存在`，先用带确认的目录创建命令补齐目标路径：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-ensure-115-path \
  --env-file .env \
  --target-path "/已整理/series/楚汉传奇 {tmdbid=41146}/Season 01" \
  --storage 115-default \
  --approve-create-path \
  --format markdown \
  --output reports/mv3-ensure-path-chuhan.md
```

`mv3-ensure-115-path` 会逐层读取 115 目录；已有目录复用，缺失目录才调用 `/api/v1/files/115/folder` 创建。它不会删除、移动或重命名任何云盘文件。

提交离线任务后，用只读状态命令等待云端完成：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-offline-status-one \
  --env-file .env \
  --info-hash cb0e53779a3abdefac80fb5d9737427ca64dfee6 \
  --target-folder-id 3453239095134780666 \
  --target-path "/已整理/series/楚汉传奇 {tmdbid=41146}/Season 01" \
  --storage 115-default \
  --format markdown \
  --output reports/mv3-offline-status-chuhan.md
```

只有当报告里的 `Ready for STRM` 为 `true` 时，才进入单条 STRM 生成。否则继续等待，不要生成空 STRM。

## qB 临时文件只读审计

qBittorrent 如果开启了“给未完成文件追加扩展名”，未完成文件会显示为 `.!qB`。这不一定代表文件丢失；真正需要区分的是：它是否还被 qB 当前任务引用、任务是否未完成、qB 是否已经报 `missingFiles`。

```bash
PYTHONPATH=src python3 -m series_cloud_archiver qb-dotqb-audit \
  --env-file .env \
  --path-alias /media-qb=/media-host \
  --path-alias /strm-root=/strm-host \
  --scan-root /media-host/TV \
  --scan-root /strm-host/Comic \
  --format json \
  --output reports/qb-dotqb-audit.json
```

`qb-dotqb-audit` 只读取 qB Web API 和宿主机文件列表，不暂停、不校验、不删除任务，也不移动/删除文件。报告会把 `.!qB` 分成：

- `incomplete_task_temp_file`：qB 仍引用该文件，且任务未完成，通常只是正常未完成临时文件。
- `qb_missing_with_dotqb`：qB 已报 missing/error，但对应 `.!qB` 还在，需要人工复核。
- `complete_task_with_dotqb`：qB 认为任务完成，却还有 `.!qB` 后缀文件，通常要先做 qB 重校验或人工确认。
- `orphan_not_in_qb`：当前 qB 文件列表完全匹配不到，才是后续清理候选。

## MoviePilot 内部清理预览

当某部剧已经确认云端 STRM、Emby、本地源文件、hlink 和 qB 做种门禁都通过后，可以先用 MoviePilot 的整理历史生成只读清理预览：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mp-cleanup-preview \
  --env-file .env \
  --title 楚汉传奇 \
  --expected-title 楚汉传奇 \
  --expected-tmdbid 41146 \
  --expected-hash-prefix cb0e53779a3a \
  --format markdown \
  --output reports/mp-cleanup-preview-chuhan.md
```

`mp-cleanup-preview` 只调用 MoviePilot 的 `GET /api/v1/history/transfer`，不会发送删除请求。报告会列出：

- 命中的 MP 整理历史 ID
- 覆盖的集数范围和缺失集
- 对应的 qB hash 前缀和下载器
- 源文件根目录
- hlink 目标根目录
- 如果人工批准，后续会调用的 MP 删除入口：`DELETE /api/v1/history/transfer?deletesrc=true&deletedest=true`

这条 MP 删除入口在 MoviePilot 内部会删除目标媒体文件、删除源文件，并在源文件删除后发出下载文件删除事件；MoviePilot 的下载链会据此从 qBittorrent 移除对应任务。当前命令只做预览，不会删除 qB 任务、种子文件、本地源文件或 hlink。

真正执行必须从预览 JSON 报告进入，并带完整校验项和人工批准开关：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mp-cleanup-execute \
  --env-file .env \
  --preview-report reports/mp-cleanup-preview-chuhan.json \
  --expected-title 楚汉传奇 \
  --expected-tmdbid 41146 \
  --expected-hash-prefix cb0e53779a3a \
  --expected-record-count 80 \
  --expected-episode-count 80 \
  --expected-episode-min 1 \
  --expected-episode-max 80 \
  --approve-mp-cleanup \
  --format markdown \
  --output reports/mp-cleanup-execute-chuhan.md
```

`mp-cleanup-execute` 会在发送任何 DELETE 前重新校验预览报告：标题、TMDB ID、qB hash 前缀、整理历史条数、集数数量、首尾集、缺失集、每条 MP history ID 和删除范围必须全部对上。只要校验失败，就不会发送删除请求。

执行后，用只读核验命令把 MP、qB、本地目录和 STRM 覆盖情况落成报告：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mp-cleanup-verify \
  --env-file .env \
  --title 楚汉传奇 \
  --expected-title 楚汉传奇 \
  --expected-tmdbid 41146 \
  --expected-hash-prefix cb0e53779a3a \
  --source-root "/media/local-source/King.War.S01" \
  --destination-root "/media/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}" \
  --strm-root "/media/cloud-strm/series/楚汉传奇 (2012) {tmdbid=41146}/Season 01" \
  --expected-episode-count 80 \
  --expected-episode-min 1 \
  --expected-episode-max 80 \
  --format markdown \
  --output reports/mp-cleanup-verify-chuhan.md
```

`mp-cleanup-verify` 是只读体检：它确认 MP 整理历史里不再有目标记录、qB 里不再有目标 hash、本地源目录和 hlink 目录已经不存在、STRM 目录仍然覆盖预期集数。它不会删除、移动、生成 STRM，也不会对 qB 发送任何操作。

如果 Emby 里还残留旧本地源，继续触发 Emby 媒体库刷新并核验旧路径是否消失：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver emby-refresh-verify \
  --env-file .env \
  --title 楚汉传奇 \
  --stale-path-prefix "/media/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}" \
  --strm-path-prefix "/media/cloud-strm/series/楚汉传奇 (2012) {tmdbid=41146}" \
  --expected-strm-records 82 \
  --expected-episode-count 80 \
  --expected-episode-min 1 \
  --expected-episode-max 80 \
  --format markdown \
  --output reports/emby-refresh-chuhan.md
```

`emby-refresh-verify` 会调用 Emby 的 `POST /emby/Library/Refresh` 触发媒体库扫描，然后轮询 `RefreshLibrary` 任务，最后确认旧 hlink/local 路径记录为 0、STRM 版本还在且集数完整。它不会删除文件、不会操作 qB、不会调用 MP 清理，也不会直接写 Emby 数据库。

为了精确识别同一部剧的新旧双版本，建议在 `.env` 里配置只读数据库路径：

```bash
EMBY_LIBRARY_DB_PATH=/path/to/emby/library.db
```

如果没有配置 `EMBY_LIBRARY_DB_PATH`，命令会退回 Emby API 搜索核验；这种方式可以用，但在多版本同名剧集上可能被 Emby 搜索结果隐藏旧版本，因此报告会给出提醒。

## MV3 原生资源搜索

MV3 的原生链路不是 qB magnet 离线，而是先搜索网盘资源，再解析分享、转存到 `/未整理`，之后由整理/STRM 流程接手。第一步只做搜索：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-resource-search \
  --env-file .env \
  --keyword 楚汉传奇 \
  --format markdown \
  --output reports/mv3-resource-search-chuhan.md
```

`mv3-resource-search` 只调用 `/api/v1/resource-search/search`，不会解析分享、转存资源、创建离线任务、生成 STRM 或操作 qB。

第二步可以只读预览某个搜索结果里的分享内容：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-share-preview \
  --env-file .env \
  --keyword 楚汉传奇 \
  --selection-index 2 \
  --expected-title-contains 楚汉传奇 \
  --format markdown \
  --output reports/mv3-share-preview-chuhan.md
```

`mv3-share-preview` 会重新搜索、选择第 N 个结果，然后调用 `/api/v1/share-transfer/parse` 和 `/api/v1/share-transfer/browse` 看分享里有哪些文件。它不会调用 `/api/v1/share-transfer/receive`，因此不会把资源转存到 115，也不会整理、生成 STRM 或操作 qB。

确认预览结果后，可以只转存一个浏览条目到 `/未整理`：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-share-receive-one \
  --env-file .env \
  --keyword 楚汉传奇 \
  --selection-index 2 \
  --browse-index 1 \
  --expected-title-contains 楚汉传奇 \
  --target-path /未整理 \
  --storage 115-default \
  --approve-receive \
  --format markdown \
  --output reports/mv3-share-receive-chuhan.md
```

`mv3-share-receive-one` 会重新搜索并预览同一个候选，只在通过标题校验和 `--approve-receive` 时调用 `/api/v1/share-transfer/receive`。它只转存选中的一个分享条目，不会整理、识别媒体类型、生成 STRM、操作 qB 或删除本地文件。

转存完成后，先只读确认 `/未整理` 的云盘目录内容：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-cloud-browse \
  --env-file .env \
  --folder-id 3453317028314611284 \
  --path "/未整理/楚汉传奇 (2012)" \
  --storage 115-default \
  --format markdown \
  --output reports/mv3-cloud-browse-chuhan.md
```

`mv3-cloud-browse` 只调用 `/api/v1/files/cloud/info` 和 `/api/v1/files/cloud/browse`，用于确认目录下真实文件、集数范围和明显断集。它不会整理、移动、生成 STRM 或删除任何东西。

确认目录内容后，再只读扫描 `/未整理` 里的文件，不直接整理：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-organize-scan-source \
  --env-file .env \
  --source-path "/未整理/楚汉传奇 (2012)" \
  --source-file-id 3453317028314611284 \
  --storage 115-default \
  --format markdown \
  --output reports/mv3-organize-scan-chuhan.md
```

`mv3-organize-scan-source` 只调用 `/api/v1/organize/scan-source`。MV3 的接口说明把它描述为“扫描 + 过滤，返回候选媒体文件清单（不做识别、不写盘）”，所以它不会调用 `/api/v1/organize/transfer`、不会移动文件、不会生成 STRM，也不会操作 qB。

确认 `mv3-cloud-browse` 里的集数完整后，才允许调用 MV3 整理转存。这里的 `--target-dir` 必须传 MV3 整理根目录，例如 `/已整理`，不要传 `/已整理/series`；`--strm-dir` 也必须传 STRM 根目录，例如 `/strm`，不要传 `/strm/series`。MV3 在 `enable_primary_category=true` 时会自己补 `series`，否则可能生成重复的 `series/series` 路径。

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-organize-transfer-from-browse \
  --env-file .env \
  --browse-report reports/mv3-cloud-browse-chuhan.json \
  --target-dir "/已整理" \
  --strm-dir "/strm" \
  --tmdb-id 41146 \
  --expected-episode-count 80 \
  --expected-episode-min 1 \
  --expected-episode-max 80 \
  --mode copy \
  --background \
  --approve-transfer \
  --format json \
  --output reports/mv3-organize-transfer-chuhan.json
```

`mv3-organize-transfer-from-browse` 只负责把媒体文件交给 MV3 整理并生成 STRM。云盘媒体文件目录不需要额外刮削、也不应生成旁挂 NFO/JPG；后续只让 MoviePilot/Emby 对 STRM 目录刮削入库。

如果之前误把 `--target-dir` 传成 `/已整理/series`，云盘可能出现 `/已整理/series/series/剧名...` 这种重复 `series` 根目录。可以先用错根目录修复命令 dry-run：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-repair-wrong-root \
  --env-file .env \
  --wrong-root "/已整理/series/series" \
  --correct-root "/已整理/series" \
  --strm-root "/strm-host/mv3/strm/series" \
  --storage 115-default \
  --format json \
  --output reports/mv3-repair-wrong-root-dry-run.json
```

这个命令会同时检查错根云盘目录、正确云盘目录和 STRM 文件目标。默认只出报告，不移动、不删除。只有报告确认无 blocker 后，才可以显式加审批参数：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-repair-wrong-root \
  --env-file .env \
  --wrong-root "/已整理/series/series" \
  --correct-root "/已整理/series" \
  --strm-root "/strm-host/mv3/strm/series" \
  --storage 115-default \
  --approve-move \
  --approve-delete-duplicates \
  --approve-delete-empty \
  --format json \
  --output reports/mv3-repair-wrong-root-execute.json
```

修复规则很保守：重复副本只有在错根和正确根集数一致、且 STRM 没有指向错根时才删；错根媒体只有在正确根缺失或不完整、STRM 指向正确根、并且所有待移动文件都有 115 file id 时才移。它不会调用 MV3 整理转存、不会重新生成 STRM、不会刮削云盘文件、不会操作 qB、MP 或 Emby。

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
