# 契约变更流程（issue #2 验收标准 6）

> 适用范围：`backend/app/contracts/`、`contracts/fixtures/`、`contracts/jsonschema/`、
> `frontend/src/lib/contracts/types.ts` —— 即全部共享契约与协议面。

## 角色与 owner

- 模块 owner 按 issue #1 的四条所有权流划分：Gameplay Core、Content Pipeline、
  Session Platform（含持久化与诊断）、Frontend Product。
- 共享契约、迁移与对外协议变更**至少需要两名模块 owner review**（spec 决策），
  且其中至少一名是被此变更直接影响的消费者模块的 owner。

## 什么算契约变更

| 变更 | 级别 |
|------|------|
| 新增可选字段（默认值向后兼容） | minor |
| 新增枚举值 / 新增命令类型 | minor（消费者需确认处理未知值的路径） |
| 收紧校验、删除字段、改名、改语义 | **breaking** |
| 改 `CONTRACTS_SCHEMA_VERSION` 主版本号 | **breaking** |

## Breaking change 流程

1. 开跟踪 issue，标注影响面（哪些消费者 + 迁移成本）。
2. 双 owner review 通过后方可合并；评审记录留在 issue。
3. 同步更新四处单源：Pydantic 模型 → fixtures → 导出的 jsonschema → 前端 TS 镜像。
4. `CONTRACTS_SCHEMA_VERSION` 递增主版本；持久化侧（events/snapshots JSONB）
   的 schema_version 由 #4/#12 的兼容性迁移流程处理，此处只登记。

## 机械保障

- fixtures ↔ Pydantic 严格校验：`backend/tests/test_contracts.py`。
- jsonschema 导出不过期断言：同测试文件（过期即红）。
- 前端消费方类型错误由 `tsc` / `next build` 捕获；
  运行时校验（ajv against `contracts/jsonschema/`）随 #6 mock server 接入。

## 非契约内的私有演进

各模块内部实现（引擎状态机细节、pipeline 内部结构、DB row model）不在此流程内，
可自由重构——这正是 contracts-first 的目的：以冻结接口换取内部自由。
