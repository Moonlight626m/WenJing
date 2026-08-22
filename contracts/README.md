# Shared Contracts — 文境核心 MVP 共享契约层

本目录是**核心 MVP 的唯一共享契约源**：后端 `backend/app/contracts/`、前端 TS 类型与样例数据
（fixtures）都以这里为准。四条并行工作流（Gameplay Core / Content Pipeline / Session Platform /
Frontend）在契约冻结后独立开发，禁止各自发明不兼容模型。

## 布局

```text
backend/app/contracts/    后端契约（Pydantic v2，版本化，extra=forbid）
  material.py              MaterialInput / Material / GenreKind
  evidence.py              原文与网络证据引用（discriminated union）
  script.py                ScriptPackage / CharacterSetting / Scene / Stage2Beat
  commands.py              CommandType / PlayerCommand / CommandStatus
  events.py                DomainEvent（游戏事实，append-only）
  runtime.py               GameStage / InteractionPhase / RuntimeState / GameSnapshot
                           RuntimeUpdate / ALLOWED_COMMANDS
  errors.py                ErrorDomains / ErrorCode / ErrorEnvelope
  protocol.py              REST DTO + WebSocket OutboundMessage（判别式联合）
  mappers.py               领域模型 → DTO 的唯一转换路径
fixtures/                  权威样例数据（JSON，逐字节同步到前端）
manifest.json              契约名称 ↔ fixture ↔ schema_version ↔ TS 类型映射
README.md                  本文件（变更流程）
```

## 设计规则

1. **版本化**：每个契约带 `schema_version`（int，默认见各模块常量）。非破坏性扩展
   （新增字段带默认值、新增枚举值、新增错误码）不需升版本；任何破坏性变更必须升版本。
2. **严格校验**：契约模型一律 `extra="forbid"`；非法输入在边界即失败，不进入领域状态。
3. **领域与 DTO 分离**：`protocol.py` 的 DTO 是设备边界；路由/WS handler 不得手工构造 DTO，
   一律经 `mappers.py`。
4. **依赖方向**：契约不依赖 FastAPI/SQLAlchemy/WebSocket/LLM client；Gameplay Core 只依赖契约。
5. **阶段枚举**：`GameStage` / `InteractionPhase` 自本层提升（值向后兼容），
   `app/core/state_machine.py` 转发使用；引擎重构（ticket #7）消费本层枚举。
6. **每阶段命令表**：`runtime.ALLOWED_COMMANDS` 是命令合法性的事实表；`RuntimeUpdate.allowed_commands`
   由此产生，前端不经由它判断（前端只展示服务端投影）。

## 变更流程（breaking change）

Shared Contracts、数据库迁移与外部协议的任何 **breaking change**（删除/重命名类型或字段、
改变字段类型或语义、重排枚举值、改变 payload 约定）必须：

1. 至少**两名模块 owner review**（GitHub PR 上两人 approve；本仓库默认
   Gameplay Core / Content Pipeline / Session Platform / Frontend 四 owner）。
2. 同时更新：后端模型、`frontend/src/lib/contracts.ts`、权威 fixtures、
   前端 fixture 副本、`manifest.json` 的 schema_version。
3. 提供迁移说明（旧数据/旧客户端如何解读）。

非破坏性扩展（新增可选字段、新增枚举成员、新增稳定错误码）不需要多人 review，
但必须同步更新 fixtures/manifest 并跑通同步测试。

## 同步机制（测试守卫）

- 后端 `backend/tests/test_contract_fixtures.py`：
  - 每个权威 fixture 可解析到对应契约；
  - `manifest.json` 与 `app.contracts` 导出、磁盘 fixture 集合三方一致；
  - 前端副本与权威 **逐字节一致**。
- 前端：`tsc --noEmit` 编译 `frontend/src/lib/contracts/fixtures.ts`
  （typed imports 直接约束 fixture JSON 形状），作为 fixture ↔ TS 类型的同步断言。

改样例数据只允许改 `contracts/fixtures/`，然后同步前端副本
（`cp contracts/fixtures/*.json frontend/src/lib/contracts/fixtures/`）。

## 常用命令

```bash
make test            # 后端测试（含契约同步测试）
cd frontend && npm run typecheck   # TS 契约类型 + fixture 形状检查
```