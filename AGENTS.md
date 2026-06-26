<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read:

- specs/001-series-cloud-archiver/plan.md
- specs/001-series-cloud-archiver/spec.md
- .specify/memory/constitution.md
<!-- SPECKIT END -->

## Operational Control Rule

When operating on a real media library, use the owning service first:

- MV3 operations, including cloud share search, receive, organize, move/copy, wrong-root repair, and STRM generation, must go through this project's MV3 CLI/API wrappers.
- MoviePilot cleanup must go through this project's MP cleanup preview/execute/verify flow so qBittorrent tasks, torrent files, and hlink paths are deleted by MP when possible.
- Emby refresh and stale/local source verification must go through this project's Emby CLI/API wrappers.
- qBittorrent should be queried through this project for matching, seed-age gates, and `. !qB` audits.
- Direct shell/file/cloud manipulation is only a fallback after the project or upstream service lacks the needed capability. Prefer adding the missing capability to the project, testing it, committing it, pushing it, and deploying it before using a manual fallback.
