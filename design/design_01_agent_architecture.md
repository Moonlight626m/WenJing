# 文境 (Wenjing) — 模块设计：Agent 架构

> 本文档聚焦 Agent 体系。后续会陆续出：交互系统、游戏引擎、数据持久化、前端架构等模块。

---

## 一、总体 Agent 体系

```
┌─────────────────────────────────────────────────────────────┐
│                      Game Engine                            │
│                    (编排层 / 状态机)                          │
│                                                              │
│   ┌─────────────┐  ┌─────────────┐  ┌───────────────────┐  │
│   │  编剧 Agent  │  │  验证 Agent  │  │ 角色 Agent Cluster │  │
│   │              │  │             │  │                    │  │
│   │ · 素材收集   │  │ · 设定审核   │  │ 角色 Agent 1       │  │
│   │ · 剧情设计   │  │ · 风格审核   │  │ 角色 Agent 2       │  │
│   │ · 交互设计   │  │ · 人设审核   │  │ 角色 Agent 3       │  │
│   │              │  │ · 逻辑审核   │  │ ...               │  │
│   └─────────────┘  └─────────────┘  └───────────────────┘  │
│                                                              │
│   ┌──────────────────────────────────────────────────┐      │
│   │              Shared Services Layer                │      │
│   │  LLM Service (单例) | Memory Store | RAG (后续)   │      │
│   └──────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

### 关键设计原则

1. **所有 Agent 共享同一个 LLM Service 实例** — 避免连接池膨胀，统一管理 token 速率 TODO
2. **Agent 间不直接通信** — 一律通过 Game Engine 中转（事件总线模式）
3. **每轮对话只有一次 LLM 调用** — 每个 Agent 的 respond() 方法只调一次 LLM，减少开销
4. **验证 Agent 异步化** — 不阻塞主流程，验证失败通过回调/事件通知回 Engine

---

## 二、编剧 Agent (Screenwriter Agent)

### 2.1 职责边界

编剧 Agent 是整个游戏的内容引擎，输出两种产物：**剧本**（Stage1）和 **剧情推进**（Stage2/3）。

### 2.2 内部结构：三个 sub-agent

```
                编剧 Agent
                    │
        ┌───────────┼───────────────┐
        ▼           ▼               ▼
   素材收集      剧情设计        交互设计
   sub-agent    sub-agent       sub-agent
        │           │               │
        ▼           ▼               ▼
   ┌────────┐ ┌──────────┐ ┌──────────────┐
   │ 作品背景 │ │ 事件序列  │ │ 交互点生成     │
   │ 时代设定 │ │ 角色行动线 │ │ 选项设计       │
   │ 人物形象 │ │ 分支条件  │ │ 僵局检测       │
   │ 前置情节 │ │ 结局判定  │ │ 模式切换决策   │
   └────────┘ └──────────┘ └──────────────┘
```

### 2.3 素材收集 sub-agent

**输入**：课文原文  
**知识源**：课文 + RAG 检索（网络解读资源、教案、时代背景资料）  

**输出 Schema** (JSON)：

```python
MaterialCollectionOutput = {
  "work_title": str,              # 课文/作品名称
  "author": str,                  # 作者
  "era_setting": {                # 时代背景
    "dynasty_or_period": str,     # 朝代/时期
    "social_context": str,        # 社会背景
    "cultural_notes": [str],      # 关键文化常识
  },
  "characters": [                 # 角色形象构建（每个角色一条）
    {
      "name": str,
      "role_in_plot": str,        # 在课文中的角色定位
      "personality_analysis": str, # 性格分析（基于课文 + 教案解读）
      "key_relationships": [      # 关键关系
        {"with": str, "nature": str, "evidence_from_text": str}
      ],
      "character_arc": str,       # 人物弧光（从开端到结局的变化）
    }
  ],
  "plot_summary": {               # 情节概要
    "premise": str,               # 前置情节（课文节选前发生了什么）
    "main_conflict": str,         # 主要矛盾
    "key_scenes": [               # 关键场景
      {
        "title": str,
        "participants": [str],
        "core_event": str,
        "significance": str,      # 该场景在全文中的作用
      }
    ],
    "ending": str,                # 课文结局
  },
  "thematic_analysis": {          # 主题分析（来自教案）
    "core_theme": str,
    "symbolic_elements": [str],   # 意象/象征元素
    "pedagogical_focus": [str],   # 教学重点（用于设计互动时"锻炼学生"）
  }
}
```

### 2.4 剧情设计 sub-agent

**输入**：
- 素材收集输出
- 当前游戏状态（已发生的事件、玩家历史选择）
- 当前阶段（Stage2/3）

**输出 Schema**：

```python
# ===== Stage1 产物：完整剧本 =====
ScriptOutput = {
  "script_summary": {
    "title": str,
    "total_expected_duration": int,  # 预期交互轮次
    "character_slots": [             # 所有角色 slot
      {"name": str, "is_player_playable": bool}
    ],
  },
  "scenes": [                        # 场景序列
    {
      "scene_id": int,
      "title": str,
      "location": str,
      "participants": [str],          # 参与角色
      "stage": "stage2" | "stage3",  # 属于哪个阶段
      "summary": str,                 # 场景概述
      "expected_beats": [             # 预期情节点
        {
          "beat_id": int,
          "description": str,
          "trigger_condition": str,   # 触发条件（"玩家入场" / "上场景结束"）
          "key_dialogue_or_action": str,
          "pedagogical_value": str,   # 该点的教学价值
        }
      ],
    }
  ],
  "character_settings": [            # 角色设定（给角色 Agent 的 identity）
    {
      "name": str,
      "public_background": str,      # 公开背景（所有角色都可见）
      "private_secret": str,         # 私有秘密（仅该角色可知，Stage2 按课文）
      "personality_traits": [str],   # 性格特征
      "goals": {                     # 目标
        "stage2": str,               # 还原阶段的目标
        "stage3": str,               # 续写阶段的目标
      },
      "voice_style": str,            # 语言风格（如有课文依据）
    }
  ],
}

# ===== Stage2/3 产物：单次剧情推进 =====
PlotAdvancement = {
  "scene_update": {                   # 当前场景状态更新
    "current_location": str,
    "present_characters": [str],
    "recent_events_summary": str,     # 刚发生了什么
  },
  "available_actions": [              # 当前可选行动（给 交互设计 sub-agent 参考）
    {
      "action_id": int,
      "type": "speak" | "act" | "investigate",
      "description": str,
      "suggested_by": str,            # 哪个角色提出的
      "expected_outcome": str,
    }
  ],
  "next_scene_trigger": str,          # 推进到下一场景的条件
  "pedagogical_focus": str,           # 本轮教学重点（用于验证 Agent 评估交互质量）
}
```

### 2.5 交互设计 sub-agent

**职责**：决定"当前给玩家/角色 Agent 什么样的交互形式"，以及"是否切换交互模式"。

**核心逻辑**：

```python
class InteractionDesigner:
    """
    交互设计器，每次剧情推进后调用。
    决定下一轮的交互模式（A/B/C），并生成交互点。
    
    模式值对齐 design_02 的线协议（InteractionMessage.content.mode）：
      A = "options"                 # 选项驱动
      B = "free_input"              # 玩家自由输入
      C = "options_with_fallback"   # 选项 + 自定义回退
    """
    
    MODE_A = "options"               # 选项驱动
    MODE_B = "free_input"            # 玩家自由输入
    MODE_C = "options_with_fallback" # 交替模式
    
    def decide_mode(
        self,
        current_stage: str,            # "stage2" | "stage3"
        recent_agent_proposals: list,  # 最近角色 Agent 的提议列表
        recent_player_inputs: list,    # 最近玩家输入
        rejection_count: int,          # 连续被驳回次数
        plot_urgency: str,             # "climax" | "normal" | "stalemate"
    ) -> str:
        """
        决定下一轮交互模式。
        
        规则（按优先级）：
        
        Rule 1: 僵局检测
          if plot_urgency == "stalemate" or rejection_count >= 3:
            return MODE_B  # 放权给玩家，打破僵局
        
        Rule 2: 剧情高潮
          if plot_urgency == "climax":
            return MODE_A  # 关键情节，用选项保持可控
        
        Rule 3: Stage2 默认
          if current_stage == "stage2":
            return MODE_A  # 还原阶段以选项为主
        
        Rule 4: 角色提议丰富
          if len(recent_agent_proposals) >= 2:
            return MODE_A  # 角色有好的提议，生成选项
        
        Rule 5: 玩家连续无效输入
          if recent_player_inputs and self._is_all_invalid(recent_player_inputs):
            return MODE_A  # 切回选项引导
        
        Rule 6: Stage3 默认
          if current_stage == "stage3":
            return MODE_C  # 交替模式
    ```
    
    def generate_interaction_points(
        self,
        mode: str,
        plot_advancement: PlotAdvancement,
        character_proposals: list,
        player_context: dict,
    ) -> InteractionPoints:
        """
        根据模式生成具体的交互点。
        """
        if mode == MODE_A:
            # 从有效的角色提议中，选取 2-4 个包装为选项
            approved = self._filter_proposals(character_proposals)
            return InteractionPoints(
                mode="options",
                options=[
                    Option(
                        id=i,
                        text=p["description"],
                        outcome_hint=p.get("expected_outcome", ""),
                        proposed_by=p["suggested_by"],
                        # 标注每个选项锻炼的能力
                        skill_focus=self._infer_skill_focus(p),
                    )
                    for i, p in enumerate(approved)
                ],
                background=plot_advancement.scene_update,
            )
        
        elif mode == MODE_B:
            # 给玩家自由输入框，但限定行为类型
            return InteractionPoints(
                mode="free_input",
                allowed_action_types=["speak", "act"],
                context_hint="请描述你想做的事或想说的话",
                examples=["我想质问张三昨晚的去向", "我走到窗边检查痕迹"],
                background=plot_advancement.scene_update,
            )
        
        elif mode == MODE_C:
            # 先给选项，如果玩家都选了"其他/自定义"，切到自由输入
            return InteractionPoints(
                mode="options_with_fallback",
                options=[...],
                fallback_to_free=True,
                background=plot_advancement.scene_update,
            )
```

### 2.6 编剧 Agent 完整流程图

```
用户导入课文
    │
    ▼
素材收集 sub-agent
    │  分析课文 + RAG 检索教案/解读
    │  输出：时代背景、角色形象、情节概要、主题分析
    ▼
剧情设计 sub-agent
    │  基于素材输出，创建完整剧本
    │  输出：场景序列、角色设定表
    ▼
验证 Agent 审核完整剧本
    │  通过 → 进入 Stage2
    │  驳回 → 编剧调整
    ▼
[Stage2 循环]
    验证 Agent 推送当前剧情摘要给所有角色 Agent
        │
        ▼
    角色 Agent 提出行动提议（基于课文情节 + 角色性格）
        │
        ▼
    验证 Agent 审核提议
        │  通过 → 加入 available_actions 候选池
        │  驳回 → 角色 Agent 记录"此路不通"
        ▼
    交互设计 sub-agent
        │  1. 收集所有有效提议
        │  2. 判定交互模式（A/B/C）
        │  3. 生成交互点
        ▼
    玩家/角色执行 → 更新剧情状态
        │
        ▼
    剧情设计 sub-agent 更新剧情
        │
        ▼
    检查是否到达课文结局
        否 → 继续 Stage2 循环
        是 → 过渡到 Stage3
    │
    ▼
[Stage3 循环]
    类似 Stage2，差异：
    · 验证从"不偏离课文"切到"不偏离人设"
    · 角色提议不再受课文限制
    · 交互模式更倾向 C（交替模式）
    · 持续运行直到玩家退出
```

---

## 三、验证 Agent (Verifier Agent)

### 3.1 职责边界

验证 Agent 是"**质量门禁**"，不生产内容，只评估内容是否合规。它是一个**决策模型**而非生成模型——输出的是通过/驳回 + 原因。

### 3.2 验证维度详解

| 维度 | 验证对象 | 判断依据 | 驳回时可提供的反馈 |
|------|----------|----------|-------------------|
| **作品设定** | 编剧的剧情产出 | 时代背景、社会规范、地理/历史常识 | "这个情节存在 XX 历史错误" |
| **作品风格** | 编剧的剧情产出 | 语言风格（白话/文言）、叙事语调（严肃/诙谐） | "语言风格与原文不符，原文是 XX 风格" |
| **角色人设** | 角色 Agent 的行动提议 | 角色身份、性格、秘密、背景 | "这个行为不符合 XX 的性格" |
| **剧情逻辑** | 编剧的剧情产出 | 因果关系、时间线、事件连贯性 | "事件 A 和 B 存在矛盾，因为 XX" |
| **交互质量** | 交互设计产出的交互点 | 教学价值、难度适配、学生参与度 | "这个选项没有教学价值，建议改为 XX" |

### 3.3 调用模式

```python
class VerifierAgent:
    """
    验证 Agent。两种调用模式：同步（阻塞）和异步（非阻塞）。
    同步用于关键路径（如完整性剧本审核），异步用于常规剧情推进中的验证。
    """
    
    # ===== 同步调用（Stage1 剧本审核、Stage 切换） =====
    async def verify_script(self, script: ScriptOutput) -> VerificationResult:
        """验证完整剧本，阻塞。"""
        ...
    
    # ===== 异步调用（Stage2/3 每次剧情推进时）= ====
    async def verify_plot_advancement(
        self, advancement: PlotAdvancement, character_proposals: list
    ) -> VerificationResult:
        """验证单次剧情推进。"""
        ...
    
    async def verify_character_action(
        self, character_name: str, action: dict, character_setting: dict
    ) -> VerificationResult:
        """验证单个角色的行动提议。"""
        ...
```

**验证结果 Schema**：

```python
VerificationResult = {
  "verdict": "pass" | "reject" | "conditional_pass",
  "score": float,                  # 0.0 - 1.0，综合评分
  "dimension_scores": {            # 各维度评分
    "setting_accuracy": float,
    "style_fidelity": float,
    "character_consistency": float,
    "plot_logic": float,
    "interaction_quality": float,
  },
  "rejections": [                  # 仅 reject 时
    {
      "dimension": str,
      "reason": str,               # 驳回原因
      "suggestion": str,           # 修改建议
      "reference": str,            # 参考依据（课文原文/教案解读）
    }
  ],
  "warnings": [                    # 非致命问题，conditional_pass 时出现
    {
      "dimension": str,
      "severity": "low" | "medium",
      "note": str,
    }
  ],
}
```

### 3.4 驳回与重试机制

```
角色 Agent 提出行动提议
    │
    ▼
验证 Agent 审核
    │
    ├── pass → 加入候选池，进入下一流程
    │
    ├── conditional_pass → 加入候选池，但标记 warning，编剧/交互设计参考
    │
    └── reject →
          ├── 有明确的修改方向？ → 返回 suggestion 给提出者
          │   角色 Agent 自动调整后重提（最多 2 次）
          │
          └── 无法修改（方向根本不对）？
                ├── 角色 Agent 放弃该提议
                └── 如果所有角色提议都被驳回
                    → 交互设计 sub-agent 检测到"僵局"
                    → 切模式 B，放权给玩家
```

### 3.5 降级策略

当 LLM 调用失败或超时时，验证 Agent 不会阻塞流程：

```
if LLM call fails:
    if 是 Stage1 完整剧本审核:
        retry 1 次 → 失败则报错给用户，无法继续
    else:
        # Stage2/3 常规验证，降级
        use rule-based 快速验证（非 LLM）
        - 仅检查基本结构完整性
        - 无维度评分，默认 conditional_pass
        - 记录日志供后续人工审查
```

---

## 四、角色 Agent (Character Agent)

### 4.1 整体架构

继承 jubensha-ai 的三层分离设计，做针对性调整：

```
                 CharacterAgent
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   Identity Layer  Memory Layer   Director Layer
   (稳定 system    (分层记忆)     (阶段指令构建)
    prompt)                           │
        │              │              ▼
        ▼              ▼        ┌─────────────┐
   ┌──────────┐  ┌──────────┐  │ 响应生成流程  │
   │ 角色背景   │  │工作记忆   │  │ 1. 取 system │
   │ 性格特征   │  │私有日志   │  │ 2. 取记忆    │
   │ 私有秘密   │  │关系图谱   │  │ 3. 取阶段指令│
   │ 教学目标   │  │剧情摘要   │  │ 4. → LLM    │
   └──────────┘  └──────────┘  └─────────────┘
```

### 4.2 Identity Layer

与 jubensha-ai 相同的定位：only 包含"我是谁"，不包含任何阶段行为指令。

```python
class CharacterIdentity:
    """
    稳定的角色身份。游戏全程不变。
    来源：编剧 Agent.剧情设计输出的 character_settings
    """
    
    name: str                   # 角色名
    public_background: str      # 公开背景
    private_secret: str         # 私有秘密（仅该角色可知）
    personality_traits: list[str]  # 性格特征
    goals: dict                 # 各阶段目标 {stage2: ..., stage3: ...}
    voice_style: str            # 语言风格
    pedagogical_focus: list[str]  # 教学关注点（如"练习人物形象分析"）
    
    def to_system_prompt(self) -> str:
        """
        生成稳定 system prompt。
        与 jubensha-ai 不同的是：
        1. 增加了教学目标提示（帮助学生理解角色的方式）
        2. 规定了 Stage2 和 Stage3 的角色目标
        """
        return f"""
        你是【{self.name}】。
        
        背景：{self.public_background}
        性格：{'、'.join(self.personality_traits)}
        
        【重要规定】
        1. 完全沉浸角色，不要有任何 AI 视角
        2. 只说角色会公开说的话，不要内心独白
        3. 语言风格：{self.voice_style}
        4. Stage2 中：按照课文原情节行动，不偏离
        5. Stage3 中：在设定内自由发挥，但仍保持人设一致
        """
```

### 4.3 Memory Layer

针对文境场景做了扩展：

```python
class CharacterMemory:
    """
    分层记忆系统。
    针对文境场景的扩展：
    - 增加 plot_context: 由编剧 Agent 推送的当前剧情摘要
    - relationship_map 替代 suspicion_map（更通用）
    - working_memory 窗口更大（50 条，因为课文剧情更长）
    """
    
    # 短期记忆
    working_memory: deque[PublicSpeech]  # maxlen=50
    
    # 长期记忆（私有）
    personal_log: list[PersonalEvent]    # 自己的行动/发现/推理
    
    # 关系图谱
    relationship_map: dict[str, RelationshipState]
    # RelationshipState = {trust: 0.0-1.0, familiarity: 0.0-1.0, conflict: 0.0-1.0}
    
    # 剧情上下文（由编剧 Agent 推送）
    plot_context: str
    
    # 被驳回记录
    rejected_proposals: list[dict]       # 记住什么提议被驳回过，避免重复
```

**剧情摘要推送机制**：

```
每次剧情推进后，编剧 Agent 生成当前剧情摘要
→ 通过 Game Engine 广播给所有角色 Agent
→ 角色 Agent 更新 memory.plot_context

plot_context 内容：
  - 当前场景名/地点
  - 已发生的关键事件（1-3 句摘要）
  - 当前在场的其他角色
  - 自己刚做了什么（上次行动结果）
```

### 4.4 Director Layer

与 jubensha-ai 不同，文境的 PhaseDirector 需要处理更多阶段类型：

```python
class PhaseDirector:
    """
    阶段指令构建器。
    针对文境扩展：
    - Stage2 vs Stage3 的指令差异
    - 模式 A/B/C 的指令差异
    - 教学目标的嵌入
    """
    
    def build_user_message(
        self,
        stage: str,               # "stage2" | "stage3"
        mode: str,                # "A" | "B" | "C"
        identity: CharacterIdentity,
        memory: CharacterMemory,
        game_state: dict,
    ) -> str:
        """
        构建完整的 user message 结构如下：
        
        1. 剧情上下文（来自 memory.plot_context）
        2. 工作记忆摘要（最近的 5-10 条对话）
        3. 私有记忆（自己的行动记录）
        4. 关系状态（对其他角色的信任/冲突程度）
        5. 当前阶段特别指令
        6. 目标提示（根据角色设定中的 goals）
        
        Stage2 特别指令示例：
        "你现在处于【剧情还原】阶段。请按照课文原情节行动。
         不要发明不在原文中的重大事件。
         如果其他角色提出偏离课文的行为，应该纠正。"
        
        Stage3 特别指令示例：
        "你现在处于【剧情续写】阶段。可以在设定内自由发挥。
         保持你的人物性格一致，但可以自由提出新的行动方向。
         如果你对其他角色有想法，可以提出来。"
         
        Mode A 特别指令：
        "本轮以选项形式交互。请向交互设计师提交你的提议，
         提议会是选项的来源之一。"
        
        Mode B 特别指令：
        "本轮玩家将自由行动。请观察玩家的行为并做出反应。"
        """
```

### 4.5 角色 Agent 响应流程

```python
async def respond(self, stage, mode, game_state) -> str:
    """
    一次完整的响应流程，只有一次 LLM 调用。
    """
    # 1. 组装 system prompt（稳定身份）
    system_prompt = self.identity.to_system_prompt()
    
    # 2. 构建 user message（动态指令）
    user_message = self.director.build_user_message(
        stage, mode, self.identity, self.memory, game_state
    )
    
    # 3. 调用 LLM
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    response = await self.llm.chat(messages)
    
    # 4. 解析响应
    # 响应可能是两种格式：
    #   a) 直接发言（普通对话）—— 纯文本
    #   b) 结构化提议（给交互设计器的输入）—— 包裹在 ```proposal JSON``` 代码块中
    # 区分方式：用正则匹配 JSON 代码块标记。命中则解析为 Proposal 并剥离标记文本；
    #           未命中则整体视为直接发言。
    proposal_match = re.search(
        r"```proposal\s*(\{.*?\})\s*```", response, re.DOTALL
    )
    if proposal_match:
        proposal = Proposal.parse_raw(proposal_match.group(1))
        self.memory.record_personal_event(
            f"我提议：{proposal.description}(期待 {proposal.expected_outcome})"
        )
        return proposal
    else:
        self.memory.record_personal_event(f"我说：{response}")
        return response
```

### 4.6 Character Agent 管理（CharacterAgentManager）

角色 Agent 由 `CharacterAgentManager` 统一管理（design_03 的 `self.characters`）。它在引擎与各个角色 Agent 之间做一对多编排，负责实例创建、并行提议/反应、剧情上下文广播与记忆恢复。

```python
class CharacterAgentManager:
    """
    角色 Agent 集群管理器。
    职责：
    - 按剧本初始化角色 Agent（identity 来自 ScriptOutput.character_settings）
    - 向所有角色并行分发"提议/反应"任务
    - 统一广播 plot_context / direction 给各角色
    - 处理单角色重提（被验证驳回后）与记忆快照恢复
    """
    
    def __init__(self):
        self.agents: dict[str, CharacterAgent] = {}
        self.player_role: str | None = None
    
    def create_agents(self, character_settings: list[dict]) -> None:
        """Stage1 结束后，按角色设定初始化所有角色 Agent。"""
        for setting in character_settings:
            name = setting["name"]
            self.agents[name] = CharacterAgent(setting)
            if setting.get("is_player_playable"):
                self.player_role = name
    
    def active_names(self, include_player: bool = False) -> list[str]:
        """返回参与本轮调度的角色名。玩家扮演的角色默认可选排除。"""
        return [
            name for name in self.agents
            if include_player or name != self.player_role
        ]
    
    async def propose_action(self, name: str, stage: str) -> Proposal:
        """让单个角色提出行动提议（一轮一次 LLM）。"""
        return await self.agents[name].respond(stage=stage, mode="options")
    
    async def retry_proposal(
        self, original: Proposal, rejections: list[dict]
    ) -> Proposal | None:
        """
        被验证驳回后，携带 suggestion 让角色调整并重提。
        角色选择放弃时返回 None。
        """
        agent = self.agents[original.proposed_by]
        return await agent.revise_proposal(original, rejections)
    
    async def react(self, name: str, player_action: dict) -> str:
        """角色对玩家操作做出反应（Mode B/C 时也用于自由输入反应）。"""
        return await self.agents[name].respond(
            stage="current", mode="free_input", player_action=player_action
        )
    
    def broadcast_plot_context(self, summary: str) -> None:
        for agent in self.agents.values():
            agent.memory.plot_context = summary
    
    def broadcast_direction(self, direction: dict) -> None:
        """广播 D5 方向确认的结果（当前矛盾/关键处境）。"""
        for agent in self.agents.values():
            agent.memory.current_direction = direction
    
    def restore_memories(self, snapshot: dict) -> None:
        """回溯/恢复时还原各角色记忆。"""
        for name, memory in snapshot.items():
            self.agents[name].memory = memory
```

> 与 design_03 衔接：`CharacterAgentManager` 被 `GameEngine._collect_character_proposals`、`_verify_proposals`（重试）、`_collect_character_reactions`、`_execute_rollback`（记忆恢复）调用。
> 并行性（`asyncio.gather`）与并发上限由引擎的 AgentScheduler（design_03 §5）负责，Manager 只做任务的组织与结果聚合。

---

## 五、LLM 调用优化

### 5.1 单例共享

```python
# 所有 Agent 共享同一个 LLM Service 实例
# 原因：避免每个 Agent 持有独立连接池，统一管理 token 速率

class LLMService:
    """单例模式"""
    _instance = None
    
    def __init__(self, config):
        self.client = OpenAI(...)  # 或其他 provider
        self.semaphore = asyncio.Semaphore(5)  # 最大并发 5
        self.token_bucket = TokenBucket(rate=...)
```

### 5.2 每轮只有一次 LLM 调用

每个 Agent 的 `respond()` 方法（在 Game Engine 调度时）只调用一次 LLM。避免"Agent 内部 call 多次 LLM"的模式（如 jubensha-ai 中没有此问题，只需保持）。

### 5.3 消息量控制

User message 的长度随游戏进程增长。控制策略：

```
角色 Agent 的 user message 大小 ≈ system prompt + memory context + phase instruction

system prompt: ~500 tokens（稳定）
memory context:
  - plot_context: ~500 tokens（固定摘要，不累计）
  - 工作记忆摘要: ~1000 tokens（最近 5-10 条，不是全部 50 条）
  - 个人日志: ~500 tokens（最近 3-5 条）
  - 关系状态: ~200 tokens
phase instruction: ~500 tokens
------------------------------------------------
总计: ~2700-3200 tokens / 次 LLM 调用
```

---

## 六、与 jubensha-ai 的对比总结

| 维度 | jubensha-ai | 文境 |
|------|-----------|------|
| Agent 类型 | 角色 Agent + GM Agent | 编剧 Agent (含3 sub-agent) + 验证 Agent + 角色 Agent |
| 角色 Agent 架构 | 三层分离 | 三层分离（继承 + 扩展） |
| 交互模式 | 单模式（对话） | 三模式动态切换（A/B/C） |
| 验证 | 无 | 五维验证 + 驳回重试 |
| 阶段规划 | GM Agent 动态规划 | 编剧 Agent 的剧情设计 sub-agent 规划 |
| 记忆 | working + personal + suspicion | working + personal + relationship + plot_context |
| LLM 策略 | 单例共享 | 单例共享（一致） |
| 响应频率 | 每 Agent 每轮一次 | 每 Agent 每轮一次（一致） |