# 文境 (Wenjing) — 模块设计：前端架构

> 聚焦前端技术选型、目录结构、状态管理、WebSocket 消息流、UI 组件划分。
>
> 技术决议：前端 **Next.js**（D9）；通信 **REST + WebSocket**（D12）。
> 交互协议与界面草图见 `design_02_interaction_system.md`，本文档侧重工程架构。

---

## 一、技术栈

| 模块 | 选型 | 说明 |
|------|------|------|
| 框架 | Next.js (App Router) | 应用路由，SSR 可选用于首屏/加载页 |
| 语言 | TypeScript | 全量类型化 |
| 状态管理 | Zustand | 轻量，适合"接收消息流"场景 |
| WebSocket | `react-use-websocket` | 成熟，支持自动重连（指数退避） |
| Markdown | `react-markdown` | 叙事消息渲染（Markdown 子集） |
| 动画 | Framer Motion + CSS transitions | 流式文字、阶段切换动画 |
| HTTP 客户端 | fetch / axios | REST 接口（会话创建、剧本导入） |
| 样式 | Tailwind CSS | 快速布局 |

---

## 二、目录结构

```
frontend/
├── app/
│   ├── layout.tsx                # 根布局
│   ├── page.tsx                  # 首页（课文导入、会话创建）
│   └── game/
│       ├── page.tsx              # 游戏主界面（受保护，需 session_id）
│       ├── layout.tsx
│       └── loading.tsx           # 会话恢复加载态
├── components/
│   ├── layout/
│   │   ├── GameShell.tsx         # 主布局（叙事+输入+角色+控制栏）
│   │   ├── Header.tsx            # 标题/设置/保存/退出
│   │   ├── Sidebar.tsx           # 角色面板
│   │   └── ControlBar.tsx        # 回溯控制栏
│   ├── narrative/
│   │   ├── NarrativePanel.tsx    # 叙事主面板（消息流渲染）
│   │   ├── MessageBubble.tsx     # 角色发言气泡（流式）
│   │   ├── SceneDivider.tsx      # 场景分割线
│   │   └── SystemNotice.tsx      # 系统消息
│   ├── interaction/
│   │   ├── InputArea.tsx         # 输入区域（三模式分发）
│   │   ├── OptionsInput.tsx      # 模式 A/C：选项
│   │   ├── FreeInput.tsx         # 模式 B：自由输入
│   │   └── ActionTypeTabs.tsx    # 行为类型切换（说话/行动）
│   └── phase/
│       └── PhaseTransition.tsx   # 阶段切换过场
├── stores/
│   ├── gameStore.ts              # 游戏状态（消息列表、阶段、交互点）
│   ├── wsStore.ts                # WebSocket 连接状态与消息分发
│   └── uiStore.ts                # UI 状态（面板开关、流式动画状态）
├── lib/
│   ├── ws.ts                     # WebSocket client 封装（重连、心跳）
│   ├── api.ts                    # REST 接口封装
│   └── types.ts                  # 消息协议类型定义（design_02）
└── styles/
    └── globals.css
```

---

## 三、状态管理设计

### 3.1 状态分层

| Store | 内容 | 更新来源 |
|-------|------|----------|
| `gameStore` | 消息列表（narrative/speech/interaction/system）、当前阶段、当前交互点、进度 | WebSocket 消息 |
| `wsStore` | 连接状态（connecting/connected/disconnected）、重连次数、session_id | WS 事件 |
| `uiStore` | 面板显隐、流式动画状态、回溯浮层 | UI 交互 |

### 3.2 消息流

```
WebSocket 收到 JSON
    → wsStore 分发（按 message.type）
    → gameStore 更新对应子状态
    → React 组件订阅渲染
```

核心原则（design_02 §1.2）：**消息即视图**。前端无状态，所有游戏状态在后端；前端只维护"已收到的消息列表"。

---

## 四、WebSocket 客户端

### 4.1 连接生命周期

```
1. 会话创建：REST POST /api/sessions → 返回 session_id
2. 建立连接：ws://host/ws?session_id=xxx
3. 后端回 SessionInitMessage：阶段、已发生事件、当前交互点
4. 前端渲染初始状态，进入消息循环
5. 断线 → 指数退避重连（1s→2s→4s→max 30s）→ 携带 session_id 恢复
```

### 4.2 心跳与超时

- 定期发送 ping（如 30s），超时判定断线触发重连。
- 流式输出中若中断，重连后后端补齐未确认消息。

---

## 五、核心组件设计

### 5.1 NarrativePanel（叙事主面板）

- 订阅 `gameStore.messages`，按类型渲染气泡/分割线/系统消息。
- 流式输出：收到 `is_streaming=true` 的消息，逐 token 追加；`stream_done=true` 标记完成。
- 使用 react-markdown 渲染 narrative/speech 文本。

### 5.2 InputArea（输入区域，三模式）

| 模式 | 组件 | 交互 |
|------|------|------|
| A options | `OptionsInput` | 点击选项 → 发送 `player_action`(choose_option) |
| B free_input | `FreeInput` + `ActionTypeTabs` | 选择行为类型 + 输入文本 → `player_action`(speak/act/investigate) |
| C options_with_fallback | `OptionsInput` + "自定义"入口 | 选项为主，自定义切自由输入 |

### 5.3 ControlBar（回溯控制栏）

- `gameStore.progress`（当前步/总步）渲染进度条。
- 点击回退 → 发送 `rollback_request`(steps)。
- 回退后叙事面板变暗浮层"已回退到第 X 步"；前进按钮重新 Forward。
- 回退后新选择 → 截断后续历史（需后端确认）。

### 5.4 Sidebar（角色面板）

- 角色列表 + 状态指示器（在线/已发言/待定）。
- 关系简图：来自 `relationship_map`（design_01），MVP 可用简单标签或图谱插件。

---

## 六、REST 接口（MVP）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/sessions` | 创建会话（可选附带课文素材） |
| GET | `/api/sessions/{id}` | 会话状态查询 |
| POST | `/api/sessions/{id}/materials` | 导入课文 |
| POST | `/api/sessions/{id}/save` | 存档 |
| POST | `/api/sessions/{id}/load` | 读档 |

> 实时交互全部走 WebSocket；REST 仅用于会话管理类操作。

---

## 七、TTS/ASR 扩展点

- 仅预留接口：`MessageBubble` 增加"播放"按钮（`is_tts_ready` 开关），预留 `tts_url` 字段。
- 后续可接入 Web Speech API 或第三方 API，不改动消息协议主体。

---

## 八、MVP 范围

### 包含
- 游戏主界面：叙事面板 + 输入区域 + 角色面板 + 回溯控制栏
- 三模式输入（A/B/C）
- WebSocket 实时消息流 + 自动重连 + 流式渲染
- 会话创建/恢复/存档（REST + WS）
- 阶段切换过场

### 不包含（后续迭代）
- TTS/ASR 实际实现
- 图片/场景生成展示
- 复盘总结页面
- 剧本分享/社区页面
