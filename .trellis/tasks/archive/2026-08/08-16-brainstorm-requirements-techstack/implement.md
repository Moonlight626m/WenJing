# 执行计划：决议落盘与文档同步

> 本任务交付物是决策文档。实现阶段 = 将 D1–D15 决议落盘到项目根目录文档，为后续 design_03~05 提供输入。

## 有序执行清单

- [x] 1. 更新 `design/design.md` §7「待讨论事项」：标记已决议项（D1–D5, D14, D15），保留实现级参数待定项
- [x] 2. 删除 `todo.md`（其 issue 已全部由 prd.md D1–D15 决议覆盖；实现级参数项在 prd Notes 中标注"待 design_03 确定"）
- [x] 2b. 删除 `idea.md`、`feedback.md`（内容已精炼至 design/*.md 与 prd.md）；`research.md` 保留作实现期参考
- [x] 3. 更新 `design/design_03_game_engine.md`：将 D5 两段式、D6 LangGraph、D14 自动判断+确认、D4 retries=2 等决议回填到引擎章节
- [x] 4. 新建 `design/design_04_data_persistence.md`：事件溯源 + checkpoint + PostgreSQL JSONB + 会话存档/恢复（D10/D11/D15）
- [x] 5. 新建 `design/design_05_frontend_architecture.md`：Next.js + zustand + WS 消息流（D9/D12），含回溯控制栏与三模式输入区
- [x] 6. 根目录补充技术栈清单（或写入 design.md），汇总 D6–D13 决议

## 验证命令

- 无代码改动，无需 lint/typecheck。
- 文档一致性检查：确认 design.md 文档索引表状态更新（design_03/04/05 状态栏）。

## 风险点 / 回滚

- 仅文档变更，风险低；改动均在 git 中可追溯。
- 若后续实现发现某决议不可行，回退到任务目录 prd.md 决议记录重新评审。

## 后续动作（本次任务结束后）

- 启动新任务：design_03 补全 / design_04 / design_05 编写，或直接进入骨架搭建。
