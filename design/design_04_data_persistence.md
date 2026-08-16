# 文境 (Wenjing) — 模块设计：数据持久化

> 聚焦游戏数据存储、事件溯源落库、快照、会话存档/恢复。
>
> 技术决议：数据库 **PostgreSQL**（D10）；状态持久化 **事件溯源 + checkpoint 快照**（D11）；MVP 提供回溯与会话存档/恢复（D15）。

---

## 一、存储对象总览

| 对象 | 说明 | 存储方式 |
|------|------|----------|
| **事件流 (Event Store)** | 游戏全过程事件（剧情推进/方向/提议/验证/玩家操作/角色发言） | PostgreSQL 表 `events`，payload 用 JSONB |
| **快照 (Snapshot)** | 每 20 事件的状态快照，加速回溯 | PostgreSQL 表 `snapshots` |
| **剧本 (Script)** | Stage1 生成的完整剧本（场景序列/角色设定表） | PostgreSQL 表 `scripts`，JSONB |
| **会话 (Session)** | 游戏会话元数据与状态机当前状态 | PostgreSQL 表 `sessions` |
| **课文素材 (Material)** | 导入的课文 + 素材收集输出 | PostgreSQL 表 `materials`，JSONB |
| **角色记忆 (Memory)** | 各角色 Agent 的 working_memory/personal_log/relationship_map | 随快照保存；可选单独表 `character_memories` |

---

## 二、事件溯源 (Event Sourcing)

### 2.1 设计原则

- **事件不可变**：所有游戏事件只追加（append-only），不修改、不删除。
- **状态由事件推导**：角色记忆、剧情上下文等均可从事件流 + 快照重建。
- **事件即真相**：回溯/存档/复现均以事件流为唯一事实来源。

### 2.2 表结构

```sql
CREATE TABLE events (
    id          BIGSERIAL PRIMARY KEY,        -- 事件自增 ID
    session_id  UUID NOT NULL REFERENCES sessions(id),
    event_type  TEXT NOT NULL,                -- stage_transition | plot_advancement | direction | proposal | verification | player_action | character_speech | system | snapshot
    payload     JSONB NOT NULL,               -- 具体数据（含 scene_summary、proposal、player_action 等）
    parent_id   BIGINT REFERENCES events(id), -- 父事件（用于追溯/分支）
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_events_session ON events(session_id, id);
```

### 2.3 与 design_03 EventStore 的衔接

design_03 中 `EventStore` 为内存实现，持久化层在其上追加：
- `EventStore.append()` 写入内存的同时异步写入 `events` 表。
- 会话恢复时从 PostgreSQL 加载事件流重建内存列表。
- 内存保留最近 `max_events_in_memory`（默认 5000）条，更早事件按需从 DB 懒加载（MVP 单会话 <100 步，可全部常驻内存）。

---

## 三、Checkpoint 快照

### 3.1 作用

- 回溯时避免从 0 重放全部事件，从最近快照重放即可。
- 会话存档/恢复时直接复用快照 + 增量事件。

### 3.2 表结构

```sql
CREATE TABLE snapshots (
    id           BIGSERIAL PRIMARY KEY,
    session_id   UUID NOT NULL REFERENCES sessions(id),
    event_id     BIGINT NOT NULL REFERENCES events(id),  -- 快照对应的事件 ID
    state_machine TEXT NOT NULL,          -- 当前 GameStage
    character_memories JSONB NOT NULL,    -- 所有角色 Agent 记忆快照
    plot_context  JSONB NOT NULL,         -- 当前剧情摘要/方向
    event_count   INT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_snapshots_session ON snapshots(session_id, event_id);
```

### 3.3 快照策略

- 触发：每 20 事件（`checkpoint_interval`），与 design_03 `CheckpointManager` 一致。
- 回溯：`find_nearest_snapshot(target_id)` → 载入快照 → 从快照事件重放到目标事件 → 截断后续事件。
- 清理：MVP 不清理；长会话可保留最近 N 个快照。

---

## 四、会话与剧本

### 4.1 会话表

```sql
CREATE TABLE sessions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    current_stage TEXT NOT NULL DEFAULT 'init',   -- init/stage1_creating/stage1_complete/stage2_reenacting/stage2_complete/stage3_extending/ended
    script_id     BIGINT REFERENCES scripts(id),
    material_id   BIGINT REFERENCES materials(id),
    player_role   TEXT,                           -- 玩家扮演的角色名（Stage2 前确定）
    status        TEXT NOT NULL DEFAULT 'active', -- active/paused/ended
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 4.2 剧本表

```sql
CREATE TABLE scripts (
    id            BIGSERIAL PRIMARY KEY,
    session_id    UUID NOT NULL REFERENCES sessions(id),
    title         TEXT NOT NULL,
    script_data   JSONB NOT NULL,   -- ScriptOutput（场景序列/角色设定表）
    verification  JSONB,            -- 验证 Agent 审核结果
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## 五、会话存档/恢复与回溯

### 5.1 存档 (Save)

```
触发：玩家 system_command(save) 或引擎定时（可选）
流程：
1. 检查当前事件数是否 ≥ 最近快照间隔 → 若无则先生成快照
2. 持久化 session 状态（stage/player_role/status）
3. 事件流已逐条落库，无需额外复制
4. 返回 save_ok 给前端
```

### 5.2 恢复 (Load)

```
触发：前端携带 session_id 重连 / system_command(load)
流程：
1. 加载 session 元数据（stage/player_role）
2. 加载最近快照 → 恢复角色记忆与剧情上下文
3. 加载快照之后的增量事件 → 重放重建状态
4. 通过 SessionInitMessage 同步前端当前状态
```

### 5.3 回溯 (Rollback)

- 与 design_03 `_execute_rollback` 一致：最近快照 + 重放 + 截断。
- 截断即删除目标事件之后的事件行（事件不可变原则下，截断属于"会话分支"：可标记截断点，保留历史以便"前进"重放——见下）。
- **MVP 简化**：Stage2 类进度条回溯（删掉截断事件，历史不再保留）；Stage3 类 revert 复用同一机制，限制 ≤100 步。

### 5.4 事务一致性

- 快照 + 事件截断须在同一事务内完成，避免回溯中断导致状态不一致。
- 存档/恢复使用 `REPEATABLE READ` 隔离级别保证读一致性。

---

## 六、数据模型映射

| design_03 内存对象 | PostgreSQL 落库 |
|--------------------|-----------------|
| `EventStore.events` | `events` 表 |
| `GameSnapshot` | `snapshots` 表 |
| `CharacterMemory` | `snapshots.character_memories`（JSONB）或独立表 |
| `GameStateMachine.current` | `sessions.current_stage` |
| `ScriptOutput` | `scripts.script_data`（JSONB） |
| 素材收集输出 | `materials` 表（JSONB） |

---

## 七、ORM / 迁移

| 选型 | 决议 | 理由 |
|------|------|------|
| ORM | SQLAlchemy (async) | FastAPI 生态标准，支持 async + JSONB |
| 迁移 | Alembic | 与 SQLAlchemy 配套 |
| 驱动 | asyncpg | 异步 PostgreSQL 驱动 |

---

## 八、MVP 范围

### 包含
- 事件流落库（events 表）
- checkpoint 快照（snapshots 表，每 20 事件）
- 会话创建/恢复、游戏结束存档
- 回溯 ≤100 步（共享快照机制）

### 不包含（后续迭代）
- 剧本分享/复现（仅存剧本数据，不做导出/社区）
- 长会话事件冷存储/归档
- 多玩家会话并发控制
