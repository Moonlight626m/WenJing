# 文档索引(docs/)

> **规格优先级**:GitHub Issues(spec / 任务)> `CONTEXT.md`(术语)> 复杂机制的现行规则已在 AGENTS.md 章节、代码注释与测试 docstring 中就地成文。
> **任务与进度只以 GitHub Issues 为追踪源**(见 `docs/agents/issue-tracker.md`),文档不承担待办列表。

## 目录

| 位置 | 内容 | 状态 |
|------|------|------|
| `CONTEXT.md`(仓库根) | 领域术语表 | 现行 |
| `AGENTS.md`(仓库根) | 架构与命令约定,含关键机制的精炼描述 | 现行 |
| `docs/agents/` | agent skills 配置:issue tracker / triage labels / domain docs | 现行 |
| `docs/contract-change-process.md` | 契约变更流程(四处单源) | 现行 |
| `docs/design/` | 专题设计:游玩链路重构、Stage3 自由探索 | 草案 |
| `docs/design/play-through-architecture.md` | 游玩链路说明(现行语义/契约/存储/不变量,供后续任务查阅) | 现行 |
| `docs/design/play-through-frontend.md` | 游玩链路前端增补设计(Stage2 还原/Stage3 探索/回溯的界面与逻辑) | 草案 |
| `docs/design/stage3-chronicle-redesign.md` | Stage3 自由探索与编年史:单机实例/角色工厂/限知编年史/无显式结束 | 草案 |
| `docs/prompts/` | 运行期 Agent 的 Prompt 全文、设计标准与查阅/试验/更新手册 | 现行 |
| `docs/prompts/runtime-agents.md` | 运行期 Agent 分工、现行 Prompt 全文、开发者查阅/试验/更新流程 | 现行 |
| `docs/research/` | 技术 / 部署调研快照(带日期,非规格,不追改) | 参考 |
| `docs/archive/handoffs/` | 已实现任务的交接/设计快照(带日期,不追改) | 归档 |

历史上的架构决策文档(`docs/adr/` ADR-0001…0006 与 `docs/archive/design/` MVP 期设计)于
2026-11 删除:决策均已落地为代码,原文可查 git 历史;机制要点已沉淀在 `AGENTS.md`、
`CONTEXT.md`、代码注释与测试 docstring 中。

## 当前路线图

任务追踪在 GitHub Issues,不在本目录:

- **Epic #38** 场景视觉化与多媒体:背景图 / 生成与检索 / 对象存储 / 流式与音频。
  子任务 **#39–#64** 已基本实施完毕,仅 **#52** 游玩页舞台待视觉验收。
- 历史交付(MVP #2–#13、多用户化 #17–#26、剧本生成 workflow #27–#36)见 git 历史与
  相关 docs/research 调研快照。

## 文档维护原则

- **决策**的精炼要点与陷阱进 `AGENTS.md`;**规格与任务**进 GitHub Issues;术语进 `CONTEXT.md`。
- `docs/research/` 是带日期的调研快照,结论可能过期,**不追改**;引用其中的 ADR/旧文档
  编号时,把它们当成历史出处、按 git 历史理解。
- 新增专题设计放 `docs/design/`(可以再建);新增术语写 `CONTEXT.md`。
