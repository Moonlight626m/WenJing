# ADR-0004 运行期角色 Agent 改用 LangChain 工具调用（世界进度等能力封装为 tool）

- 状态：已接受
- 日期：2026-09-22
- 关联：#7（GameRuntime command/step）、ADR-0003（剧本生成 LangGraph，§4 明确运行期
  Stage2/3 的 `character`/`verifier` prompt 暂维持原状）、`design_01` §4（角色 Agent 三层分离）、
  `docs/research/langgraph-workflow-study.md` §3.5（BaseChatModel 适配 ChatLLMService 已验证）

## 背景

运行期 `CharacterAgent`（`backend/app/domain/agents/character.py`）此前是「一次性拼装上下文 +
单次 `llm.chat()`」：引擎在每轮 cycle 里把 `plot_context` / `current_direction` 广播灌进每个
角色的 `CharacterMemory`，角色再据此生成提议或反应。问题：

- 角色 Agent 无法**按需**获取世界信息（如"现在进行到第几幕""当前矛盾是什么""登场角色有谁"）；
  所有上下文必须由引擎预先灌入，prompt 随剧情增长而膨胀，且与状态演进耦合。
- 角色能力没有显式接口，扩展（新增可查询维度）需要改引擎广播逻辑，测试也只能断言 prompt 文本。

现在希望把角色 Agent 改造成基于 LangChain 的实现，把它的各项能力（查看当前世界进度等）
封装成**工具（tool）**，由模型按需调用。

## 决策

### 1. 角色 Agent 采用 LangChain `create_agent` + tools

- 用 `langchain.agents.create_agent(model, tools=..., system_prompt=...)` 组装角色 Agent；
  system prompt 仍来自 `CharacterIdentity`（稳定身份，三层分离的 identity 层不变）。
- 每轮 `propose_action` / `react_to` 走一次 `executor.ainvoke(...)`，返回最后一条 AI 文本。
- memory 层保留，作为 `view_my_memory` 工具的数据源；`plot_context` / `current_direction`
  仍被广播写入（保持快照兼容），但不再是角色获取上下文的唯一途径。

### 2. 能力封装为工具（`agents/tools.py`）

`WorldView` 是 agent 侧只读端口，工具经闭包注入 `WorldView` 与该角色 `memory`：

| 工具 | 能力 |
|------|------|
| `view_world_progress` | 阶段 / 情节点进度 / 玩家角色 / 是否终局 |
| `view_plot_log` | 最近剧情推进摘要 |
| `view_current_direction` | 当前核心矛盾与关键处境 |
| `view_story_outline` | 剧本场景大纲与情节点 |
| `view_characters` | 登场角色名册与公开背景 |
| `view_my_memory` | 自身私有记忆（提议 / 行动日志） |

真实实现 `RuntimeWorldView`（`domain/game/world_view.py`）只读 `GameRuntime.state` / `script`，
引擎仍是状态权威；为支持 `view_current_direction`，把 `direction` 纳入 `_RState` 显式状态
（可快照 `export_state` / 恢复 / 事件重放），而非仅存于各 agent 记忆。

### 3. LLM 仍走 `LLMService` 端口：`WenjingChatModel` 桥接

- 新增 `domain/agents/chat_model.py: WenjingChatModel(BaseChatModel)`，把 `LLMService` 暴露为
  LangChain 标准 ChatModel（延续 research §3.5 的推荐路线，不引入 `langchain-openai`）。
  仅实现 `_agenerate`；`bind_tools` 把工具转成 OpenAI 函数 schema 并记录。
- `domain/llm.py` 新增 `ToolCall` / `LLMReply` 与**可选能力协议** `ToolCallingLLM.chat_with_tools`：
  - `ChatLLMService` 经 OpenAI-compatible `tools` 参数实现（复用统一 `_invoke`）；
  - `UsageRecordingLLM` 转发并**逐次计量**（工具选择与最终答复各一条 `llm_usage`）；
  - 不支持工具调用的实现（确定性 fake 等）无需改动：`WenjingChatModel` 自动降级为无工具单轮。
- 依赖方向不变：桥接与工具在 domain（只 import `langchain_core`/`langchain`，与
  `generation/workflow` 引 `langgraph` 同级），`make lint-arch` 通过。

### 4. 修订"每轮每 Agent 一次 LLM 调用"

工具调用 Agent 单轮内可能往返多次（工具选择 + 最终答复，必要时更多）。ADR 将原则修订为：
**每次 LLM 往返单独计量**；工具调用上限由模型行为决定，禁止在工具内递归调用 LLM。

### 5. 测试策略

- 工具链路用 scripted LLM（实现 `chat_with_tools`：首轮请求 `view_world_progress`，次轮给答复）
  断言"请求工具 → 结果回填 → 最终提议"闭环；工具本身用假 `WorldView` 单测。
- 不实现 `chat_with_tools` 的既有 fake 走降级路径，原有 `test_game_runtime` 等无需改动。

## 后果

- 新增依赖仅 `langchain`（已是 pyproject 依赖）；未启用 token 级流式。
- `VerifierAgent` / `ScreenwriterAgent` 暂未迁移：验证器无世界查询能力、编剧为确定性逻辑；
  后续如需可同构迁移（Verifier 走 `WenjingChatModel`，Screenwriter 可暴露剧情大纲工具）。
- 工具的中间消息（tool_calls / tool 结果）**不进入事件流**，只作为单轮 LLM 上下文；
  事件溯源仍只记录最终提议 / 反应文本，快照/回溯语义不变。
- 角色 system prompt 增加"需要世界信息时先调用工具"的引导；prompt 质量依赖 provider 的
  tool-calling 能力（与 ADR-0003 §1 对 tool-call 质量不稳定的顾虑一致，故仅在运行期 agent 使用，
  生成期仍走 JSON + Pydantic 校验）。
