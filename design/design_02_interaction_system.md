# 文境 (Wenjing) — 模块设计：交互系统

> 聚焦前后端通信、玩家交互界面、交互模式的具体 UX 流程。

---

## 一、总体交互模型

### 1.1 三层架构

```
┌───────────────────────────────────────────────┐
│                 前端 (Web)                      │
│    Next.js + WebSocket Client                  │
│                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │
│  │ 叙事面板  │  │ 输入区域  │  │ 系统控制栏    │ │
│  │ (剧情显示)│  │ (交互操作)│  │ (回溯/设置)  │ │
│  └──────────┘  └──────────┘  └──────────────┘ │
└──────────────────────┬────────────────────────┘
                       │ WebSocket (JSON)
┌──────────────────────▼────────────────────────┐
│               后端 (Python)                    │
│    FastAPI + WebSocket Server                  │
│                                                 │
│  ┌──────────────────────────────────────────┐  │
│  │         Game Engine (编排层)              │  │
│  │  接收前端消息 → 路由到对应 Agent          │  │
│  │  Agent 产出 → 格式化为前端可渲染的消息     │  │
│  └──────────────────────────────────────────┘  │
└───────────────────────────────────────────────┘
```

### 1.2 核心原则

1. **后端主动推送** — 前端只负责展示和采集用户输入，剧情推进全部由后端 Game Engine 驱动
2. **消息即视图** — 前端的每次 UI 更新都对应一条来自后端的 `narrative` 或 `interaction` 消息
3. **前端无状态** — 所有游戏状态在后端维护，前端只维护"当前已收到的消息列表"
4. **流式输出** — Agent 发言通过 WebSocket 分块推送（SSE 风格），前端逐步渲染

---

## 二、消息协议

### 2.1 消息类型总览

后端 → 前端（5 种）：

| 消息类型 | 说明 | 前端响应 |
|----------|------|----------|
| `narrative` | 剧情叙述（场景描述、事件发生） | 追加到叙事面板 |
| `character_speech` | 角色 Agent 发言 | 追加到叙事面板，标注发言人 |
| `interaction` | 交互点（需要玩家操作） | 渲染输入区域 |
| `system` | 系统消息（阶段切换、游戏开始/结束） | 显示系统提示 |
| `phase_transition` | 阶段切换 | 渲染过场动画+新阶段标题 |

前端 → 后端（3 种）：

| 消息类型 | 说明 | 后端响应 |
|----------|------|----------|
| `player_action` | 玩家的选择或自由输入 | 路由到 Game Engine 处理 |
| `rollback_request` | 玩家请求回退 | Game Engine 执行回溯 |
| `system_command` | 暂停/继续/退出等 | Game Engine 处理 |

### 2.2 消息结构

```python
# ===== 后端 → 前端 =====

NarrativeMessage = {
  "type": "narrative",
  "id": int,                    # 递增消息 ID
  "session_id": str,
  "content": {                  # 剧情内容
    "text": str,                # 渲染文本（支持 Markdown 子集）
    "scene": str | None,        # 场景名（切换场景时携带）
    "characters_present": [str],# 当前在场角色
  },
  "timestamp": float,
}

CharacterSpeechMessage = {
  "type": "character_speech",
  "id": int,
  "session_id": str,
  "content": {
    "speaker": str,             # 发言人
    "text": str,                # 发言内容
    "emotion": str | None,      # 情绪标签（"愤怒"/"平静"/"慌张"）
    "is_streaming": bool,       # 是否正在流式传输中
    "stream_done": bool,        # 流式传输是否完成
  },
  "timestamp": float,
}

InteractionMessage = {
  "type": "interaction",
  "id": int,
  "session_id": str,
  "content": {
    "mode": "options" | "free_input" | "options_with_fallback",
    "context": str,             # 当前情境描述
    # 模式 A: options
    "options": [                 # mode=options 时必填
      {
        "id": int,
        "text": str,            # 选项文本
        "proposed_by": str,     # 提出该选项的角色
        "skill_focus": str,     # 锻炼的能力标签
      }
    ] | None,
    # 模式 B: free_input
    "allowed_actions": [str] | None,  # mode=free_input 时必填
    "examples": [str] | None,         # 示例输入
    # 模式 C: options_with_fallback
    "fallback_to_free": bool,   # 是否允许"自定义"选项切到自由输入
  },
  "timestamp": float,
}

SystemMessage = {
  "type": "system",
  "id": int,
  "session_id": str,
  "content": {
    "category": "info" | "success" | "warning" | "error",
    "text": str,
  },
  "timestamp": float,
}

PhaseTransitionMessage = {
  "type": "phase_transition",
  "id": int,
  "session_id": str,
  "content": {
    "from": str,                # 前一阶段名
    "to": str,                  # 后一阶段名
    "transition_text": str,     # 过场叙述
    "stage": "stage2" | "stage3",
  },
  "timestamp": float,
}


# ===== 前端 → 后端 =====

PlayerActionMessage = {
  "type": "player_action",
  "session_id": str,
  "content": {
    "action_type": "choose_option" | "speak" | "act" | "investigate",
    # choose_option 时
    "option_id": int | None,
    # speak/act/investigate 时
    "text": str | None,          # 玩家输入的文本
    "target": str | None,        # 行动目标角色（可选）
  },
  "timestamp": float,
}

RollbackRequestMessage = {
  "type": "rollback_request",
  "session_id": str,
  "content": {
    "steps": int,                # 回退步数
  },
  "timestamp": float,
}

SystemCommandMessage = {
  "type": "system_command",
  "session_id": str,
  "content": {
    "command": "pause" | "resume" | "exit" | "save" | "load",
  },
  "timestamp": float,
}
```

---

## 三、前端界面设计

### 3.1 页面布局

```
┌──────────────────────────────────────────────────────────────┐
│  [游戏标题]                              [设置] [保存] [退出] │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌───────────────────┐  ┌────────────────────────────────┐ │
│  │   角色面板          │  │        叙事主面板              │ │
│  │                   │  │                                │ │
│  │ 头像+角色名       │  │  [系统] 现在是介绍阶段...      │ │
│  │ 状态指示器         │  │                                │ │
│  │ (在线/已发言/待定) │  │  [张生] 在下张珙，字君瑞...   │ │
│  │                   │  │                                │ │
│  │ 所有角色列表       │  │  [崔莺莺] 妾身崔氏...        │ │
│  │ 当前轮到谁高亮     │  │                                │ │
│  │                   │  │  [红娘] 小姐...                │ │
│  │ 角色关系简图       │  │                                │ │
│  │ (信任/怀疑/中立)   │  │  ──── 当前交互 ────          │ │
│  │                   │  │                                │ │
│  └───────────────────┘  │  ▼ 输入区域 (下详)            │ │
│                          │                                │ │
│                          └────────────────────────────────┘ │
├──────────────────────────────────────────────────────────────┤
│  回溯控制栏: [◀◀ 回退5步] [◀ 回退1步] [进度条] [▶ 前进]   │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 叙事主面板设计

**消息气泡形式**，类似聊天应用但区分角色：

```
[系统消息]  —  灰色底，居中
┌────────────────────────────────┐
│  现在进入【角色介绍】阶段。     │
│  请各位依次自我介绍。          │
└────────────────────────────────┘

[角色发言]  —  左对齐，头像+气泡
  🧑 张生 ─────────────────────
│ 在下张珙，字君瑞，西洛人氏。  │
│ 今日赴京赶考，路经此处...    │
  ─────────────────────────────
  (流式输出时，文字逐个出现)

[场景描述]  —  斜体，左对齐，分割线
  ── 场景 ──
  普救寺内，月色朦胧。张生在
  庭院中徘徊，忽闻琴声...
  ──────────

[玩家选择历史]  —  右对齐，绿色
  ── 你的选择 ──
  > 我走向窗边，想要看清那人
  ──────────────
```

### 3.3 输入区域设计（三种模式）

#### 模式 A：选项

```
┌────────────────────────────────────────────┐
│  情境：红娘询问你的态度                    │
│                                            │
│  ┌──────────────────────────────────────┐  │
│  │ ○ 我坦率表达对莺莺的心意          │  │
│  │    （坦诚直率 · 角色印象锻炼）      │  │
│  ├──────────────────────────────────────┤  │
│  │ ○ 我遮掩过去，说只是路过          │  │
│  │    （含蓄掩饰 · 人物心理分析）      │  │
│  ├──────────────────────────────────────┤  │
│  │ ○ 我不回答，反问红娘的意见          │  │
│  │    （机智应对 · 对话策略分析）      │  │
│  ├──────────────────────────────────────┤  │
│  │ ○ 自定义（自由输入）               │  │  ← fallback 入口
│  └──────────────────────────────────────┘  │
│                                            │
│  [每个选项下方展示 skill_focus 标签]       │
└────────────────────────────────────────────┘
```

#### 模式 B：自由输入

```
┌────────────────────────────────────────────┐
│  你可以：说话 / 行动                      │
│                                            │
│  ┌──────────────┐                         │
│  │ 💬 说话      │  🏃 行动               │  ← 切换行为类型
│  └──────────────┘                         │
│                                            │
│  ┌──────────────────────────────────────┐  │
│  │ 输入你想说的话或做的事...            │  │
│  │                                      │  │
│  │ 示例：                               │  │
│  │ "我质问张三昨晚去了哪里"             │  │
│  │ "我走到窗边，检查有没有痕迹"          │  │
│  └──────────────────────────────────────┘  │
│                                            │
│  [发送]                                    │
└────────────────────────────────────────────┘
```

#### 模式 C：选项 + 可自定义

```
（同模式 A，但"自定义"选项始终可见）
...加上自由输入 fallback 的提示
```

### 3.4 回溯控制栏

```
┌──────────────────────────────────────────────────────────┐
│  ◀◀ -5  │  ◀ -1  │  ████████████████░░░░  (47/62)  │  ▶     │
│  回退5步   回退1步      当前进度/总步数         前进      │
└──────────────────────────────────────────────────────────┘

功能：
- 回退时，叙事面板"变暗"，显示"已回退到第 X 步"的浮层
- 前进按钮在回退后可用，重新 Forward 到最新进度
- 回退后玩家做了新选择 → 自动截断后续历史
```

---

## 四、交互流程详解

### 4.1 一次完整的"选项交互"流程

```
Step 1: 后端交互设计 sub-agent 产出一组交互点
        ↓
Step 2: Game Engine 组装 InteractionMessage
        ↓
Step 3: WebSocket → 前端
        ↓
Step 4: 前端渲染叙事面板的"当前情境" + 输入区域的选项
        ↓
Step 5: 玩家点击某一选项
        ↓
Step 6: 前端组装 PlayerActionMessage → WebSocket → 后端
        ↓
Step 7: Game Engine 接收 → 存入事件日志 → 更新剧情状态
        ↓
Step 8: Game Engine 通知角色 Agent 发生了什么事（broadcast）
        ↓
Step 9: 编剧 Agent.剧情设计 sub-agent 生成下一轮剧情推进
        ↓
Step 10: 编剧 Agent.交互设计 sub-agent 决定下一步交互模式
        ↓
Step 11: 回到 Step 1（循环）
```

### 4.2 一次完整的"自由输入交互"流程

```
Step 1: 后端交互设计 sub-agent 判定进入模式 B
        ↓
Step 2: Game Engine 发送 InteractionMessage(mode=free_input)
        ↓
Step 3: 前端渲染自由输入界面
        ↓
Step 4: 玩家输入文本 + 选择行为类型（说话/行动/搜查）
        ↓
Step 5: 前端组装 PlayerActionMessage(action_type=speak|act|investigate)
        → WebSocket → 后端
        ↓
Step 6: Game Engine 接收玩家输入
        ↓
Step 7: Game Engine 将玩家输入转发给验证 Agent
        ↓
Step 8: 验证 Agent 审核合理性
        │
        ├── 通过 → 继续到 Step 9
        │
        └── 驳回 →
              ├── Game Engine 发送 SystemMessage(warning)
              ├── 前端显示 "这个行为不太合理，因为... 请重新输入"
              └── 回到 Step 4（玩家重新输入）
        ↓
Step 9: 验证通过 → Game Engine 存入事件日志
        ↓
Step 10: Game Engine 通知编剧 Agent 更新剧情
        ↓
Step 11: Game Engine 通知所有角色 Agent 玩家行动结果
        ↓
Step 12: 继续正常剧情循环
```

### 4.3 流式输出流程

```
角色 Agent 发言时：
Step 1: Game Engine 调用 agent.respond()
Step 2: LLM 开始流式返回 token
Step 3: 每收到一批 token → 组装 CharacterSpeechMessage(is_streaming=True)
Step 4: 立即通过 WebSocket 推送到前端
Step 5: 前端逐字渲染到气泡中
Step 6: LLM 输出完成 → 推送 CharacterSpeechMessage(stream_done=True)
Step 7: 前端标记该消息完成
```

---

## 五、WebSocket 连接管理

### 5.1 连接生命周期

```
玩家打开页面
    │
    ▼
建立 WebSocket 连接（ws://host/ws?session_id=xxx）
    │
    ▼
后端创建新 Session（若 session_id 不存在）
  或恢复已有 Session（若 session_id 存在）
    │
    ▼
后端发送 SessionInitMessage：当前阶段、已发生事件列表、当前交互点
    │
    ▼
前端渲染当前游戏状态
    │
    ▼
进入正常消息循环
    │
    ▼
玩家关闭页面 / 游戏结束 → WebSocket 断开
```

### 5.2 重连设计

```
WebSocket 意外断开
    │
    ▼
前端自动重连（指数退避：1s → 2s → 4s → max 30s）
    │
    ▼
重新建立连接，附带原有 session_id
    │
    ▼
后端：
  1. 恢复 Session
  2. 发送所有"未确认"的消息（前端上次收到后到断开期间的消息）
  3. 发送当前交互点（如果之前有未完成的 interaction）
    │
    ▼
前端同步状态，继续游戏
```

---

## 六、前端技术选型建议

| 模块 | 建议 | 理由 |
|------|------|------|
| 框架 | Next.js | jubensha-ai 已验证可用，SSR 可做加载优化 |
| 状态管理 | Zustand | 轻量，简单，适合"接收消息流"场景 |
| WebSocket | `useWebSocket` (react-use-websocket) | 成熟，支持自动重连 |
| Markdown 渲染 | `react-markdown` | 叙事消息可含简单 Markdown |
| 动画 | CSS transitions + Framer Motion | 流式文字、阶段切换动画 |
| TTS (后续) | Web Speech API (免费) / 第三方 API | 接口预留 |

---

## 七、与 Agent 架构的衔接点

| 交互系统概念 | 对应 Agent 架构概念 | 说明 |
|-------------|-------------------|------|
| InteractionMessage 的 mode | 交互设计 sub-agent 的 decide_mode() | 后端决定模式后，前端按对应模式渲染 |
| PlayerActionMessage | Player Proxy Agent 的 input_handler | 前端发来的 action 需要包装为 Agent 可理解的格式 |
| 验证驳回的 warning | 验证 Agent 的 verify() | 审核结果通过 system message 反馈给玩家 |
| 选项的 skill_focus | 素材收集的教学目标 | 标注"这个选项锻炼什么能力" |
| 角色面板的关系简图 | 角色 Agent 的 relationship_map | 供前端可视化展示 |