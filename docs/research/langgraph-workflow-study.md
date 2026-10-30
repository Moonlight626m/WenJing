# LangGraph 1.x 剧本生成 workflow 开发参考

> 调研日期：2026-09-20
> 调研方式：官方一手文档（`docs.langchain.com/oss/python/langgraph/*`，LangGraph 1.x 文档站）+
> **本仓库已安装包源码实测**（`backend/.venv`：langgraph 1.2.11 / langchain-core 1.5.5 /
> langchain 1.3.15 / langgraph-checkpoint 4.2.0 / langgraph-prebuilt 1.1.0 / openai 3.1.0 / Python 3.11）。
> 所有「已验证」结论均来自可运行的最小脚本（`/tmp/opencode/langgraph_probe/`，用
> `cd backend && uv run python /tmp/opencode/langgraph_probe/xxx.py` 实跑），未实跑的 API 明确标注「未运行验证」。
> 为验证 PG checkpointer，临时向 `.venv` 安装了 `langgraph-checkpoint-postgres 3.1.2` +
> `psycopg[binary]`（**未改动 `pyproject.toml` / `uv.lock` / 任何业务代码**，`uv sync` 即可还原）。

## 1. TL;DR

**版本矩阵**（以仓库 venv 实测为准）：

| 包 | 版本 | 状态 |
|---|---|---|
| langgraph | 1.2.11 | 已装 |
| langchain-core | 1.5.5 | 已装 |
| langchain | 1.3.15 | 已装 |
| langgraph-checkpoint | 4.2.0 | 随 langgraph 装好 |
| langgraph-prebuilt | 1.1.0 | 已装（含 RetryPolicy 等旧 re-export） |
| langgraph-checkpoint-postgres | 3.1.2 | **需另装**（probe 验证时装入 venv，#28 要正式加入依赖） |
| langchain-openai | 未装 | 若走 `init_chat_model("openai:...")` 路径需另装 |

**关键结论（全部已验证）**：

1. `interrupt()`（正 API）+ `Command(resume=...)` + **持久 checkpointer** 完全满足教师闸门：
   跨进程（新进程重建 graph + 同一 `thread_id`）可从 `AsyncPostgresSaver` 精确恢复到中断点，
   `resume` 前还能 `aget_state` 读到快照（`next=("gate",)`）。
2. `Send` fan-out 真并行成立：4 个 async 节点（各 sleep 0.5s）全部在 t≈0.005s 同时启动，
   join 靠 `Annotated[list, operator.add]` reducer 收集。
3. 状态 schema 推荐 **TypedDict + Annotated reducers**；Pydantic 模型也能用但有两个坑
   （见 §3.1：坏输入会污染 thread 的 checkpoint；invoke 默认返回 dict 而非模型实例）。
4. 自定义 `BaseChatModel` 适配我们 `ChatLLMService` 可行且已跑通；`with_structured_output`
   在自定义模型上直接 `NotImplementedError`（需自实现或走节点内 JSON 解析）。
5. 重试：`add_node(..., retry_policy=RetryPolicy(...))`（**不是 `retry=`，旧参数已 deprecated**）；
   且 `default_retry_on` **不重试 RuntimeError**——LLM 适配层必须显式 `retry_on` 或自捕获。
6. 进度观测推荐 `graph.astream(..., stream_mode="updates", version="v2")`：统一 `StreamPart`
   格式（`type/ns/data`），逐节点更新事件，粒度与开销都合适。`stream_events(version="v3")`
   是 1.2 新的 typed-projection API（**标 experimental**，`LangChainBetaWarning`），暂不采用。

**我们采纳的模式清单**：
- 图骨架：`StateGraph(TypedDict)` 线性主干（素材收集→考证→事件划分→人物并行→剧本书写→校验→总审）+ 条件边打回；
- 人物并行：`add_conditional_edges(START, fan_out)` 发 `Send`，`Annotated[list[...], operator.add]` 收集；
- 教师闸门：节点内 `interrupt(payload)` + `Command(resume=...)` + `aupdate_state` 注入教师编辑；
- 持久化：`AsyncPostgresSaver`（独立表，非 Alembic 管），`thread_id` = 剧本生成会话 ID；
- LLM：`BaseChatModel` 子类包装 `ChatLLMService`（保留 token 计量与 purpose 分类）；
- 观测：`astream(stream_mode="updates", version="v2")` 逐节点写 `generation_state`。

---

## 2. 核心概念速查（映射到我们的节点）

| 我们的工作流（issue #27-#34） | LangGraph 概念 | 形态 |
|---|---|---|
| 素材收集→考证→事件划分→…→总审 | `StateGraph` + `add_edge` 线性主链 | `add_edge("material", "verify")` |
| 全局 doubter 打回 | 条件边回环（targeted 循环） | `add_conditional_edges("doubter", route)`，`route` 返回 `"revise"` 回上游或 `END` |
| 打回次数上限 | 条件边内判断 + 失败节点 | `round >= MAX → "fail"` 边（不要靠 recursion_limit 兜底） |
| 每主要人物独立 agent | `Send` fan-out（map-reduce） | 条件边返回 `[Send("character_agent", {...}) for ...]` |
| 人物设定合并裁决 | join 节点 + reducer | `profiles: Annotated[list, operator.add]`，fan-out 边都指向 join 节点 |
| 教师分阶段闸门 | `interrupt()` + `Command(resume=...)` | 节点内动态暂停，checkpointer 持久化 |
| 教师编辑注入 | `aupdate_state` / resume 值本身 | 见 §3.3 |
| 每节点状态落库 | `astream(stream_mode="updates")` 事件 | 每个 `updates` 事件 = 一个节点的输出 |
| 断点暂停/进程重启恢复 | `AsyncPostgresSaver` + `thread_id` | 见 §3.4 |

> 对照：旧 design_01 的「Agent 间不直接通信、经 Game Engine 中转」在 LangGraph 语境下
> 自然映射为「节点只读写共享 State，节点间不互相调用」——语义一致，可沿用。

---

## 3. 主题详解

### 3.1 StateGraph 核心与 State schema

**官方 API 现状（1.2.11 源码确认）**：
- `StateGraph(state_schema)` → `add_node(name, fn, retry_policy=..., timeout=...)` /
  `add_edge(a, b)` / `add_conditional_edges(source, router, path_map)` /
  `compile(checkpointer=...)`；入口 `START`、出口 `END`（`from langgraph.graph import END, START, StateGraph`）。
- 节点函数：`(state) -> dict`（部分更新，走 channel 合并）或返回 `Command(goto=..., update=...)`。
- 条件边 router 返回：节点名 / 节点名列表 / `Send` 列表 / `END`；
  传 `path_map` 可把返回值映射到节点并约束可选边（利于画图与校验）。
- `recursion_limit` 是调用 config（`config={"recursion_limit": 50}`），**默认 25**；
  超限抛 `langgraph.errors.GraphRecursionError`（已验证）。

**TypedDict + Annotated reducer（推荐）**：
```python
import operator
from typing import Annotated, TypedDict

class State(TypedDict):
    draft: str                                   # last_value（默认覆盖）
    doubter_notes: Annotated[list[str], operator.add]  # 累加合并
```
- 无 Annotated 的 key 是 **last-value channel**：并行写同一 key 会报
  `INVALID_CONCURRENT_GRAPH_UPDATE`（官方错误页）；并行 fan-out 的输出**必须**走 reducer。
- 已验证：probe_a（counter + 打回循环 + 上限失败边）、probe_b（reducer join）。

**Pydantic 模型作为 State（可用但有坑，已验证 probe_g）**：
- 好处：输入/更新会经 `schema(**input)` 强校验（坏类型直接 `ValidationError`）。
- 坑 1：**坏输入会在写 checkpoint 后、跑节点前才炸**——该 thread 留下被污染的 checkpoint，
  之后同一 thread 的 `aget_state` / 再 invoke 也会在校验时抛错（实测复现两次）。
  → 生产上输入校验应在进图之前自己做，或坏输入换新 thread。
- 坑 2：`ainvoke` 返回的是 **dict**（v1 默认；`version="v2"` 才 coerce 回模型实例），节点内拿到的是模型实例。
- 坑 3：`Annotated[list, operator.add]` 在 Pydantic 里可写，默认值要用 `Field(default_factory=list)`。
- checkpointer serde：默认 `JsonPlusSerializer`（ormsgpack）对 Pydantic v2 模型有原生支持，
  存储侧无障碍（snapshot.values 读回是 dict）。

**我们怎么用**：主状态用 TypedDict + reducers；输出摘要另存（JSONB 自有表，见 §3.4 取舍）。
不引入 Pydantic State（校验收益低、污染坑真实存在）。

### 3.2 Send 并行 fan-out / map-reduce（每人物并行）

**已验证（probe_b）**：标准写法是从条件边发 `Send`：

```python
class OverallState(TypedDict):
    characters: list[str]
    profiles: Annotated[list[dict], operator.add]   # reducer：join 收集

def fan_out(state: OverallState):
    return [Send("character_agent", {"name": n}) for n in state["characters"]]

async def character_agent(state: CharInput):   # CharInput 可与 OverallState 不同！
    profile = await llm(...)                   # Send 的 arg 就是该节点的输入 state
    return {"profiles": [profile]}             # 只写自己那份，reducer 合并

builder.add_node("character_agent", character_agent)
builder.add_conditional_edges(START, fan_out)  # Send 必须从条件边发出
builder.add_edge("character_agent", "merge")   # 所有实例结束后进 join
```

要点：
- 并行已实测：4 个任务 `start` 全部在 t=0.005s（串行时第 4 个会 ≥1.5s）。
- **fan-out 后直接 `add_edge("character_agent", "merge")`**：同一 super-step 的所有实例完成后
  才进入下一 super-step，join 节点读到的 `profiles` 已是合并结果（Pregel 超步语义）。
- `Send(node, arg)` 的 `arg` 是该实例的完整输入 state（类型可不同于 OverallState）；
  实例间不共享状态，互不干扰。
- 与 checkpointer 兼容：每个 Send 实例是独立 task，写 `checkpoint_writes` 按行存
  （这就是官方文档 pending-writes 机制，部分实例失败不需重跑成功者）。

**坑**：
- `Send` 只能从 `add_conditional_edges` 的 router 发出，不能写在节点返回值里（那是 `Command(goto=[Send...])`，也能发但语义不同——`goto` 是节点内动态跳转，两者都合法；已读源码确认 `Command.goto` 接受 `Send | Sequence[Send]`，未单独实跑）。
- fan-out 节点若需要 `interrupt()`（并行分支同时中断），resume 要用 `{interrupt_id: value}` 映射（官方文档「Handling multiple interrupts」模式；未实跑，#32 若人物级人工干预再验证）。

### 3.3 Human-in-the-loop / 教师闸门（interrupt）

**官方 API 现状（1.x 正 API，已验证 probe_c1）**：
- 节点内调用 `interrupt(payload)`：首次抛 `GraphInterrupt` 暂停并把 `payload`（须 JSON 可序列化）抛给调用方；
  **resume 后节点从头重跑**，第二次执行时 `interrupt()` 直接返回 resume 值（不抛异常）。
- 输入侧用 `Command(resume=...)` 恢复；结果在 `result["__interrupt__"]`（v1 默认形态）。
- 旧的 `interrupt_before/interrupt_after`（静态断点）**仍存在**但官方明确「不推荐用于 HITL」，
  仅建议调试用；两者关系：静态断点是编译/调用期配置，`interrupt()` 是动态正 API。
- **必须配 checkpointer**，否则 `interrupt()` 无意义。

**教师闸门标准形态（probe_c1 全部验证）**：
```python
def teacher_gate(state: State):
    decision = interrupt({"stage": "event_division", "content": state["event_division"], "ask": "请审批/编辑"})
    # resume 后本节点从头重跑，interrupt() 返回 resume 的值
    return {"teacher_decision": decision}

# 调用方（API 层）：
r = await graph.ainvoke(inputs, config)             # → {'__interrupt__': (Interrupt(value=...),)}
await graph.aupdate_state(config, {"event_division": "教师编辑版"})   # 注入编辑（产生新 checkpoint）
r2 = await graph.ainvoke(Command(resume={"decision": "approve"}), config)  # 恢复并继续
```
- `aupdate_state` 返回新 config dict（`{"configurable": {thread_id, checkpoint_ns, checkpoint_id}}`），
  它创建**新 checkpoint**（不覆盖原快照），更新走 reducer（有 reducer 的 channel 是累加不是覆盖——注入编辑时只写 last-value 字段）。
- resume 时读到的 state 已含 `update_state` 注入的教师编辑（实测最终结果含「教师编辑版」）。
- 拒绝路径：resume 值即节点内 `interrupt()` 的返回值，条件边按 `teacher_decision` 路由即可。

**进程重启后能否恢复？（关键需求，已验证）**：
- `MemorySaver`（= `InMemorySaver`，同一对象，源码确认）**不能**跨进程：probe_c2 用子进程重建
  graph + 同一 `thread_id` resume，结果是「空线程把 `Command(resume=...)` 当新输入 → 再次 interrupt」。
- `AsyncPostgresSaver` **能**：probe_c3a（进程 A：`setup()` 建表 + 跑到 interrupt）→
  probe_c3b（全新进程、重建 graph、同一 `thread_id`）：`aget_state` 恢复快照（`values`、`next=('gate',)`），
  `ainvoke(Command(resume=...))` 从中断点继续到完成。教师闸门跨请求/重启恢复可行。

**interrupt 的副作用规则（官方「Rules of interrupts」+ probe_c1 验证）**：
1. 节点内**不要**用裸 try/except 包 `interrupt()`（会吞掉 `GraphInterrupt`）；
2. resume 后**节点从头重跑**：`interrupt()` 之前的副作用必须幂等（我们的做法：
   LLM 产物先落库再 interrupt，重跑时节点应先查「本 task 是否已有产物」——见 §5 建议）；
3. 一个节点多次 `interrupt()` 按**索引顺序**匹配 resume 值，禁止条件跳过 / while 循环包 interrupt；
4. 验证型重提问：每节点最多一次 `interrupt()`，无效答案走条件边回环（官方明确警告
   `while True + interrupt` 会指数级重放）。

### 3.4 Checkpointer 持久化

**包与类（已验证）**：
- `langgraph-checkpoint`（已随装）提供 `BaseCheckpointSaver` + `InMemorySaver`。
- PG 需另装 **`langgraph-checkpoint-postgres`**（venv 实装 3.1.2，会带上 psycopg 3.3.6）；
  另需 **`psycopg[binary]`**（`uv pip install psycopg` 默认不带 libpq，裸装会
  `ImportError: no pq wrapper available`——实测踩到，必须 binary）。
- `AsyncPostgresSaver`（`langgraph.checkpoint.postgres.aio`）：
  - `from_conn_string(conn_string)` 是 **async context manager**，连接用 **psycopg**（非 asyncpg）：
    连接串写 `postgresql://user:pass@localhost:5432/db`（**不要** `postgresql+asyncpg://`，
    SQLAlchemy 风格的 `+asyncpg` psycopg 不认识）。
  - 也可传 `psycopg_pool.AsyncConnectionPool` 构造（`__init__(conn, pipe=None, serde=None)`）。
  - `setup()` 幂等建表/迁移，首次使用前 MUST 调用；probe 实测在 wenjing 库建了
    `checkpoints` / `checkpoint_writes` / `checkpoint_migrations` / `checkpoint_blobs` 四张表，
    与 Alembic 完全无关（它是 saver 自管迁移）。**生产建议放独立 schema 或独立库**，避免与业务表混排。
  - `thread_id` 语义：一个生成会话一个 thread（我们可用 `script_id` 或专用 session id）；
    恢复、状态查询、历史都靠它。`checkpoint_ns`：父图 `""`，子图 `node:uuid`。
  - `__init__` 里 `self.loop = asyncio.get_running_loop()`——**实例与创建时的事件循环绑定**；
    FastAPI 单进程单循环没问题，但不要在模块导入期/跨循环复用同一实例（#28 建议在 app lifespan 里创建）。
- checkpoint 存什么：每个 super-step 一行全量 channel 值（msgpack 序列化）+ 每节点写一行
  `checkpoint_writes`（`(task_id, channel, value)`）；中断信息也走 writes。
  `state history` 全量可查（`aget_state_history`），即「时间旅行」。

**checkpointer 真源 vs 自己存 JSONB（对 #28 `generation_state` 的取舍建议）**：

| | checkpointer 真源 | 自己存 JSONB |
|---|---|---|
| 状态语义 | 全量图状态逐步快照，天然支持 resume/interrupt/时间旅行 | 只有业务快照，resume 需自己重建 |
| 存储 | msgpack blob（黑盒，DBA 不可读），4 张表 | 可读、可索引、前端直查 |
| 与 Alembic | 无关（自建自迁移） | 纳入统一迁移 |
| 放大风险 | 每步全量写，长流程膨胀（官方给了 DeltaChannel beta 缓解） | 每节点一行，量小可控 |

**建议混合**（两条都要，职责分开）：
- `AsyncPostgresSaver` 负责**可恢复性**（interrupt/resume/断点续跑），是运行时机制，不对外暴露；
- 自己的 `generation_state` JSONB 负责**业务观测**（每节点 status/输出摘要/prompt_version/token 用量），
  由 `astream(updates)` 事件驱动写入（§3.7），对外 API/前端只读这个。
- 不要试图用 JSONB 反推图状态来手工 resume——恢复只走 checkpointer。

### 3.5 自定义 LLM 接入（BaseChatModel 适配 ChatLLMService）

**langchain-core 1.5.5 的 `BaseChatModel` 接口（读源码确认，非记忆）**：
```python
@abstractmethod
def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None,
              run_manager: CallbackManagerForLLMRun | None = None, **kwargs) -> ChatResult: ...

async def _agenerate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                     run_manager: AsyncCallbackManagerForLLMRun | None = None, **kwargs) -> ChatResult:
    # 基类默认实现 = run_in_executor 包 _generate；async 场景应直接覆写 _agenerate
```
- 子类还须实现属性 `_llm_type`；类是 Pydantic 模型，字段要声明类型（`service: Any`）。
- 返回 `ChatResult(generations=[ChatGeneration(message=AIMessage(content=..., usage_metadata={...}, response_metadata={...}))])`；
  token 用量放 `usage_metadata={"input_tokens", "output_tokens", "total_tokens"}`（LangChain 标准位置，
  之后 LangSmith/计量都读这里）。

**已验证（probe_d）**：子类只实现 `_agenerate`（sync `_generate` raise NotImplementedError）+
`ainvoke` 在图节点内调用成功，`usage_metadata` 原样带回。适配我们服务的骨架：

```python
class WenjingChatModel(BaseChatModel):
    service: Any          # ChatLLMService（经 ModelServiceFactory 构造）
    purpose: str = "agent"
    session_id: str = ""

    @property
    def _llm_type(self) -> str:
        return "wenjing-chat"

    def _generate(self, messages, stop=None, run_manager=None, **kw) -> ChatResult:
        raise NotImplementedError("后端全 async，只走 _agenerate")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kw) -> ChatResult:
        dict_msgs = [{"role": m.type, "content": m.content} for m in messages]
        content, usage = await self.service.chat_with_usage(dict_msgs, session_id=self.session_id, purpose=self.purpose)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content=content,
            usage_metadata={"input_tokens": usage.prompt_tokens, "output_tokens": usage.completion_tokens,
                            "total_tokens": usage.total_tokens} if usage else None,
        ))])
```

**两条路线取舍**：
- **包一层 BaseChatModel（推荐）**：保留现有计量/超时/信号量/错误包装（`codes.LLM_CALL_FAILED`）与
  purpose 分类，LangGraph 只看到标准 ChatModel；`_generate` 可留 NotImplementedError（我们全 async）。
- `init_chat_model` / `langchain-openai`：能省适配代码、自带 `with_structured_output`、
  `stream_mode="messages"` token 流，但把计量/purpose/限流移出我们控制，需在回调层重建。
  建议 #28 先走包装路线；若后面要 token 流式或 tool-calling 再评估换 `ChatOpenAI`
  （`init_chat_model` 在 langchain 1.3.15 存在，`from langchain.chat_models import init_chat_model`，已验证可导入；
  langchain-openai 未装，真实调用未验证）。

**with_structured_output**：
- 自定义模型上默认抛 `NotImplementedError: with_structured_output is not implemented for this model`（probe_d 实测）。
- 需要结构化输出的节点（事件划分、人物设定等）两条路：(a) 在 WenjingChatModel 上自实现
  `with_structured_output`（tool-calling 或 JSON 模式）；(b) 节点内手动「提示词 + JSON 解析 + Pydantic 校验」。
  我们的 schema 是 `extra=forbid` Pydantic，两种路都能用；**(b) 先行更稳**（不依赖 provider 的 tool-call 质量）。
- `init_chat_model("openai:...").with_structured_output(PydanticSchema)` 的行为（含 extra=forbid
  → JSON schema `additionalProperties: false` 转换）**未运行验证**（本机无 langchain-openai、无 key），开发时冒烟确认。

### 3.6 重试与错误处理

**已验证（probe_f）**：
- `add_node(..., retry_policy=RetryPolicy(...))`——`RetryPolicy` 在 `langgraph.types`
  （`langgraph.prebuilt` 只是兼容 re-export；`retry=` 是 deprecated 旧参数名，会警告并转 `retry_policy`）。
- 字段：`max_attempts=3`、`initial_interval=0.5`、`backoff_factor=2.0`、`jitter=True`、`retry_on`。
- **大坑：`default_retry_on` 只重试 `ConnectionError`、httpx 5xx、requests 错误等网络类异常；
  `RuntimeError`（以及我们 `errx` 包装的任意异常）默认不重试**（实测 RuntimeError 单次即失败）。
  LLM 节点要用 `retry_on=(ConnectionError, TimeoutError, AppLLMError)` 或显式 `retry_on=Exception`
  + 排除不可重试类型（用 callable 谓词，别把 `ValueError` 这类参数错误也重试）。
- 重试耗尽后异常**直接向上抛到 `ainvoke/astream` 调用方**（附 `During task with name 'xxx'` 上下文），
  节点内不捕获就由 API 层统一捕（可配 `compile()`/`astream` 的 fault-tolerance 从上个 checkpoint 恢复——
  `durability="sync"` 模式下 pending writes 保证同 super-step 已成功节点不重跑，见官方 Fault tolerance 页）。
- 节点内自捕获更细（LLM 调用 try/except 转成「节点失败状态」写 state，由条件边决定终止），
  与全局 catch-up 兼容。注意：**节点内 try/except 不要覆盖到 `interrupt()` 调用**（§3.3）。

### 3.7 进度观测：ainvoke vs astream vs astream_events

**已验证（probe_e）**：
- `astream(..., stream_mode="updates", version="v2")`：每个节点/超步产出
  `{"type": "updates", "ns": (), "data": {"<node>": <update_dict>}}`——正是「每节点状态落库」需要的事件流。
- 不传 `version`（v1 默认）：单 mode 直接给 `{"<node>": update}`，多 mode 给 `(mode, data)` 元组。
  v2 统一格式 + 类型可收窄（`langgraph.types.StreamPart` TypedDict 联合），**建议直接用 v2**
  （1.2.11 ≥ 1.1，支持；且 `interrupts` 也挂在 StreamPart/values part 上，不用翻 `__interrupt__` 键）。
- `stream_mode="values"` 给全量状态（含 reducers 合并后的结果），调试有用，生产可不开（省开销）。
- `subgraphs=True` 时 `ns` 字段带命名空间（`("node:task_id",)`）；我们没有独立 subgraph（人物并行用 Send 不算 subgraph），暂不需要。
- `stream_mode="messages"`：LLM token 级流（要求模型是标准 ChatModel；自定义模型也可，
  但我们 v1 阶段不需要逐 token 推前端，暂不用）。
- `stream_mode="custom"` + `get_stream_writer()`：节点内发细粒度进度（如「第 2/5 轮检索」）。
  Python 3.11 下 async 节点内可直接用；值得给长节点（素材收集多轮）用。
- `ainvoke`：一次性拿终态，无过程事件——**不适合**做进度落库，仅适合内部测试。
- `stream_events(version="v3")`：typed projections 新 API（`.interrupted/.interrupts/.output/.messages`），
  已验证能跑（probe_g），但**标 experimental**（`LangChainBetaWarning`），不建议现在依赖。

**结论**：主循环用 `astream(stream_mode="updates", version="v2")`，每个 updates 事件里
`data` 的 key 就是节点名 → 写 `generation_state`（status=completed/failed + 摘要）；
`generation_state` 的 status 枚举与契约 stage 对齐。收到中断事件（`values` part 的 `interrupts` 非空）
时把节点标 `awaiting_teacher`。

### 3.8 异步与单 worker（FastAPI 内嵌）

- 节点支持 `async def`；async 图必须用 `ainvoke/astream`（sync API 对 async 节点会另起线程/报错）。
  probe_b/c 全部在 `asyncio.run` 单循环内跑通。
- 在 FastAPI 里用 `asyncio.create_task(graph.ainvoke(...))` 后台跑整个剧本生成（我们的形态）没问题：
  probe 环境即单循环，`InMemorySaver`/`AsyncPostgresSaver` 均验证 async 路径。
- `AsyncPostgresSaver` **绑定创建时的 event loop**（源码 `__init__` 里 `get_running_loop()`）：
  在 app lifespan（同一循环）内创建并复用，不要每请求新建（psycopg pool 也贵），
  更不要跨循环复用。
- 单 worker 约束不变（AGENTS.md：WS outbox 在进程内存）。LangGraph 不改变这一点：
  同一进程内多个并发 `graph.ainvoke`（多个剧本会话）= 各自独立 thread_id + 各自 checkpoint，
  MemorySaver 是进程内单例（并发安全，源码 asyncio.Lock 保护 PG saver），
  PG saver 则天然跨进程安全。
- **坑**：同一进程反复 `compile()` 新图没问题，但 checkpointer 单例要共享（不同 thread_id 互不干扰），
  否则内存 saver 的图在 gate 等待期间重启会丢（§3.3）——生产必须 PG saver。
- Python ≥3.11（我们 3.11.16）：contextvars 随 task 传播，官方「Python <3.11 需手动传 config」的
  限制不适用于我们；`get_stream_writer()` 在 async 节点内可用。

---

## 4. 版本陷阱清单（0.2/0.3 教程 vs 1.x 实际 API）

| # | 旧教程写法 | 1.x（已验证）实际 |
|---|---|---|
| 1 | `from langgraph.checkpoint.memory import MemorySaver` + 当成跨进程持久化 | 类仍存在且 `MemorySaver is InMemorySaver`，但**进程内存**；跨进程必须 AsyncPostgresSaver（probe_c2/c3） |
| 2 | `interrupt_before=["gate"]` 做 HITL | 仍支持但官方「不推荐做 HITL」；用 `interrupt()` + `Command(resume=...)`（probe_c1） |
| 3 | `invoke(None, config)` 静态断点续跑 | 静态断点路径还在；`interrupt()` 场景必须 `Command(resume=...)`，`None` 无效（resume 走 Command） |
| 4 | `add_node("n", fn, retry=RetryPolicy())` | `retry` 已 deprecated → `retry_policy=`（源码 DeprecationWarning 文案） |
| 5 | `RetryPolicy` 从 `langgraph.prebuilt` 导入 | 在 `langgraph.types`（prebuilt 仅兼容 re-export） |
| 6 | **想当然认为所有异常都会重试** | `default_retry_on` 只覆盖网络类异常；RuntimeError 等单次即抛（probe_f 实测） |
| 7 | `stream` 多 mode 返回 `(mode, data)` 元组 | 默认仍如此（v1 格式），但**应该用 `version="v2"`**：统一 `{"type","ns","data"}` StreamPart（probe_e）；`stream_events(..., version="v3")` 又是另一套（experimental） |
| 8 | `invoke` 结果里找 `__interrupt__`（v1） | 仍可用；v2 `invoke` 返回 `GraphOutput`（`.value/.interrupts`），dict 访问已 deprecated |
| 9 | 0.x Pydantic 状态 + `MemorySaver` 简单可靠 | Pydantic State 坏输入会**污染 thread checkpoint**（aget_state 后续都炸，probe_g 实测） |
| 10 | 教程常写 `StateGraph.from_entries`/`add_sequence` 等 | 1.x 主 API 就是 `add_node/add_edge/add_conditional_edges`（源码 state.py 确认） |
| 11 | `AsyncPostgresSaver` 用 asyncpg | 用 **psycopg 3**（+ `psycopg[binary]`）；连接串禁 `+asyncpg` 后缀（实测 ImportError + 源码确认） |
| 12 | 「checkpointer 建表归 Alembic 管」 | `setup()` 自建自迁移 4 张表，与 Alembic 无关；幂等可重复调（probe_c3 实测） |
| 13 | 旧教程 `checkpointer=MemorySaver()` 后随便 `get_state` | 必须带 `thread_id` config；`aupdate_state` 返回 config dict（不是 StateSnapshot） |
| 14 | langchain 0.x 的 `ChatOpenAI(model=..., api_key=...)` 例子 | langchain-core 1.5.5 的 BaseChatModel 接口如 §3.5（`_generate/_agenerate(messages, stop, run_manager, **kwargs)`；读源码确认） |

---

## 5. 对 issue #28 骨架落地的建议

**图形态（对 #28 节点清单的具体落地）**：
```python
class ScriptState(TypedDict):
    source_text: str
    material: dict            # 素材收集输出
    verified: dict            # 考证输出 + doubter_notes
    doubter_notes: Annotated[list[str], operator.add]      # 全局 doubter 打回痕迹
    doubter_round: int                                     # 打回上限计数（last-value）
    characters: list[str]
    profiles: Annotated[list[dict], operator.add]          # Send fan-out join
    event_division: dict
    script_package: dict
    gate_stage: str            # 当前等待教师的阶段（awaiting_teacher 时非空）

# 主链：material → verify → doubter → (打回: material 或 event_division) → events →
#       fan_out(Send) → merge → write → check → review → END
# 闸门：每个主要产出节点（event_division / profiles_merge / script_package）
#       后面挂 teacher_gate_<stage> 节点，节点内 interrupt({"stage": ..., "content": ...})，
#       教师拒绝 → Command 语义上由 gate 节点返回值驱动条件边（goto 回上游节点 / END）。
```

三条最重要的建议：

1. **checkpointer 选型：`AsyncPostgresSaver` 一步到位，别先用 MemorySaver 再迁移。**
   教师闸门「暂停数小时/数天 + 进程重启」是硬需求，MemorySaver 语义上不可跨进程（已实测），
   API 层每次请求是新的 graph 调用。落地：依赖加 `langgraph-checkpoint-postgres` + `psycopg[binary]`；
   app lifespan 里创建 saver 实例（async 上下文内、单例），`setup()` 放启动时幂等执行；
   `thread_id` 用新分配的生成会话 ID。注意它自带 4 张表不归 Alembic，建议独立 schema
   （连接串可带 `options=-csearch_path=langgraph`）或接受 public 下 `checkpoint*` 前缀命名。

2. **状态 schema 用 TypedDict + Annotated reducers，`generation_state` 独立于图状态。**
   图状态（TypedDict）只放节点间传递的数据；对外可查的进度（每节点 status/摘要/prompt_version/
   token 用量）由 `astream(stream_mode="updates", version="v2")` 事件单独写 `generation_state`
   JSONB。理由：Pydantic State 的坏输入污染 checkpoint 坑真实存在；且进度字段（给前端契约）不应
   绑死在图 state 上。打回上限计数放 state（`doubter_round`）+ 条件边判断，不要用 recursion_limit
   兜底（25 默认值是调试护栏，不是业务上限）。

3. **LLM 适配层用 BaseChatModel 包装现有 ChatLLMService，结构化输出先走「节点内 JSON+Pydantic 校验」。**
   保留计量（`chat_with_usage` → `usage_metadata`）、purpose 分类、限流、错误码包装；
   LLM 节点的 RetryPolicy 显式 `retry_on`（默认策略不重试我们的包装异常）。
   教师闸门节点遵循 interrupt 四规则：每节点最多一次 interrupt、无裸 try/except 包裹、
   interrupt 前的 LLM 调用产物落库要幂等（重跑会先查已有产物）。

---

## 6. 未验证 / 待开发时确认的点

| 项 | 状态 | 说明 |
|---|---|---|
| 并行分支同时 interrupt 的 resume 映射 | 官方文档模式，**未实跑** | `{interrupt_id: value}` 映射；#32 若做人物级人工干预需先验证 |
| `Command(goto=[Send(...)])` 节点内动态 fan-out | 源码确认支持，**未实跑** | 备用形态（Send 从节点返回而不是条件边） |
| `init_chat_model` / langchain-openai 真实调用 + `with_structured_output(extra=forbid)` | **未运行验证** | 无 key；#28 的 key-gated 冒烟脚本里确认 |
| `stream_mode="messages"` 对自定义 ChatModel 的 token 流 | 未验证 | 自定义模型实现 `_stream` 前默认 fallback 整块消息，需确认 |
| DeltaChannel（1.2 beta）省 checkpoint 体积 | 未验证 | 我们的 state 大头是 LLM 结构化输出（每步全量写会有一定体积），短期可接受，长期观察 |
| `durability` 参数（exit/async/sync） | 未实跑 | 按官方文档：生产建议 `durability="sync"`（每步同步落盘）——LLM 节点慢，checkpoint 开销占比可忽略 |
| langgraph-prebuilt `create_agent` 等 | 不采用 | 我们的 workflow 是确定性流水线 + 闸门，不是自由 agent 循环 |
| PG checkpointer 表放独立 schema | 未实跑 | `from_conn_string` 连接串直接传 search_path options 待验证 |
| 本 probe 在 wenjing 库留下的 `checkpoint*` 表 | 说明 | probe 残留；`make db-reset` 即清除。正式实现前无影响 |

## 附：probe 清单（/tmp/opencode/langgraph_probe/，已全部实跑通过）

| 脚本 | 验证内容 | 结果 |
|---|---|---|
| probe_a.py | Annotated reducer + 条件边 + doubter 打回循环 + 上限失败边 | 3 轮打回后通过，notes 累加正确 |
| probe_b.py | Send fan-out 4 人物并行 + reducer join | 4 任务 t≈0.005s 同时启动（并行确认） |
| probe_c1.py | interrupt + Command(resume) 两段式 + aupdate_state 教师编辑注入 + 拒绝路径 | approve/reject 均正确，编辑值被 resume 后节点读到 |
| probe_c2.py | MemorySaver 跨进程（子进程重建 graph 同 thread_id resume） | 失败：新进程视作新输入再次 interrupt → 证明必须持久 checkpointer |
| probe_c3a/b.py | AsyncPostgresSaver setup() + 跨进程恢复（两个独立进程） | aget_state 恢复快照 next=('gate',)，resume 完成整图 |
| probe_d.py | BaseChatModel 子类（_generate/_agenerate）+ usage_metadata 注入节点；with_structured_output | 运行成功；structured_output 抛 NotImplementedError |
| probe_e.py | stream_mode=["updates","values"] v1 vs v2 形态、astream | v2 统一 StreamPart 确认 |
| probe_f.py | RetryPolicy 显式 retry_on 重试 3 次成功；default_retry_on 不重试 RuntimeError；recursion_limit→GraphRecursionError | 全部确认 |
| probe_g.py | Pydantic State + checkpointer serde、坏输入污染 thread、stream_events v3 | 校验生效、污染复现、v3 可用（experimental 警告） |
