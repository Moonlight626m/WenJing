# 文境 (Wenjing) — 模块设计：游戏引擎

> 游戏引擎是后端核心编排层，负责状态机管理、Agent 调度、事件循环、回溯执行。
>
> 技术决议：状态机基于 **LangGraph**（D6）；引擎运行在 **单进程 asyncio 事件循环**（D13）。

---

## 一、引擎定位

```
                    ┌──────────────────────┐
                    │     WebSocket        │
                    │     (消息收发)        │
                    └────────┬─────────────┘
                             │
                    ┌────────▼─────────────┐
                    │   Game Engine        │
                    │                      │
                    │  ┌────────────────┐  │
                    │  │  Event Loop    │  │ ← 主循环
                    │  └───────┬────────┘  │
                    │          │           │
                    │  ┌───────┴────────┐  │
                    │  │  State Machine │  │ ← 阶段状态
                    │  └───────┬────────┘  │
                    │          │           │
                    │  ┌───────┴────────┐  │
                    │  │ Agent Scheduler│  │ ← Agent 编排
                    │  └───────┬────────┘  │
                    │          │           │
                    │  ┌───────┴────────┐  │
                    │  │ Event Store    │  │ ← 事件溯源
                    │  └────────────────┘  │
                    └──────────────────────┘
```

**核心职责**（只有这四件事）：
1. **状态机** — 管理 Stage1→Stage2→Stage3 的状态转换
2. **事件循环** — 驱动游戏逐轮推进
3. **Agent 调度** — 决定何时调用哪个 Agent，串行/并行执行
4. **事件溯源** — 记录所有事件，支持回溯

引擎不做的事（由其他模块负责）：
- 不生产剧情内容（编剧 Agent）
- 不审核内容（验证 Agent）
- 不扮演角色（角色 Agent）
- 不渲染 UI（前端）

---

## 二、状态机

### 2.1 状态定义

```python
from enum import Enum

class GameStage(Enum):
    INIT = "init"              # 初始状态，等待剧本创建
    STAGE1_CREATING = "stage1_creating"   # 剧本创建中
    STAGE1_COMPLETE = "stage1_complete"   # 剧本创建完成，等待玩家选择角色
    STAGE2_REENACTING = "stage2_reenacting"  # 剧情还原中
    STAGE2_COMPLETE = "stage2_complete"      # 还原完成，等待切 Stage3
    STAGE3_EXTENDING = "stage3_extending"    # 剧情续写中
    ENDED = "ended"              # 游戏结束

class InteractionPhase(Enum):
    """
    Stage2/3 内部的交互阶段
    每个 Stage 内会循环经历这些 phase
    """
    NARRATIVE = "narrative"              # 编剧推送场景描述
    DIRECTION = "direction"              # 方向确认（D5 两段式第一步：确认当前矛盾/关键处境）
    AGENT_PROPOSAL = "agent_proposal"    # 角色 Agent 提议
    VERIFICATION = "verification"        # 验证审核
    INTERACTION_DESIGN = "interaction_design"  # 交互设计
    PLAYER_TURN = "player_turn"          # 玩家操作
    AGENT_REACTION = "agent_reaction"    # 角色 Agent 对玩家操作的反应
    STAGE_CHECK = "stage_check"          # 检测是否结束当前 Stage
```

### 2.2 状态转换图

```
[INIT]
  │  用户导入课文
  ▼
[STAGE1_CREATING]
  │  编剧 Agent 完成剧本创建 + 验证通过
  ▼
[STAGE1_COMPLETE]
  │  玩家选择角色
  ▼
[STAGE2_REENACTING]
  │  按课文还原，直到到达课文结局
  ▼
[STAGE2_COMPLETE]
  │  过场提示，玩家确认进入续写（D14：引擎自动判断结局达成 → 推送过场 → 玩家点击确认）
  ▼
[STAGE3_EXTENDING]
  │  自由续写，直到玩家退出
  ▼
[ENDED]
```

```python
class GameStateMachine:
    """状态机：负责状态转换和状态校验"""
    
    _transitions = {
        GameStage.INIT: [GameStage.STAGE1_CREATING],
        GameStage.STAGE1_CREATING: [GameStage.STAGE1_COMPLETE],
        GameStage.STAGE1_COMPLETE: [GameStage.STAGE2_REENACTING],
        GameStage.STAGE2_REENACTING: [GameStage.STAGE2_COMPLETE],
        GameStage.STAGE2_COMPLETE: [GameStage.STAGE3_EXTENDING],
        GameStage.STAGE3_EXTENDING: [GameStage.ENDED],
        GameStage.ENDED: [],
    }
    
    def __init__(self):
        self.current: GameStage = GameStage.INIT
        self.phase: InteractionPhase | None = None
    
    def transition_to(self, target: GameStage) -> bool:
        """尝试转换到目标状态。非法转换返回 False。"""
        if target in self._transitions[self.current]:
            self.current = target
            return True
        return False
```

---

## 三、事件循环

引擎的核心是一个 `async while` 循环，每次循环推进一个 phase。

### 3.1 主循环

```python
class GameEngine:
    """
    游戏引擎主类
    
    设计原则：
    - 单线程 asyncio 事件循环
    - 每个 phase 是一个 async step
    - 不同 phase 之间通过事件总线（EventBus）传递消息
    - Agent 通过 engine 提供的接口被调度，不直接互相调用
    """
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.state_machine = GameStateMachine()
        self.event_store = EventStore()         # 事件溯源
        self.event_bus = EventBus()              # Agent 间通信中转
        self.scheduler = AgentScheduler()        # Agent 编排
        
        # Agent 实例（由 scheduler 管理）
        self.screenwriter: ScreenwriterAgent | None = None
        self.verifier: VerifierAgent | None = None
        self.characters: CharacterAgentManager | None = None
        
        # 配置
        self.config = EngineConfig(
            max_proposal_retries=2,    # 角色提议被驳回后最多重试 2 次
            checkpoint_interval=20,    # 每 20 个事件打快照
            max_rollback_steps=100,    # 最大回退步数
        )
    
    async def run(self):
        """引擎入口，启动游戏流程"""
        # Stage 1: 剧本创建
        await self._run_stage1()
        
        # Stage 2: 剧情还原
        await self._run_stage2()
        
        # Stage 3: 剧情续写
        await self._run_stage3()
        
        await self._end_game()
    
    async def _run_stage1(self):
        """Stage 1 是线性的，不需要循环"""
        self.event_bus.emit("stage_start", {"stage": "stage1"})
        
        # 1. 素材收集
        material = await self.screenwriter.collect_material(textbook)
        
        # 2. 完整剧本生成
        script = await self.screenwriter.create_script(material)
        
        # 3. 验证完整剧本
        result = await self.verifier.verify_script(script)
        if result.verdict == "reject":
            script = await self._retry_with_feedback(
                self.screenwriter, script, result
            )
        
        # 4. 初始化角色 Agent
        self.characters = CharacterAgentManager()
        self.characters.create_agents(script.character_settings)
        
        self.state_machine.transition_to(GameStage.STAGE1_COMPLETE)
        self.event_bus.emit("stage_complete", {"stage": "stage1"})
```

### 3.2 Stage2/3 主循环

Stage2 和 Stage3 共享同一个循环结构，只有内部策略不同：

```python
    async def _run_stage2(self):
        """剧情还原阶段的主循环"""
        self.state_machine.transition_to(GameStage.STAGE2_REENACTING)
        
        while True:
            phase_result = await self._execute_phase_cycle(stage="stage2")
            
            # 检查是否到达课文结局
            if phase_result.stage_complete:
                break
            
            # 检查玩家是否请求回退
            if phase_result.rollback_requested:
                await self._execute_rollback(phase_result.rollback_steps)
        
        self.state_machine.transition_to(GameStage.STAGE2_COMPLETE)
    
    async def _run_stage3(self):
        """剧情续写阶段的主循环"""
        self.state_machine.transition_to(GameStage.STAGE3_EXTENDING)
        
        while True:
            phase_result = await self._execute_phase_cycle(stage="stage3")
            
            # Stage3 持续运行直到玩家退出
            if phase_result.player_exit:
                break
            if phase_result.rollback_requested:
                await self._execute_rollback(phase_result.rollback_steps)
```

### 3.3 单次 Phase Cycle

这是引擎最核心的方法，一次 `_execute_phase_cycle` 对应一次完整的"方向确认→提议→验证→交互→反应"。

> 该 cycle 含 **8 个 phase**，与 §2.1 `InteractionPhase` 枚举一一对应（NARRATIVE → DIRECTION → AGENT_PROPOSAL → VERIFICATION → INTERACTION_DESIGN → PLAYER_TURN → AGENT_REACTION → STAGE_CHECK）。
> 其中 DIRECTION 是 D5"方向确认 + 行为选项两段式"的第一步，其余七个 phase 构成常规推进。

```python
    async def _execute_phase_cycle(self, stage: str) -> PhaseCycleResult:
        """
        执行一轮完整的 phase 循环。
        
        流程（固定 8 步）：
        Step 1: 编剧推送剧情摘要
        Step 2: 编剧/交互设计确认「当前矛盾/关键处境」（方向确认，D5 两段式第一步）
        Step 3: 角色 Agent 据此提出具体行为提议（并行）
        Step 4: 验证 Agent 审核提议（并行）
        Step 5: 交互设计器筛选提议、决定模式并生成交互点
        Step 6: 等待玩家操作（或超时检测）
        Step 7: 角色 Agent 对玩家操作做出反应（并行）
        Step 8: Stage 结束检测
        """
        
        # --- Step 1: 编剧推送剧情摘要 ---
        plot_update = await self.screenwriter.advance_plot(stage)
        self.event_bus.emit("narrative_push", plot_update)
        self._record_event("plot_advancement", plot_update)
        
        # 广播剧情摘要给所有角色 Agent
        self.characters.broadcast_plot_context(plot_update.summary)
        
        # 发送 narrative 消息到前端
        await self._send_to_frontend({
            "type": "narrative",
            "content": {"text": plot_update.scene_description},
        })
        
        # --- Step 2: 方向确认（D5 两段式第一步）---
        direction = await self.screenwriter.confirm_direction(stage, plot_update)
        self.event_bus.emit("direction_confirmed", direction)
        self._record_event("direction", direction)
        
        # 广播当前矛盾/关键处境给所有角色 Agent
        self.characters.broadcast_direction(direction)
        
        # --- Step 3: 角色 Agent 提出行动提议（并行）---
        proposals = await self._collect_character_proposals(stage)
        
        # --- Step 4: 验证 Agent 审核提议（并行）---
        valid_proposals = await self._verify_proposals(proposals, stage)
        
        # --- Step 5: 交互设计器筛选提议、决定模式并生成交互点 ---
        interaction = await self.screenwriter.design_interaction(
            stage=stage,
            proposals=valid_proposals,
            cycle_context=self._build_cycle_context(),
        )
        
        # 发送 interaction 消息到前端
        await self._send_to_frontend({
            "type": "interaction",
            "content": interaction.to_dict(),
        })
        
        # --- Step 6: 等待玩家操作 ---
        player_action = await self._wait_for_player_action()
        
        if player_action.type == "rollback":
            return PhaseCycleResult(rollback_requested=True, rollback_steps=player_action.steps)
        
        # 记录玩家操作
        self._record_event("player_action", player_action)
        
        # --- Step 7: 角色 Agent 对玩家操作做出反应 ---
        reactions = await self._collect_character_reactions(player_action, stage)
        
        # 发送角色反应到前端
        for reaction in reactions:
            await self._send_to_frontend({
                "type": "character_speech",
                "content": reaction,
            })
        
        # --- Step 8: Stage 结束检测 ---
        stage_complete = await self._check_stage_completion(stage)
        
        # 每轮结束打 checkpoint（用于回溯）
        self._maybe_checkpoint()
        
        return PhaseCycleResult(stage_complete=stage_complete)
```

### 3.4 并行 Agent 调度

Step 3（角色提议）和 Step 4（验证审核）中，多个角色 Agent 的调用是并行的。

> **提议重试（D4 / R2.3）**：被驳回的提议带着 Verifier 的 `suggestion` 退回提出者，角色 Agent 依据反馈调整后最多重提 2 次（`EngineConfig.max_proposal_retries`）。
> 若某条提议 2 次重试后仍被驳回，则放弃该提议；若全部提议均被放弃，`InteractionDesigner` 检测到僵局，切到模式 B 放权给玩家（见 `design_01` §3.4 / §2.5 Rule 1）。

```python
    async def _collect_character_proposals(self, stage: str) -> list[Proposal]:
        """
        并行收集所有角色 Agent 的行动提议。
        使用 asyncio.gather 实现并发。
        """
        tasks = []
        for name in self.characters.active_names():
            task = self.characters.propose_action(name, stage)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        proposals = []
        for name, result in zip(self.characters.active_names(), results):
            if isinstance(result, Exception):
                logger.error(f"角色 {name} 提议失败: {result}")
                continue
            proposals.append(result)
        
        return proposals
    
    async def _verify_proposals(
        self, proposals: list[Proposal], stage: str
    ) -> list[Proposal]:
        """
        并行验证所有提议；被驳回的提议退回提出者并允许重试（最多 2 次）。
        重试时携带 Verifier 的 suggestion 作为反馈。
        """
        valid: list[Proposal] = []
        pending = proposals
        attempts_left = self.config.max_proposal_retries  # 默认 2

        while pending and attempts_left >= 0:
            tasks = [self.verifier.verify_proposal(p, stage) for p in pending]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            still_pending = []
            for prop, result in zip(pending, results):
                if isinstance(result, Exception):
                    logger.error(f"验证 {prop.proposed_by}:{prop.action_id} 失败: {result}")
                    continue  # 降级视为条件通过，保留提议
                if result.verdict == "reject" and attempts_left > 0:
                    # 退回提出者，携带修改建议重提
                    revised = await self.characters.retry_proposal(
                        prop, result.rejections
                    )
                    if revised is None:
                        logger.info(f"角色 {prop.proposed_by} 放弃提议")
                        continue
                    still_pending.append(revised)
                    continue
                if result.verdict in ("pass", "conditional_pass") or attempts_left == 0:
                    # 通过 / 条件通过直接进入候选池；重试用尽则按降级收录
                    valid.append(prop)
                    continue

            pending = still_pending
            attempts_left -= 1

        return valid
```

---

## 四、事件存储与回溯

### 4.1 事件存储

```python
class GameEvent:
    """单条游戏事件"""
    event_id: int            # 自增 ID
    timestamp: float
    event_type: str          # stage_transition | plot_advancement | proposal | verification | player_action | character_speech | system
    payload: dict            # 具体数据
    parent_id: int | None    # 父事件 ID（用于追溯）

class EventStore:
    """
    事件溯源存储。
    所有游戏历史存储在内存中（list[GameEvent]），
    定期序列化到数据库持久化。
    """
    
    def __init__(self):
        self.events: list[GameEvent] = []
        self._counter = 0
    
    def append(self, event_type: str, payload: dict, parent_id: int | None = None) -> GameEvent:
        self._counter += 1
        event = GameEvent(
            event_id=self._counter,
            timestamp=time.time(),
            event_type=event_type,
            payload=payload,
            parent_id=parent_id,
        )
        self.events.append(event)
        return event
    
    def rollback_to(self, target_event_id: int) -> list[GameEvent]:
        """
        回退到指定事件。
        返回被截断的事件列表（不包含 target_event_id 本身）。
        """
        idx = next(
            (i for i, e in enumerate(self.events) if e.event_id == target_event_id),
            -1
        )
        if idx == -1:
            raise ValueError(f"事件 {target_event_id} 不存在")
        
        truncated = self.events[idx + 1:]
        self.events = self.events[:idx + 1]
        return truncated
```

### 4.2 Checkpoint 快照

```python
class GameSnapshot:
    """
    游戏状态快照。
    每 N 个事件保存一次，用于快速回溯（不必从头重放所有事件）。
    """
    event_id: int                    # 对应的事件 ID
    state_machine: GameStage         # 状态机状态
    character_memories: dict         # 所有角色 Agent 的记忆快照
    plot_context: str                # 当前剧情摘要
    event_count: int                 # 到该点为止的事件总数

class CheckpointManager:
    """
    快照管理器。
    - 每 N 个事件生成一个快照
    - 回退时从最近的快照开始重放，不必从 0 开始
    """
    
    def __init__(self, interval: int = 20):
        self.interval = interval
        self._snapshots: list[GameSnapshot] = []
    
    def maybe_snapshot(self, engine: GameEngine) -> None:
        """事件数达到间隔时生成快照"""
        if len(engine.event_store.events) % self.interval != 0:
            return
        snapshot = self._create_snapshot(engine)
        self._snapshots.append(snapshot)
    
    def find_nearest_snapshot(self, target_event_id: int) -> GameSnapshot:
        """找到距目标事件最近的快照（不晚于目标）"""
        for snap in reversed(self._snapshots):
            if snap.event_id <= target_event_id:
                return snap
        raise ValueError("目标事件之前没有快照")
```

### 4.3 回溯执行

```python
    async def _execute_rollback(self, steps: int) -> None:
        """
        执行回溯。
        1. 找到目标事件 ID（当前最新 - steps）
        2. 找到最近的 checkpoint
        3. 从 checkpoint 重放到目标事件
        4. 截断事件列表
        5. 恢复所有 Agent 状态
        """
        current_count = len(self.event_store.events)
        target_id = current_count - steps
        
        if target_id < 1:
            # 不能回退到 0
            return
        
        # 找到最近 checkpoint
        snapshot = self.checkpoint_manager.find_nearest_snapshot(target_id)
        
        # 恢复状态机
        self.state_machine.current = snapshot.state_machine
        
        # 恢复角色记忆
        self.characters.restore_memories(snapshot.character_memories)
        
        # 恢复剧情上下文
        self.characters.broadcast_plot_context(snapshot.plot_context)
        
        # 截断事件
        self.event_store.rollback_to(target_id)
        
        # 通知前端
        await self._send_to_frontend({
            "type": "system",
            "content": {
                "category": "info",
                "text": f"已回退 {steps} 步，当前在第 {target_id} 步",
            },
        })
```

---

## 五、Agent 调度器

```python
class AgentScheduler:
    """
    Agent 编排调度器。
    
    职责：
    1. 管理 Agent 的调用顺序（串行/并行）
    2. 控制并发数（避免 LLM 过载）
    3. 处理超时和失败重试
    """
    
    def __init__(self, max_concurrent: int = 5):
        self.semaphore = asyncio.Semaphore(max_concurrent)
    
    async def run_parallel(self, tasks: list[Callable]) -> list[Any]:
        """并行执行一组 Agent 调用，受信号量限制"""
        async def _wrapped(task):
            async with self.semaphore:
                return await task
        
        return await asyncio.gather(
            *[_wrapped(t) for t in tasks],
            return_exceptions=True
        )
    
    async def run_sequential(self, tasks: list[Callable]) -> list[Any]:
        """串行执行一组 Agent 调用"""
        results = []
        for task in tasks:
            results.append(await task)
        return results
```

---

## 六、Engine 配置

```python
@dataclass
class EngineConfig:
    """引擎配置，集中管理所有可调参数"""
    
    # 提议重试
    max_proposal_retries: int = 2      # 角色提议被驳回后最多重试 2 次
    
    # 回溯
    checkpoint_interval: int = 20       # 每 20 事件打快照
    max_rollback_steps: int = 100       # 最大回退步数
    
    # 并发
    max_concurrent_llm: int = 5         # 最大并行 LLM 调用数
    
    # 超时
    llm_timeout_seconds: int = 30       # 单次 LLM 调用超时
    player_timeout_seconds: int = 300   # 玩家操作超时（5 分钟无操作）
    
    # 事件存储
    max_events_in_memory: int = 5000    # 内存中最大事件数
```

---

## 七、Engine 对外接口

供 WebSocket Handler 调用的接口：

```python
class GameEngine:
    
    # ===== 生命周期 =====
    async def run(self): ...
    
    # ===== 玩家操作注入 =====
    async def handle_player_action(self, action: PlayerAction) -> None:
        """接收前端发来的玩家操作，注入当前 phase cycle"""
        self._pending_player_action = action
    
    async def handle_rollback_request(self, steps: int) -> None:
        """接收前端发来的回退请求"""
        self._pending_player_action = PlayerAction(type="rollback", steps=steps)
    
    # ===== 状态查询 =====
    def get_current_state(self) -> dict:
        """获取当前游戏状态摘要（供前端初始化/重连时使用）"""
        return {
            "stage": self.state_machine.current.value,
            "phase": self.state_machine.phase.value if self.state_machine.phase else None,
            "event_count": len(self.event_store.events),
            "latest_event_id": self.event_store.events[-1].event_id if self.event_store.events else 0,
        }
    
    def __init__(self, session_id: str):
        ...
        # 玩家操作队列（异步等待）
        self._pending_player_action: PlayerAction | None = None
        self._player_action_event = asyncio.Event()
    
    async def _wait_for_player_action(self, timeout: int = 300) -> PlayerAction:
        """等待玩家操作（异步非阻塞）"""
        try:
            await asyncio.wait_for(
                self._player_action_event.wait(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            # 超时 → 返回默认行为
            return PlayerAction(type="timeout", default=True)
        
        self._player_action_event.clear()
        action = self._pending_player_action
        self._pending_player_action = None
        return action
```

---

## 八、与前端 WebSocket 的衔接

```
WebSocket Handler
    │
    ▼
收到 PlayerActionMessage
    │
    ├── type == "player_action"
    │       → engine.handle_player_action(action_data)
    │
    ├── type == "rollback_request"
    │       → engine.handle_rollback_request(steps)
    │
    └── type == "system_command"
            → e.g., pause/resume/exit

Engine 内部通过 _send_to_frontend() 发送消息：
    await websocket.send_json({
        "type": "narrative" | "character_speech" | "interaction" | "system" | "phase_transition",
        "content": {...},
    })
```

---

## 九、与 Agent 架构的衔接点

| 引擎概念 | Agent 架构对应 | 说明 |
|---------|---------------|------|
| `_execute_phase_cycle()` 的 8 steps | Agent 各个 sub-agent 的调用时机 | 引擎编排顺序，Agent 执行逻辑 |
| `_collect_character_proposals()` | CharacterAgentManager.propose_action() | 并行调用所有角色 Agent |
| `_verify_proposals()` | VerifierAgent.verify_proposal() | 并行验证 |
| `confirm_direction()` | ScreenwriterAgent 交互设计 sub-agent | D5 方向确认（两段式第一步） |
| `design_interaction()` | ScreenwriterAgent.InteractionDesigner | 筛选提议、模式判定 + 交互点生成 |
| `_send_to_frontend()` | Message Protocol 定义 | 5 种后端→前端消息类型 |
| `_wait_for_player_action()` | PlayerProxyAgent input_handler | 等待前端消息 |
| `EventStore.rollback_to()` | CharacterMemory 恢复 | 回溯时恢复 Agent 记忆 |

---

## 十、引擎启动流程

```
1. 玩家通过前端创建/加入游戏 Session
    → 后端创建 GameEngine(session_id)
    → 初始化编剧 Agent、验证 Agent
    → 等待玩家导入课文
    ↓
2. 玩家导入课文
    → engine.run()
    → Stage 1: 剧本创建（自动完成）
    → 等待玩家选择角色
    ↓
3. 玩家选择角色
    → Stage 2 启动
    → _run_stage2() 进入 event loop
    ↓
4. 持续运行直到结束
    → 每轮 cycle 中，通过 WebSocket 与前端交互
    → 支持回溯、暂停、继续
```