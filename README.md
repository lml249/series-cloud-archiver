# Series Cloud Archiver

中文 | [English](README.en.md)

这是一个用 Spec Kit 驱动的媒体库自动化方案项目，目标是把已经完结的剧集从本地做种盘安全迁移到云盘 STRM 入库，释放本地空间，同时尽量避免误删。

项目当前已经包含可运行的保守编排命令，但危险动作仍然默认 dry-run，并且必须拿到明确验证报告和人工审批参数后才会执行。

## 最重要的边界

云盘实体目录只做两件事：**转存资源** 和 **生成 STRM**。

所有识别、刮削、NFO、海报和 Emby 入库都必须发生在 STRM 媒体库路径上，不能对 `/已整理`、`/未整理` 这类云盘实体目录做刮削。裸 `/series/...` 也不算 STRM 媒体库路径；STRM 侧路径应明确位于 `/strm`、`.../mv3/strm`、`cloud-strm` 或类似 STRM 根下。项目会阻断把非 STRM 侧路径传给 Emby 刷新/刮削或 STRM NFO 语言审计的命令，并在整理转存时排除 `.nfo/.jpg/.jpeg/.png/.webp` 这类元数据旁挂。

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

## 当前阶段不做什么

- 不做无人值守的危险删除；所有写操作都要有明确审批参数。
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
- 危险操作必须人工批准。

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
  --scan-report reports/local-tv-manual-completion-full.json \
  --output data/identity-overrides.json

PYTHONPATH=src python3 -m series_cloud_archiver cloud-check \
  --scan-report reports/local-tv-manual-completion-full.json \
  --strm-root /media/cloud-strm \
  --identity-file data/identity-overrides.json \
  --format markdown
```

`identity-resolve` 只调用 MoviePilot 的媒体识别接口补齐 TMDB ID/季号，不触发下载或转存。`cloud-check` 只扫描 `.strm` 文件名里的 `tmdbid`、季号和集号，不读取 STRM 里的直链，也不会触发 MV3 转存、生成 STRM 或删除本地文件。`cloud_strm_complete` 只表示云端 STRM 文件名覆盖预期集数，后续仍要经过 Emby 入库、播放探测、qB 做种和人工审批。

如果已经有 `cloud-check` 报告，并且只想补里面的 `needs_identity_review` 条目，可以直接让 `identity-resolve` 读取 cloud 报告。这样不会把标题里已经带 `{tmdbid=...}` 的普通条目重新丢给 MoviePilot 识别：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver identity-resolve \
  --env-file /example/app/series-cloud-archiver/.env \
  --cloud-report /example/app/series-cloud-archiver/outputs/current-20260629/cloud-check-current.json \
  --output /example/app/series-cloud-archiver/outputs/current-20260629/identity-overrides-current.json
```

## MV3 转存待办 dry-run

云端 STRM 复核后，可以把 `cloud_strm_not_found` 的项目整理成“待转存清单”：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver plan-mv3-transfer \
  --cloud-report reports/local-tv-cloud-strm-check-with-identity-full.json \
  --format markdown \
  --output reports/mv3-transfer-plan.md
```

这一步只读取 `cloud-check` 的 JSON 报告并排序，不调用 MV3，也不生成 STRM。默认只纳入已有 TMDB ID 和季号、但云端完全没有 STRM 的剧集；季号不清的多季合集会继续留在人工复核里。

如果 MV3 暂时可达但授权未恢复，可以把当前缺 STRM 的队列、需要身份复核的条目、历史候选样例和 MV3 授权状态汇总成一个可复跑的恢复队列报告：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-restored-transfer-queue \
  --cloud-report reports/cloud-check-current.json \
  --transfer-plan reports/mv3-transfer-plan.json \
  --historical-scan reports/local-tv-bulk-precleanup-scan.json \
  --mv3-report reports/mv3-check.json \
  --format markdown \
  --output reports/mv3-restored-transfer-queue.md
```

`mv3-restored-transfer-queue` 只是只读汇总，不搜索、不转存、不生成 STRM、不刷新 Emby、不清理 qB/MP/hlink。它的用途是等 MV3 授权恢复后，按“已有 TMDB ID + 明确季号 + 云端 STRM 未找到”的队列继续逐条搜索和转存。

## 推荐入口：批量流水线 state machine

现在优先使用 `batch-pipeline`，不要再把 `batch-plan`、`batch-share-preview`、`batch-share-receive-plan`、`batch-transfer-run`、`batch-finalize-plan`、`batch-finalize-run` 手工一条条串起来。`batch-pipeline` 会把这些阶段统一编排到一个运行目录里，每一步都写 JSON 报告，最后生成 `00-pipeline-state.json`。后续排错、复跑和人工复核都从这些报告继续。

默认模式只生成计划、预览计划、接收计划、finalize 计划和人工复核报告；不会搜索 MV3、不会接收分享、不会整理、不会刮削、不会刷新 Emby、不会删除 qB/hlink/source：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver batch-pipeline \
  --env-file /example/app/series-cloud-archiver/.env \
  --cloud-report /example/app/series-cloud-archiver/outputs/current-20260629/cloud-check-rescan-identity-062228a-20260630.json \
  --transfer-plan /example/app/series-cloud-archiver/outputs/current-20260629/mv3-transfer-plan-rescan-identity-062228a-20260630.json \
  --share-search-plan /example/app/series-cloud-archiver/outputs/current-20260629/share-search-identity-062228a-rows07-17-20260630.json \
  --review-report /example/app/series-cloud-archiver/outputs/current-20260629/batch-review-latest.json \
  --output-dir /example/app/series-cloud-archiver/outputs/current-20260629/pipeline-runs \
  --run-id dry-run-YYYYMMDD \
  --cloud-root /已整理/series \
  --mv3-strm-root /strm \
  --host-strm-root /example/host/strm \
  --mp-strm-root /example/moviepilot/strm \
  --emby-strm-root /example/service/strm \
  --forbidden-target-prefix /series/series \
  --forbidden-target-prefix /已整理/series/series \
  --format json \
  --output /example/app/series-cloud-archiver/outputs/current-20260629/pipeline-runs/dry-run-YYYYMMDD.json
```

如果没有现成报告，也可以让它从媒体库根开始生成前置报告：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver batch-pipeline \
  --env-file /example/app/series-cloud-archiver/.env \
  --media-root /example/local-tv \
  --strm-root /example/host/strm \
  --identity-file /example/app/series-cloud-archiver/outputs/current-20260629/identity-overrides-current.json \
  --output-dir /example/app/series-cloud-archiver/outputs/current-20260629/pipeline-runs \
  --run-id scan-dry-run-YYYYMMDD \
  --cloud-root /已整理/series \
  --mv3-strm-root /strm \
  --host-strm-root /example/host/strm \
  --mp-strm-root /example/moviepilot/strm \
  --emby-strm-root /example/service/strm \
  --format json \
  --output /example/app/series-cloud-archiver/outputs/current-20260629/pipeline-runs/scan-dry-run-YYYYMMDD.json
```

`batch-pipeline` 的审批闸门是分层的：

- 默认分享预览计划会同时覆盖 `auto_ready_for_transfer_preview` 和可预览的 `manual_review` 条目；可以用 `--preview-bucket` 缩小范围。
- `--execute-share-search`：实际调用 MV3 资源搜索，只读，不转存。
- `--execute-preview`：实际解析分享并 browse，只读，不转存。
- `--run-transfer-stage --preflight-staging`：只读检查每个接收计划的预期 staging 目录，不接收分享、不整理云盘，适合每批执行前确认 `/未整理/...` 没有残留冲突。
- `--run-transfer-stage --approve-receive`：允许把预览完整的分享接收到 `/未整理`。
- `--run-transfer-stage --approve-transfer`：允许交给 MV3 整理到 `/已整理` 并生成 STRM。
- `batch-transfer-run` 在真正接收前会只读检查 `receive-plan` 里的 `expected_staging_path`，例如 `/未整理/Season 1`。如果该 staging 路径已经存在、含视频、含文件或含子目录，runner 会停在 `failed_staging_preflight`，不会调用分享接收，避免和之前半完成的 MV3 转存残留混在一起。
- 转存整理后，runner 会只读检查 `--host-strm-root` 下的预期 `series/...` STRM 输出，并阻断误落到 `未识别/...` 的条目；这类条目不能进入刮削、Emby 或本地清理。
- `--run-finalize-stage --execute-scrape`：只对 STRM 路径请求 MoviePilot 刮削。
- `--approve-cloud-duplicate-delete`：只在 STRM 保护目标完整时删云盘重复视频。
- `--approve-emby-stale-delete`：只在 STRM 替代完整时删 Emby 旧本地条目。
- `--approve-delete`：最后才允许 qB/hlink/source 清理。

如果某个剧季虽然门禁看起来满足，但因为人工原因必须保留本地，例如“当前云盘版本没有中文字幕”，请写一个本地排除清单并在批量命令里带上 `--manual-exclusion-file`。格式参考 [manual-exclusions.example.json](examples/manual-exclusions.example.json)；真实清单文件名建议用 `manual-exclusions.local.json` 或放在 `outputs/` 下，默认会被 Git 忽略。命中排除项后，`batch-plan` 会把该剧季标成 `manual_exclusion`，`batch-finalize-plan/run` 不会生成或执行清理动作：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver batch-pipeline \
  --env-file .env \
  --manual-exclusion-file outputs/series-cloud-archiver/manual-exclusions.local.json \
  ...
```

目录角色不能混用：`--cloud-root` 是计划用的 `/已整理/series`，`--organize-target-dir` 必须是 `/已整理`，`--transfer-target-path` 必须在 `/未整理` 下，`--mv3-strm-root`/`--host-strm-root`/`--mp-strm-root`/`--emby-strm-root` 必须是 STRM 侧路径。`--host-strm-root` 是脚本所在机器看到的 STRM 路径，`--mp-strm-root` 是 MoviePilot 容器看到的 STRM 路径，`--emby-strm-root` 是 Emby 容器/库里看到的 STRM 路径；三者可以不同。云盘实体目录只做转存和生成 STRM，NFO/JPG/Emby 入库验证都只在 STRM 侧跑。

继续跑后续小批搜索/预览时，建议把最新 `batch-review-report` 用 `--review-report` 传给 `batch-pipeline` 或 `batch-share-preview`。预览 runner 会按 TMDB ID + 季号跳过已经是 `manual_review_transfer_failed`、`manual_review_preview_blocked`、`blocked_after_finalize_gates`、`skipped_manual_exclusion` 等决策的条目，避免把半完成转存、缺集预览或清理阻断项反复排回可执行预览队列。这个过滤只影响只读预览计划，不会接收分享、整理云盘、刮削、刷新 Emby 或删除本地。

输出目录里最重要的文件：

- `05-batch-plan.json`：分桶结果，决定哪些能自动预览、哪些要人工复核。
- `06-share-preview.json`：分享预览计划或执行结果。
- `07-receive-plan.json`：审批门控的接收计划。
- `08-transfer-run.json`：如果跑了转存整理阶段，这里记录接收、整理、后置核验结果。
- `12-finalize-plan.json`：STRM/NFO/Emby/qB/MP 清理前门禁计划。
- `13-finalize-run.json`：如果跑了 finalize 阶段，这里记录每个门禁的结果。
- `14-review.json`：合并人工复核报告。
- `15-extra-source-media-plan.json`：如果 finalize 被“源目录有额外视频但 hlink 未覆盖”阻断，这里会列出这些额外视频的 MV3 只读扫描命令和人工映射要求。
- `00-pipeline-state.json`：整次运行的索引和摘要。

如果 `08-transfer-run.json` 里出现整理超时、`strm_written_to_unrecognized_root`、staging 残留，或者云端媒体/STRM 被拆到多个目录，先用只读诊断命令固化现场，不要直接修目录或清理本地：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-transfer-remediation-plan \
  --transfer-run-report /example/app/outputs/current/pipeline-runs/RUN_ID/08-transfer-run.json \
  --cloud-report /example/app/outputs/current/failed-season-cloud-browse-a.json \
  --cloud-report /example/app/outputs/current/failed-season-cloud-browse-b.json \
  --host-strm-root /example/host/strm \
  --expected-tmdbid 286997 \
  --expected-season 2 \
  --expected-episode-count 30 \
  --expected-episode-min 1 \
  --expected-episode-max 30 \
  --format json \
  --output /example/app/outputs/current/failed-season-transfer-remediation-plan.json
```

`mv3-transfer-remediation-plan` 只读取 transfer-run、云端 browse/search 报告和本机 STRM 文件，输出云端分段、STRM 分段、集数覆盖和阻断原因。它不会移动云端媒体、生成或改写 STRM、刮削、刷新 Emby、操作 qB，也不会删除 hlink/source/本地文件。只要报告里还有 `cloud_media_split_across_multiple_roots`、`strm_split_across_multiple_roots`、`staging_media_still_present` 或 `unrecognized_root_present`，该剧季必须留在人工复核，不能进入 finalize/cleanup。

如果最新 `batch-review-report` 中已有 `manual_review_transfer_failed`，且阻断原因明确是 `strm_written_to_unrecognized_root`，可以先生成批量错根修复计划。这个计划只消费现有 review 报告，默认只输出 dry-run 命令，不转存、不整理、不刮削、不刷新 Emby，也不删除本地：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-transfer-wrong-root-repair-plan \
  --review-report /example/app/outputs/current/manual-review-latest.json \
  --env-file /example/app/series-cloud-archiver/.env \
  --cloud-media-storage 115-default \
  --format json \
  --output reports/mv3-transfer-wrong-root-repair-plan.json
```

计划只挑选 `manual_review_transfer_failed + strm_written_to_unrecognized_root`，并且要求云盘路径在 `/已整理/未识别/.../Season N`、STRM 路径在 STRM 侧 `未识别/.../Season N`。它会把云盘目标推导为 `/已整理/series/.../Season NN`，把 STRM 目标推导为同一 host STRM 根下的 `series/.../Season N`。无推荐候选、缺 STRM、非 `/未识别`、路径不成季目录、集数缺预期的条目仍然留人工复核。

每批先跑 dry-run runner。它只实际执行 `mv3-repair-wrong-root-direct-season-pair` 的无审批 dry-run，用来确认云盘错根媒体、正确目标空位、STRM target rewrite 预览和集数都一致；STRM 根迁移步骤会先标成 deferred，因为必须等云盘移动和 STRM target rewrite 成功后再复核：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-transfer-wrong-root-repair-run \
  --plan reports/mv3-transfer-wrong-root-repair-plan.json \
  --output-dir reports/mv3-transfer-wrong-root-repair-diagnostics \
  --limit 2 \
  --execute-dry-run \
  --format json \
  --output reports/mv3-transfer-wrong-root-repair-dry-run.json
```

只有 dry-run 全绿后，才可以小批量执行 approved runner：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-transfer-wrong-root-repair-run \
  --plan reports/mv3-transfer-wrong-root-repair-plan.json \
  --output-dir reports/mv3-transfer-wrong-root-repair-diagnostics-approved \
  --limit 2 \
  --execute-approved \
  --format json \
  --output reports/mv3-transfer-wrong-root-repair-execute.json
```

approved runner 的顺序是固定的：先给单项错根修复命令加 `--approve-repair`，让它创建正确云盘季目录、移动错根媒体、重写 STRM target；成功后立即跑一次 `strm-root-relocate` dry-run，确认 STRM 文件已指向 `/已整理/series/...` 且不再指向 `/已整理/未识别/...`；最后才给 STRM 侧根迁移加 `--approve-move`。如果第一步或第二步失败，后续步骤会 dependency-skipped。这个 runner 不会刮削云盘实体目录，不会触发 MoviePilot/Emby/qB，也不会删除 hlink/source；修复后必须重新生成 batch/finalize/review 报告，再走 STRM/NFO/Emby/qB/MP 清理前门禁。

如果 `13-finalize-run.json` 出现 `source_root_check_failed`，不要直接删除源目录。通常意思是 qB 源目录里还有 hlink 没覆盖的视频，例如 SP、making-of、花絮或错季文件。`batch-pipeline` 会自动生成 `15-extra-source-media-plan.json`；也可以单独重跑：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver extra-source-media-plan \
  --finalize-run-report /example/app/series-cloud-archiver/outputs/current-20260629/pipeline-runs/RUN_ID/13-finalize-run.json \
  --env-file /example/app/series-cloud-archiver/.env \
  --target-dir /已整理 \
  --strm-dir /strm \
  --format json \
  --output reports/extra-source-media-plan.json
```

这个计划仍然只读：它只把额外视频整理成 `mv3-organize-scan-source --local-source --file` 命令。像 `SP1/SP2` 这种特辑不会自动假设成 `Season 00` 的第几集，必须先确认 TMDB Season 00 的映射，再进入转存、生成 STRM、STRM 侧刮削和 Emby 验证。

如果 `13-finalize-run.json` 里某一季是 `already_cleaned_noop`，表示 STRM、NFO、Emby 和云盘侧检查已经通过，同时扫描报告里的完整 qB hash 已确认不在 qB，source/hlink 根也没有视频可删。这个状态不会执行 qB 删除或文件删除，只是把“本地早已清完”的季节从失败项中摘出来，避免后续批量复跑时反复卡在已经不存在的本地目录。

如果 `batch-review-report` 里还有 `blocked_after_finalize_gates`，先生成统一的只读修复计划，再用 runner 按类别批量收集诊断证据。默认 runner 仍然只 dry-run，不执行诊断命令：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver finalize-remediation-plan \
  --review-report /example/app/series-cloud-archiver/outputs/current-20260629/pipeline-runs/batch-review.json \
  --finalize-run-report /example/app/series-cloud-archiver/outputs/current-20260629/pipeline-runs/RUN_ID/13-finalize-run.json \
  --env-file /example/app/series-cloud-archiver/.env \
  --format json \
  --output reports/finalize-remediation-plan.json

PYTHONPATH=src python3 -m series_cloud_archiver finalize-remediation-run \
  --plan reports/finalize-remediation-plan.json \
  --output-dir reports/finalize-remediation-diagnostics \
  --category strm_mismatch \
  --format json \
  --output reports/finalize-remediation-run.json
```

确认只读计划后，才加 `--execute-readonly` 批量执行允许列表里的诊断命令。runner 只接受 `strm-verify`、`strm-nfo-language-audit`、`emby-media-updated` 局部 STRM 路径通知/验证、`mv3-cloud-duplicate-video-cleanup` dry-run、`mv3-cloud-browse`、`mv3-cloud-search`、`qb-orphan-torrent-cleanup-preview`、`mp-cleanup-preview` 这类只读/预览命令；它会把每条命令的输出强制写到 `--output-dir`，并阻断任何 `--approve-*` 审批参数。它不会转存、整理、生成 STRM、刮削、触发 Emby 全库扫描、删除云盘文件、删除 qB、删除 hlink 或删除 source。

如果类别是 `emby_strm_mismatch`，修复计划会先复核 STRM 集数和中文 NFO，再只把 Emby 容器看到的 STRM 侧路径传给 `emby-media-updated` 做局部通知和验证。这个类别不能使用 `/已整理`、`/未整理` 或裸 `/series` 云盘实体路径；只要 Emby 仍看不到完整集数，就继续保留在 finalize 阻断项，不能进入清理审批。

如果 `strm_mismatch` 的诊断显示“不是缺集，而是 STRM 和云盘实际集数都比旧预期更多”，不要手工改 finalize 计划。先让项目从诊断目录生成只读的预期集数修正建议：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver finalize-remediation-expected-update-plan \
  --plan reports/finalize-remediation-plan.json \
  --diagnostic-dir reports/finalize-remediation-diagnostics \
  --format json \
  --output reports/finalize-remediation-expected-update-plan.json
```

只有当输出行是 `ready_for_expected_update`，才说明 STRM 和 MV3 云盘季目录集数一致、连续、无缺口、无重复、STRM target 前缀正确，可以把报告里的 `identity_overrides` 作为新的预期集数证据，重新生成 cloud/batch/finalize 计划并重跑门禁。这个命令本身只读，不会改原计划，不会调用 MV3/MP/Emby/qB，也不会删除任何文件。

下面保留的散命令仍然可用，主要用于调试单个阶段、修复异常项，或者在 pipeline 缺少某个能力时作为构件使用。

## 批量状态计划 dry-run

当已经有扫描、云端 STRM 检查、转存待办和 MV3 分享搜索评分报告后，可以先生成一份批量状态计划。它不会调用 MV3 搜索、转存、整理、生成 STRM，不会触发 MoviePilot 刮削或 Emby 刷新，也不会操作 qB、hlink、source 或本地文件系统；它只把现有证据分桶：

- `auto_ready_for_transfer_preview`：资源搜索评分、集数和体积相似度都够好，可以进入单条预览和转存审批门。
- `auto_ready_for_validation_cleanup`：云端 STRM 已经覆盖预期集数，可以进入 STRM/NFO/Emby/qB/MP 清理前验证。
- `manual_review`：身份、集数、体积、路径或资源候选证据不够稳，需要人工复核。
- `skipped`：当前状态不属于迁移流程。

DSM 上用现有报告生成只读计划：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver batch-plan \
  --env-file /example/app/series-cloud-archiver/.env \
  --scan-report /example/app/series-cloud-archiver/outputs/current-20260629/local-tv-scan-current-20260629.json \
  --cloud-report /example/app/series-cloud-archiver/outputs/current-20260629/hlink-tv-cloud-check-rescan-noqb-identity-20260627.json \
  --transfer-plan /example/app/series-cloud-archiver/outputs/current-20260629/mv3-transfer-plan-season-split-safe-20260629.json \
  --share-search-plan /example/app/series-cloud-archiver/outputs/current-20260629/share-search-season-safe-rows21-38-20260629.json \
  --share-search-plan /example/app/series-cloud-archiver/outputs/current-20260629/share-search-season-safe-rows39-59-20260629.json \
  --cloud-root /已整理/series \
  --mv3-strm-root /strm \
  --host-strm-root /example/host/strm \
  --emby-strm-root /example/service/strm \
  --forbidden-target-prefix /series/series \
  --forbidden-target-prefix /已整理/series/series \
  --format json \
  --output /example/app/series-cloud-archiver/outputs/current-20260629/batch-plan-YYYYMMDD.json
```

`--share-search-plan` 可以重复传多份，适合把分段搜索出来的 `rows21-38`、`rows39-59` 等报告合并成同一份批量计划。输出里的 `next_actions` 是阶段模板，不会自动带 `--approve-receive`、`--approve-transfer`、`--approve-delete`、`--approve-mp-cleanup` 这类审批参数。真正批量执行阶段必须先从这份只读计划进入，并继续保留每一关的验证报告。

如果只是想给人工复核看，也可以把同一条命令的 `--format json` 改成 `--format csv`，输出会平铺出剧名、TMDB、季号、集数、复核原因、推荐资源、清理预览阻断和本地路径。

更推荐在每批 dry-run 或执行后生成一份合并人工复核表。`batch-review-report` 只读取已有 JSON 报告，不重新扫描全库，不调用 MV3/MP/Emby/qB，也不会写云盘或删除本地文件。它会把 `batch-plan`、只读分享预览结果、转存整理 runner 结果、finalize 运行结果，以及可重复传入的 `--post-cleanup-report` 清理后证据报告合并，给每个剧季写出 `decision`、`next_action`、候选资源、缺失集、转存失败阶段、清理失败阶段和阻断原因：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver batch-review-report \
  --batch-plan /example/app/series-cloud-archiver/outputs/current-20260629/batch-plan-YYYYMMDD.json \
  --share-preview-report /example/app/series-cloud-archiver/outputs/current-20260629/batch-share-preview-executed-YYYYMMDD.json \
  --transfer-run-report /example/app/series-cloud-archiver/outputs/current-20260629/batch-transfer-run-YYYYMMDD.json \
  --finalize-run-report /example/app/series-cloud-archiver/outputs/current-20260629/batch-finalize-run-YYYYMMDD.json \
  --post-cleanup-report /example/app/series-cloud-archiver/outputs/current-20260629/orphan-hlink-execute-YYYYMMDD.json \
  --format csv \
  --output /example/app/series-cloud-archiver/outputs/current-20260629/batch-review-YYYYMMDD.csv
```

`--post-cleanup-report` 可以接 `cloud-hlink-cleanup-execute`、`cloud-hlink-orphan-cleanup-execute`、`qb-orphan-torrent-cleanup-preview`、`no-hash-local-absent-verify`、`mp-cleanup-verify`、`strm-verify`、`strm-nfo-language-audit`、`emby-media-updated` 等 JSON 报告；只有 qB、hlink/source、STRM、中文 NFO、Emby 这些门禁证据合并后全部为绿，复核表才会标成 `done_cleanup_verified`。

常见 `decision` 含义：

- `ready_for_share_preview`：可以进入只读分享预览，但还不能转存。
- `ready_for_receive_plan`：分享预览已证明完整，可以生成接收计划并等待显式审批。
- `manual_review_transfer_failed`：分享预览通过，但接收、整理或 STRM 生成阶段失败；常见原因是 115 分享过期或 MV3 整理未完成。不要清理本地，先换分享源或重新搜索。
- `ready_for_finalize_gates`：云端 STRM 已完整，可以跑 STRM/NFO/Emby/qB/MP 清理前门禁。
- `blocked_after_finalize_gates`：STRM/NFO/Emby 等前置门禁可能已过，但清理前验证失败，必须处理阻断原因后重跑。
- `manual_review_required` / `manual_review_preview_blocked`：证据不足、缺集、错季、错剧或体积异常，需要人工复核。

如果要把复核表里某一类状态切成下一阶段批量计划，可以用只读过滤器。它支持标准 `batch-review-report` 的 `decision` 字段，也支持全局覆盖汇总表里的 `coverage` / `review_decision` 字段：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver batch-plan-filter \
  --batch-plan /example/app/series-cloud-archiver/outputs/current-20260629/05-batch-plan.json \
  --review-report /example/app/series-cloud-archiver/outputs/current-20260629/batch-review-YYYYMMDD.json \
  --decision ready_for_finalize_gates \
  --format json \
  --output /example/app/series-cloud-archiver/outputs/current-20260629/ready-finalize-plan-YYYYMMDD.json
```

这个命令只筛选计划，不调用 MV3/MP/Emby/qB，也不会写云盘或删除本地文件。

## 批量 MV3 分享预览 dry-run

如果批量计划里大量条目只是卡在 `episode_coverage_unclear`，说明 MV3 搜索结果标题无法证明集数完整，但分享内部可能是完整剧集。可以让编排器从 `batch-plan` 中自动挑选候选，批量生成只读分享预览计划：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver batch-share-preview \
  --env-file /example/app/series-cloud-archiver/.env \
  --batch-plan /example/app/series-cloud-archiver/outputs/current-20260629/batch-plan-YYYYMMDD.json \
  --limit 10 \
  --format json \
  --output /example/app/series-cloud-archiver/outputs/current-20260629/batch-share-preview-plan-YYYYMMDD.json
```

默认模式不会读取 MV3 API，也不会解析分享；它只输出将要预览的 `mv3-share-preview` 命令。默认只选择“最佳候选分数够高，且唯一阻断是 `episode_coverage_unclear`”的条目；错季、标题不匹配、体积明显不对、疑似中文副标题串剧的候选会继续跳过并写入原因。

确认 dry-run 计划后，可以执行只读预览：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver batch-share-preview \
  --env-file /example/app/series-cloud-archiver/.env \
  --batch-plan /example/app/series-cloud-archiver/outputs/current-20260629/batch-plan-YYYYMMDD.json \
  --execute-preview \
  --preview-output-dir /example/app/series-cloud-archiver/outputs/current-20260629/share-preview-batch \
  --limit 10 \
  --format json \
  --output /example/app/series-cloud-archiver/outputs/current-20260629/batch-share-preview-executed-YYYYMMDD.json
```

`batch-share-preview --execute-preview` 仍然只调用 MV3 的搜索、分享解析和 browse 预览接口，不会调用 `/api/v1/share-transfer/receive`，不会转存到 115，不会整理、生成 STRM、刮削、刷新 Emby，也不会操作 qB、hlink、source 或本地文件。只有预览报告证明集数完整的条目，才允许进入后续“接收到 `/未整理` -> MV3 整理到 `/已整理` -> 生成 STRM -> STRM 侧刮削/验证”的阶段。

## 批量 MV3 接收与整理 runner

分享预览通过后，先生成审批门控的接收计划：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver batch-share-receive-plan \
  --env-file /example/app/series-cloud-archiver/.env \
  --batch-share-preview-report /example/app/series-cloud-archiver/outputs/current-20260629/batch-share-preview-executed-YYYYMMDD.json \
  --target-path /未整理 \
  --format json \
  --output /example/app/series-cloud-archiver/outputs/current-20260629/batch-share-receive-plan-YYYYMMDD.json
```

然后交给批量 runner。默认不接收、不整理，只报告需要审批的项目：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver batch-transfer-run \
  --env-file /example/app/series-cloud-archiver/.env \
  --receive-plan /example/app/series-cloud-archiver/outputs/current-20260629/batch-share-receive-plan-YYYYMMDD.json \
  --output-dir /example/app/series-cloud-archiver/outputs/current-20260629/batch-transfer-run-stages \
  --format json \
  --output /example/app/series-cloud-archiver/outputs/current-20260629/batch-transfer-run-YYYYMMDD.json
```

确认计划后，才分阶段显式审批：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver batch-transfer-run \
  --env-file /example/app/series-cloud-archiver/.env \
  --receive-plan /example/app/series-cloud-archiver/outputs/current-20260629/batch-share-receive-plan-YYYYMMDD.json \
  --output-dir /example/app/series-cloud-archiver/outputs/current-20260629/batch-transfer-run-stages \
  --title 折腰 \
  --approve-receive \
  --approve-transfer \
  --target-path /未整理 \
  --organize-target-dir /已整理 \
  --strm-dir /strm \
  --format json \
  --output /example/app/series-cloud-archiver/outputs/current-20260629/batch-transfer-run-approved-YYYYMMDD.json
```

`batch-transfer-run` 只处理 `batch-share-receive-plan` 中 `approval_required` 的条目。`--approve-receive` 只允许把已验证完整的分享接收到 `/未整理`；`--approve-transfer` 才允许把已收到的云盘目录交给 MV3 整理到 `/已整理` 并生成 STRM。MV3 整理请求返回后，runner 还会再做只读后置核验：确认 `/已整理/series/.../Season N` 里只有期望集数、没有重复集、没有 NFO/JPG/海报等刮削旁挂，并确认 `/未整理` staging 源不再残留视频。如果 MV3 自动把目录命名成 `剧名 (年份) {tmdbid=...}`，runner 会优先按 TMDB ID 在 `/已整理/series` 下解析真实目录。任一门禁失败都会停在 `failed_post_organize_verify`，不能进入后续刮削或清理。

它不会刮削云盘实体目录，不会刷新 Emby，不会操作 qB，也不会删除 hlink/source。本地清理必须等后续 `batch-finalize-run` 的 STRM、中文 NFO、Emby、qB/MP/hlink/source 门禁全部通过后再单独审批。

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
  --strm-root /strm \
  --min-seed-days 7 \
  --format markdown \
  --output reports/mv3-offline-manifest.md
```

`plan-mv3-offline` 会只读 qB 的 torrent 列表，匹配待转存剧集，并输出：

- qB 命中多少个种子
- 有多少个种子带 magnet
- 有多少个已经满足做种天数
- 预计的 115 云端目录
- 后续应调用的 MV3 离线接口和 STRM 生成接口模板。STRM 生成模板里的 `source_dir` 是云盘媒体目录，`target_dir` 必须是 STRM 侧根目录，不能写成 `/已整理/...`

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

如果一次清理已经通过别的安全路径删掉了 qB、源目录和 hlink，只剩 MoviePilot 整理历史记录没有收口，可以显式使用 record-only 模式。它仍然必须先做预览，并且必须同时保留源文件和目标文件开关：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mp-cleanup-preview \
  --env-file .env \
  --title 示例剧名 \
  --expected-title 示例剧名 \
  --expected-tmdbid 100000 \
  --expected-hash-prefix abcdef123456 \
  --expected-season 1 \
  --keep-source \
  --keep-dest \
  --record-only \
  --format json \
  --output reports/mp-record-only-preview.json
```

执行时同样要带 `--keep-source --keep-dest --record-only`。这会调用 `DELETE /api/v1/history/transfer?deletesrc=false&deletedest=false`，只删除经过校验的 MoviePilot 整理历史记录，不删除 qB 任务、本地源文件、hlink 文件、STRM 或云盘文件。

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

## qB/MP 记录缺失时的孤儿清理

如果 MoviePilot 已经没有整理历史，qB 里也不再有对应任务，但本地 hlink 或源目录仍然残留，不能手动 `rm -rf`。先用项目的孤儿清理预览逐季确认。

hlink-only 预览只允许清理一个显式 hlink Season 目录：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver cloud-hlink-orphan-cleanup-preview \
  --env-file .env \
  --title 绝命毒师 \
  --expected-tmdbid 1396 \
  --hlink-root "/media/hlink/TV/绝命毒师 (2008)/Season 01" \
  --strm-root "/media/cloud-strm/series/绝命毒师 (2008) {tmdbid=1396}/Season 01" \
  --expected-episode-count 7 \
  --expected-episode-min 1 \
  --expected-episode-max 7 \
  --required-target-prefix "/已整理/series/绝命毒师 (2008) {tmdbid=1396}/Season" \
  --cloud-media-folder-id 115-folder-id \
  --format json \
  --output reports/cloud-hlink-orphan-preview.json
```

执行单季 hlink-only 清理时也必须从预览 JSON 进入，并显式复核标题、TMDB 和 hlink 根；执行报告可以作为 `batch-review-report --post-cleanup-report` 的输入，与 finalize 里的 STRM/NFO/Emby 门禁合并成清理完成证据。

如果本地残留的是一个多季 hlink 根目录，不要逐季手动删，也不要把整部剧当成单季去骗过集数检查。使用多季 hlink-only 预览，每季重复一个 `--season`；普通连续季写成 `季号:STRM季目录:集数:起始集:结束集`，本地历史本来就不连续时写成 `季号:STRM季目录:episodes=1,3-13`。云端 STRM 多出本地没有的集数不会阻断，但本地 hlink 已有的任何一集在 STRM 中缺失都会阻断：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver cloud-hlink-orphan-multiseason-cleanup-preview \
  --env-file .env \
  --title 广告狂人 \
  --expected-tmdbid 1104 \
  --hlink-root "/media/hlink/TV/广告狂人 (2007)" \
  --season "1:/media/cloud-strm/series/广告狂人 (2007) {tmdbid=1104}/Season 01:13:1:13" \
  --season "5:/media/cloud-strm/series/广告狂人 (2007) {tmdbid=1104}/Season 05:episodes=1,3-13" \
  --required-target-prefix "/已整理/series/美剧【广告狂人】" \
  --forbidden-target-prefix "/volume3" \
  --cloud-media-path "/已整理/series/美剧【广告狂人】1-7季全 1080P中字【373G】" \
  --format json \
  --output reports/cloud-hlink-orphan-multiseason-preview.json
```

执行也必须从预览 JSON 进入，并复核标题、TMDB、hlink 根和季号：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver cloud-hlink-orphan-multiseason-cleanup-execute \
  --env-file .env \
  --preview-report reports/cloud-hlink-orphan-multiseason-preview.json \
  --expected-title 广告狂人 \
  --expected-tmdbid 1104 \
  --expected-hlink-root "/media/hlink/TV/广告狂人 (2007)" \
  --expected-season 1 \
  --expected-season 5 \
  --approve-delete \
  --format json \
  --output reports/cloud-hlink-orphan-multiseason-execute.json
```

source-only 预览只允许清理一个显式 qB 源目录：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver cloud-source-orphan-cleanup-preview \
  --env-file .env \
  --title 绝命毒师 \
  --expected-tmdbid 1396 \
  --source-root "/media/source/Breaking.Bad.S01.2008.1080p.BluRay.x264" \
  --strm-root "/media/cloud-strm/series/绝命毒师 (2008) {tmdbid=1396}/Season 01" \
  --expected-episode-count 7 \
  --expected-episode-min 1 \
  --expected-episode-max 7 \
  --required-target-prefix "/已整理/series/绝命毒师 (2008) {tmdbid=1396}/Season" \
  --cloud-media-folder-id 115-folder-id \
  --format json \
  --output reports/cloud-source-orphan-preview.json
```

这些预览都会重新验证 STRM 集数和目标前缀、检查云盘媒体目录没有 `.nfo/.jpg/.jpeg/.png/.webp` 元数据旁挂，并扫描 qB 当前任务列表。只要 qB 仍然引用目标文件 inode 或源路径，预览就会阻断。真正执行必须从预览 JSON 报告进入，并显式传入标题、TMDB ID、目标根目录和 `--approve-delete`；执行时会再次预检，成功后只删除那个精确 hlink 或 source 根目录，不操作云盘、STRM、Emby 或其他 qB 任务。云盘实体目录仍然只承担转存和生成 STRM，不做刮削；中文 NFO、海报和 Emby 入库只在 STRM 媒体库路径完成。

如果 `batch-finalize-run --approve-delete` 的 `cloud_hlink_cleanup_execute` 已经成功删除 qB 任务和 hlink 根目录，但报告因 `source_root_still_contains_video_files` 停住，不要手工删除 source，也不要直接重跑同一个 finalize。先从上一次 `13-finalize-run.json` 做 source-only 恢复 dry-run：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver batch-source-orphan-recovery-run \
  --env-file /volume1/docker/series-cloud-archiver/.env \
  --finalize-run-report outputs/current-20260701/pipeline-runs/<run>/13-finalize-run.json \
  --output-dir outputs/current-20260701/pipeline-runs/<recovery-run>/source-recovery-stages \
  --format json \
  --output outputs/current-20260701/source-orphan-recovery-dryrun.json
```

确认每个 item 都是 `source_orphan_cleanup_waiting_for_approval` 后，才显式批准 source-only 删除：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver batch-source-orphan-recovery-run \
  --env-file /volume1/docker/series-cloud-archiver/.env \
  --finalize-run-report outputs/current-20260701/pipeline-runs/<run>/13-finalize-run.json \
  --output-dir outputs/current-20260701/pipeline-runs/<recovery-run-approved>/source-recovery-stages \
  --approve-delete \
  --format json \
  --output outputs/current-20260701/source-orphan-recovery-approved.json
```

这个 runner 只处理旧报告中 qB delete 和 hlink delete 已成功、qB 当前无剩余、hlink 已不存在、唯一阻断为 source 视频残留的行；执行前会重新检查合并后的多 source root 集数、STRM 指向、云盘媒体旁挂和 qB 当前任务。`batch-finalize-run` 里若遇到同样的半成功状态，也只会停在 `source_orphan_cleanup_waiting_for_approval`，真正删除 source 需要额外传入 `--approve-source-orphan-delete`。

还有一种常见残局：STRM 已经完整，本地 source/hlink 已经不存在或只剩旁挂文件，但 qB 里还挂着“文件丢失”的孤儿任务。这个场景不要走 MP 清理，也不要手动点 qB，先用 qB task-only 预览：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver qb-orphan-torrent-cleanup-preview \
  --env-file .env \
  --title 八千里路云和月 \
  --expected-tmdbid 289624 \
  --expected-qb-hash 54e6fafc796dedce402f91cbc8b69d55d6bb3dc0 \
  --source-root "/media/source/Echoes.of.a.Thousand.Moons.S01" \
  --hlink-root "/media/hlink/TV/八千里路云和月 (2026)" \
  --strm-root "/media/cloud-strm/series/八千里路云和月 (2026) {tmdbid=289624}/Season 01" \
  --expected-episode-count 40 \
  --expected-episode-min 1 \
  --expected-episode-max 40 \
  --required-target-prefix "/已整理/series/八千里路云和月" \
  --format json \
  --output reports/qb-orphan-preview-baqianli.json
```

预览会要求完整 qB hash，确认 qB 任务名/路径仍指向目标剧、任务已完成且做种时间达标、本地 source/hlink 没有视频、STRM 侧路径完整，并且 MP 整理历史已经缺失。真正执行仍然从预览 JSON 进入，并复核标题、TMDB ID、完整 hash 和每个根目录：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver qb-orphan-torrent-cleanup-execute \
  --env-file .env \
  --preview-report reports/qb-orphan-preview-baqianli.json \
  --expected-title 八千里路云和月 \
  --expected-tmdbid 289624 \
  --expected-qb-hash 54e6fafc796dedce402f91cbc8b69d55d6bb3dc0 \
  --expected-source-root "/media/source/Echoes.of.a.Thousand.Moons.S01" \
  --expected-hlink-root "/media/hlink/TV/八千里路云和月 (2026)" \
  --expected-strm-root "/media/cloud-strm/series/八千里路云和月 (2026) {tmdbid=289624}/Season 01" \
  --approve-delete \
  --format json \
  --output reports/qb-orphan-execute-baqianli.json
```

`qb-orphan-torrent-cleanup-execute` 只调用 qB Web API 删除任务，并固定使用 `deleteFiles=false`：它会清掉 qB 任务和 qB 的种子元数据，但不会让 qB 删除内容文件，不会删除 hlink/source 目录，不会触碰云盘、STRM、Emby，也不会做任何刮削。云盘/MV3 侧仍然只负责转存和生成 STRM；NFO、海报、Emby 入库都只在 STRM 媒体库路径完成。

如果 Emby 里还残留旧本地源，优先只通知 STRM 媒体库路径更新并核验旧路径是否消失。批量迁移默认使用这个局部入口，避免慢速全库扫描，也避免把云盘实体目录带进刮削范围：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver emby-media-updated \
  --env-file .env \
  --title 楚汉传奇 \
  --updated-path "/media/cloud-strm/series/楚汉传奇 (2012) {tmdbid=41146}" \
  --stale-path-prefix "/media/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}" \
  --strm-path-prefix "/media/cloud-strm/series/楚汉传奇 (2012) {tmdbid=41146}" \
  --expected-strm-records 82 \
  --expected-episode-count 80 \
  --expected-episode-min 1 \
  --expected-episode-max 80 \
  --format markdown \
  --output reports/emby-media-updated-chuhan.md
```

`emby-media-updated` 只调用 Emby 的 `POST /emby/Library/Media/Updated`，并且 `--updated-path` 和 `--strm-path-prefix` 都必须是 STRM 侧路径；传 `/已整理/...`、`/未整理/...` 这类云盘实体目录会被项目阻断。这个命令不会触发全库扫描，不会删除文件、不会操作 qB、不会调用 MP 清理，也不会直接写 Emby 数据库。

只有在局部 STRM 通知无法让 Emby 收敛、并且确认需要慢速全库刷新时，才显式批准全库刷新：

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
  --approve-full-library-refresh \
  --format markdown \
  --output reports/emby-refresh-chuhan.md
```

`emby-refresh-verify` 只有带 `--approve-full-library-refresh` 才会调用 Emby 的 `POST /emby/Library/Refresh` 触发媒体库扫描，然后轮询 `RefreshLibrary` 任务，最后确认旧 hlink/local 路径记录为 0、STRM 版本还在且集数完整。它不会删除文件、不会操作 qB、不会调用 MP 清理，也不会直接写 Emby 数据库。

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

确认预览结果后，可以只转存一个浏览条目到 `/未整理`。如果分享根目录下是一个完整剧集文件夹，优先接收这个文件夹本身，而不是进入文件夹后 `--receive-all-files` 把文件平铺到 `/未整理` 根目录；接收文件夹前必须先用 `mv3-share-preview --browse-cid ...` 证明内层集数完整：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-share-receive-one \
  --env-file .env \
  --keyword 楚汉传奇 \
  --selection-index 2 \
  --browse-index 1 \
  --receive-selected-folder \
  --verified-folder-browse-report reports/mv3-share-preview-chuhan-folder.json \
  --expected-episode-count 80 \
  --expected-episode-min 1 \
  --expected-episode-max 80 \
  --expected-title-contains 楚汉传奇 \
  --target-path /未整理 \
  --storage 115-default \
  --approve-receive \
  --format markdown \
  --output reports/mv3-share-receive-chuhan.md
```

`mv3-share-receive-one` 会重新搜索并预览同一个候选，只在通过标题校验和 `--approve-receive` 时调用 `/api/v1/share-transfer/receive`。接收文件夹时还会复核 `--verified-folder-browse-report` 里的 `browse_cid`、集数范围、缺失集和异常集，避免把未验证的文件夹转存进云盘。它只转存选中的一个分享条目，不会整理、识别媒体类型、生成 STRM、操作 qB 或删除本地文件。

如果 cleanup preview 发现 qB 源目录里还有 hlink 未覆盖的本地视频，例如特辑或花絮，先用 `extra-source-media-plan` 生成只读计划，再让 MV3 扫描单个本地文件：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-organize-scan-source \
  --env-file .env \
  --source-path "/volume-example/source-tv/Demo/Demo.SP1.mkv" \
  --local-source \
  --file \
  --format json \
  --output reports/demo-sp1-scan.json
```

如果 `scan-source` 返回空 `items`，不要手工挪文件，也不要绕开项目直接操作云盘。先把人工确认过的归属写成映射文件；每一行必须有本地源文件、TMDB ID、季号和集号。比如特辑通常会写成 Season 00，但具体 `episode` 必须以 TMDB/媒体库确认结果为准：

```json
{
  "mode": "confirmed-extra-source-media-map",
  "items": [
    {
      "title": "兄弟连",
      "tmdbid": 4613,
      "season": 0,
      "episode": 5,
      "episode_title": "We Stand Alone Together",
      "source_path": "/volume-example/source-tv/Demo/Demo.SP1.mkv"
    }
  ]
}
```

确认映射文件后，先生成 dry-run 报告；这一步只构造 MV3 请求和安全门禁，不会调用 `/api/v1/organize/transfer`：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-organize-transfer-from-local-map \
  --env-file .env \
  --mapping-file reports/demo-extra-local-map.json \
  --target-dir /已整理 \
  --strm-dir /strm \
  --tmdb-id 123 \
  --expected-episode-count 1 \
  --expected-episode-min 5 \
  --expected-episode-max 5 \
  --format json \
  --output reports/demo-sp1-transfer-dry-run.json
```

dry-run 报告无 blocker 后，才可以加审批参数让 MV3 copy 到 `/已整理` 并生成 STRM：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-organize-transfer-from-local-map \
  --env-file .env \
  --mapping-file reports/demo-extra-local-map.json \
  --target-dir /已整理 \
  --strm-dir /strm \
  --tmdb-id 123 \
  --expected-episode-count 1 \
  --expected-episode-min 5 \
  --expected-episode-max 5 \
  --approve-transfer \
  --format json \
  --output reports/demo-sp1-transfer-execute.json
```

这条链路不会移动或删除本地源文件，强制使用 copy 模式；映射文件里的季/集只作为项目的安全门禁和报告证据，最终命名仍由 MV3 根据 `tmdb_id` 和源文件信息完成。本地 qB/source/hlink 仍然必须等 STRM 完整、中文 NFO、Emby 和清理预览全部变绿后，才由最终 cleanup 阶段处理。云盘实体目录仍然只做转存和 STRM 生成，不做刮削，不写 NFO/JPG。

如果怀疑 115 里已经有同内容，或者分享预览暂时不可用，可以先用只读云盘搜索找候选目录。这个命令只查 115 文件名，不转存、不整理、不生成 STRM，也不会刮削云盘媒体目录：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-cloud-search \
  --env-file .env \
  --keyword "楚汉传奇" \
  --storage 115-default \
  --format json \
  --output reports/mv3-cloud-search-chuhan.json
```

转存完成后，或者云盘搜索找到了候选目录后，先只读确认云盘目录内容：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-cloud-browse \
  --env-file .env \
  --folder-id 3453317028314611284 \
  --path "/未整理/楚汉传奇 (2012)" \
  --storage 115-default \
  --format markdown \
  --output reports/mv3-cloud-browse-chuhan.md
```

`mv3-cloud-browse` 只调用 `/api/v1/files/cloud/info` 和 `/api/v1/files/cloud/browse`，用于确认目录下真实文件、集数范围和明显断集。它不会整理、移动、生成 STRM、刮削云盘目录或删除任何东西。

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

确认 `mv3-cloud-browse` 里的集数完整后，才允许调用 MV3 整理转存。这里的 `--target-dir` 必须传 MV3 云盘整理根目录，例如 `/已整理`，不要传 `/已整理/series`，也不能传 `/strm` 这类 STRM 侧路径；`--strm-dir` 必须传 STRM 根目录，例如 `/strm`，不要传 `/strm/series`，也不能传 `/已整理`、`/未整理` 或裸 `/series`。MV3 在 `enable_primary_category=true` 时会自己补 `series`，否则可能生成重复的 `series/series` 路径。项目会在调用 MV3 写接口前检查这两个目录的角色，填反或混用会直接阻断。

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

`mv3-organize-transfer-from-browse` 只负责把媒体文件交给 MV3 整理并生成 STRM。云盘只做转存和 STRM 生成，云盘媒体文件目录不做刮削，也不应生成旁挂 NFO/JPG；后续只让 MoviePilot/Emby 对 STRM 目录刮削入库。项目里的 MV3 分享接收、整理扫描、整理转存都会排除 `.nfo/.jpg/.jpeg/.png/.webp` 这类刮削旁挂，字幕旁挂仍可保留给播放使用。即使上游 browse 报告没有标出 `media_kind`，项目也会按扩展名重新判定，只把真实视频文件提交给 MV3 整理。

换句话说，115/MV3 的实体目录只负责“资源在那里、STRM 指过去”；中文 NFO、海报、剧集信息和 Emby 入库都应该发生在 STRM 媒体库路径。任何把 `/已整理/...` 这类云盘媒体目录，或裸 `/series/...` 这类非 STRM 侧目录，传给 Emby 刷新/刮削的命令都会被项目阻断。

整理转存成功后，下一步必须先验证两边：云盘媒体目录只应该有视频和可播放用字幕旁挂，不能有 `.nfo/.jpg/.jpeg/.png/.webp`；STRM 目录才是后续刮削和 Emby 入库对象。也就是说，删除本地 hlink 或 qB 种子前，至少要同时拿到 `mv3-cloud-browse`、`mv3-cloud-media-sidecar-verify`、`strm-verify` 和局部 Emby 验证报告。

批量场景不要再把 `batch-finalize-plan` 里的命令一条条手工复制执行。先生成 finalize plan，再交给 `batch-finalize-run` 按顺序跑门禁：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver batch-finalize-plan \
  --env-file .env \
  --batch-plan reports/batch-plan.json \
  --host-strm-root "/example/host/strm" \
  --mp-strm-root "/example/moviepilot/strm" \
  --service-strm-root "/example/service/strm" \
  --forbidden-target-prefix "/未整理" \
  --format json \
  --output reports/batch-finalize-plan.json

PYTHONPATH=src python3 -m series_cloud_archiver batch-finalize-run \
  --env-file .env \
  --finalize-plan reports/batch-finalize-plan.json \
  --output-dir reports/batch-finalize-stages \
  --limit 2 \
  --execute-scrape \
  --format json \
  --output reports/batch-finalize-run-sample.json
```

`batch-finalize-run` 会逐部剧季执行 `strm-verify -> mv3-cloud-duplicate-video-cleanup dry-run -> mp-scrape-strm -> strm-nfo-language-audit -> emby-media-updated -> cloud-hlink-cleanup-preview`。任何一步失败都会停止当前项并写报告；默认不会删除云盘重复视频、Emby 旧条目、qB、种子文件或 hlink。MoviePilot 和 Emby 如果挂载路径不同，finalize plan 用 `--mp-strm-root` 给 MoviePilot，用 `--service-strm-root` 给 Emby。

三个删除动作分开审批：

- `--approve-cloud-duplicate-delete`：只在 STRM 保护目标完整、重复视频数量明确时，删除云盘 Season 里未被 STRM 引用的重复视频，并立刻复核云盘/STRM。
- `--approve-emby-stale-delete`：只在 STRM 替代完整时，删除 Emby 里旧本地源的 Season/root 条目，避免库里同时显示本地源和 STRM 源。
- `--approve-delete`：只在前面所有门禁都通过、`cloud-hlink-cleanup-preview` 显示 `ready_for_execute=true` 后，才执行 qB/hlink/source 本地清理。

这个 runner 只把 STRM 路径传给 MP/Emby 刮削和刷新；云盘 `/已整理/...` 路径只用于检查实体目录里有没有误写入的 NFO/JPG 等旁挂。

单独调用 `mv3-strm-generate` 时也保持同样边界：只生成 STRM，不允许顺手整理或刮削云盘媒体。`--target-dir` 必须是 STRM 侧根目录，不能传 `/已整理`、`/未整理` 或 `/series`。命令里的 `--organize` 会被项目阻断；即使传了旧版兼容参数 `--allow-organize` 也不会放行。正常迁移流程应先用 `mv3-organize-transfer-from-browse` 完成云盘整理和 STRM 生成，再只刷新/刮削 STRM 侧媒体库。

如果发现云盘媒体目录里已经出现 `.nfo/.jpg/.jpeg/.png/.webp` 等刮削旁挂，先用 dry-run 列出将要删除的元数据文件：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-cloud-media-sidecar-cleanup \
  --env-file .env \
  --path "/已整理/series/剧名 (2026) {tmdbid=123456}" \
  --storage 115-default \
  --format json \
  --output reports/mv3-cloud-media-sidecar-cleanup-dry-run.json
```

确认报告里只包含元数据旁挂、没有视频和字幕后，才允许带上预期数量批准删除：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-cloud-media-sidecar-cleanup \
  --env-file .env \
  --path "/已整理/series/剧名 (2026) {tmdbid=123456}" \
  --storage 115-default \
  --expected-delete-count 2 \
  --approve-delete \
  --format json \
  --output reports/mv3-cloud-media-sidecar-cleanup-execute.json
```

这个命令只会通过 MV3 删除云盘媒体目录中的元数据旁挂；视频文件和字幕旁挂不会被选中，也不会操作 qB、MP、Emby 或本地文件。

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

如果错根不是 `/已整理/series/series/剧名...`，而是一个合集目录本身，例如 `/已整理/series/美剧广告狂人1-7季/S07`，同一个命令也可以先 dry-run。此时 `--correct-root` 可以直接写正确标题目录，`--strm-root` 可以写 STRM 的标题目录：

```bash
PYTHONPATH=src python3 -m series_cloud_archiver mv3-repair-wrong-root \
  --env-file .env \
  --wrong-root "/已整理/series/错误合集目录" \
  --correct-root "/已整理/series/广告狂人 (2007) {tmdbid=1104}" \
  --strm-root "/strm-host/mv3/strm/series/广告狂人 (2007) {tmdbid=1104}" \
  --storage 115-default \
  --format json \
  --output reports/mv3-repair-wrong-root-direct-season-dry-run.json
```

这类报告会把错根下的 `S07`、`Season 07` 等直接季目录逐季列出，只在 STRM 指向正确标题根、正确季目录存在、集数/文件 id 检查通过时，才给出可审批的移动或删除动作。

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
