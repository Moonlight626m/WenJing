# 归档（archive/）

> 本目录存放**已冻结的历史文档**：保留设计过程与当时的技术取舍，但**不是现行规格**，
> 不随代码演进更新。阅读时请以 ADR、GitHub Issues 与 `CONTEXT.md` 为准。

## design/

MVP 时期的模块设计文档（`design.md`、`design_00_tech_decisions.md`、`design_0X_*`），
原位于仓库根 `design/`，2026-09 归档至此。

**已被取代 / 过期说明（重要）：**

- `design_07_session_manager_and_infra_seams.md`：**已过期**。其「长驻 run + asyncio.Task」形态
  已被 #7 的 GameRuntime command/step 取代；`StoragePort` 等 seam 的落地以 ADR-0005 为准。
- `design_03_game_engine.md`、`design_04_data_persistence.md`：被实际实现（command/step 运行时、
  Alembic 迁移基线与分支事件存储）取代。
- `design_06_mvp_implementation.md`：被 ADR-0002（多用户化）与 ADR-0003（LangGraph 生成 workflow）修订。
- `design_00`（单用户假设）、`design_01`（Agent 架构）、`design_04`（归属模型）：被 ADR-0002/0003/0004 修订。

现行决策请看 `docs/adr/`；文档地图见 `docs/README.md`。代码注释里对 `design_0X §Y` 的引用是
**历史出处说明**，不代表该文档仍是规格。
