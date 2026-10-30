# 文档索引（docs/）

> **规格优先级**：`docs/adr/`（ADR，最新）> GitHub Issues（spec / 任务）> `docs/archive/design/`（MVP 期归档背景）。
> **任务与进度只以 GitHub Issues 为追踪源**（见 `docs/agents/issue-tracker.md`），文档不承担待办列表。

## 目录

| 位置 | 内容 | 状态 |
|------|------|------|
| `docs/adr/` | 架构决策记录（ADR-0001…0006） | 现行，冲突时以此为准 |
| `docs/design/` | 专题设计 | 现行 |
| `docs/agents/` | agent skills 配置：issue tracker / triage labels / domain docs | 现行 |
| `docs/contract-change-process.md` | 契约变更流程（四处单源） | 现行 |
| `docs/research/` | 技术 / 部署调研快照（带日期，非规格，不追改） | 参考 |
| `docs/archive/design/` | MVP 期模块设计（`design.md`、D1–D15、`design_0X_*`） | 历史归档；`design_07` 已过期 |
| `CONTEXT.md`（仓库根） | 领域术语表 | 现行 |

## 当前路线图

任务追踪在 GitHub Issues，不在本目录：

- **Epic #38** 场景视觉化与多媒体（ADR-0005）：背景图 / 生成与检索 / 对象存储 / 流式与音频。
  子任务 **#39–#64**，按依赖前沿推进；已推进到 M6，仅 **#52**（游玩页舞台）等视觉验收。
  决策见 `docs/adr/0005-media-asset-streaming-architecture.md`；讨论纪要与落地计划已随
  实现完成归档至 `docs/archive/design/media-scene-visualization.md`。
- 历史交付（MVP #2–#13、多用户化 #17–#26、剧本生成 workflow #27–#36）见 git 历史与
  ADR-0002 / ADR-0003。

## 文档维护原则

- **决策**进 `docs/adr/`；**规格与任务**进 GitHub Issues；两者之外才写专题设计。
- `docs/research/` 是带日期的调研快照，结论可能过期，**不追改**；被 ADR 引用时才需留意。
- `docs/archive/design/` 是已归档的 MVP 期文档，与 ADR 冲突时以 ADR 为准；不再往里补新设计。
- 新增专题设计放 `docs/design/`；新增术语写 `CONTEXT.md`。
