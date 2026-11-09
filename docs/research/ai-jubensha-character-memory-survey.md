# AI 剧本杀 / 角色扮演产品的角色记忆、世界状态与多角色并发调研

> 调研日期：2026-11-09
> 调研方式：**一手来源直接抓取**（产品官方文档 / 帮助中心 / 官方 README / 官方 API 文档 / 官方 Zendesk API / 官方 llms.txt）。
> Exa MCP 额度已耗尽（`web_search_exa` / `web_fetch_exa` / `agent_run` 均 402），本轮**未使用 Exa**；
> 只对已知 URL 用 `webfetch` 直取，抓不到的明确写「未核验」。
> **结论可能过期、非规格**：这是带日期的调研快照，不构成本项目架构决策；若要采纳，先写 Issue / ADR。
> 姊妹篇：`docs/research/agent-memory-architecture-survey.md`（通用记忆架构与并发基线）、
> `docs/research/jubensha-ai.md`（开源 AI 剧本杀源码级分析）。

## 0. 结论（先看这段）

针对「AI 剧本杀 / 角色扮演产品如何做角色记忆、世界状态、多角色并发」，本轮的判断是：

1. **没有找到一个产品同时公开解决「角色私有可见性 + 世界状态回溯 + 多角色并发」三件事。**
   它们大多只解决「单用户 × 单角色 × 跨会话事实记忆」；一旦进入多角色共享世界，
   官方文档普遍只给「一次一个回合」「共享聊天历史」这类产品级约束，不给并发/版本语义。
   WenJing 现有的「事件流权威 + 每 session 串行 + `plot_entries_for(viewer)` 按视角投影」
   在完整性上仍然领先，不应该为了「上记忆系统」把它换掉。

2. **最值得抄的三类模式**：
   - **上下文预算化**：AI Dungeon 把 context 拆成 Required（Instructions / Plot Essentials /
     Story Summary / Author's Note / 最后动作）与 Dynamic（Story Cards / History / Memory Bank），
     并公开了 70% / 25% / 50% / 25% 的预算规则（[官方说明](https://help.aidungeon.com/faq/what-goes-into-the-context-sent-to-the-ai)）。
     WenJing 可以把 prompt 拼装从「按需塞」升级成「显式预算器」。
   - **热路径只追加、整理放后台**：Convai 在会话结束时批量抽取事实（[官方说明](https://docs.convai.com/api-docs/plugins-and-integrations/convai-unity-sdk/features/long-term-memory/how-long-term-memory-works.md)），
     Memobase 用 buffer + flush（[官方 README](https://github.com/memodb-io/memobase)），Letta 用 dreaming 后台整理（[官方文档](https://docs.letta.com/configuration/memory)），
     LangMem 明确区分 hot path / background（[官方文档](https://langchain-ai.github.io/langmem/concepts/conceptual_guide/)）。
   - **事实 / 事件 / 关系分开建模**：Charisma 用 Word / Sentence / Decision / Counter / True-false 五类结构化 memory + Gates
     （[官方文档](https://docs.charisma.ai/memories-gates)）；Zep/Graphiti 用带 validity window 的事实边 + episode 溯源
     （[官方文档](https://help.getzep.com/v4/facts.md)）；Mem0 的 ADD-only 抽取 + entity linking（[官方文档](https://docs.mem0.ai/core-concepts/how-it-works)）。
     WenJing 可以在事件流之上加一张「角色 × 事实」派生表，而不是只存自由文本。

3. **最该避免的四条**：
   - 把向量库或外部记忆服务当世界状态 / 角色私有记忆的**权威**；
   - 每个角色各存一份「共享世界」，导致回溯时无法只回退一方；
   - 在玩家命令热路径里同步跑 LLM 抽取、建图、summarize；
   - 让摘要 / 反思**反向改写历史事件**。AI Dungeon 自己就承认：编辑历史后不会自动重算摘要，需要手动更新
     （[官方说明](https://help.aidungeon.com/faq/the-memory-system)）——这正是「派生记忆与权威脱节」的典型裂缝。

4. **世界状态的公开答案很弱。** AI Dungeon 明确说它是「协作讲故事」，没有把 Voyage 的 health / inventory / quests /
   levels 那套 game state 搬过来（[官方说明](https://help.aidungeon.com/faq/the-memory-system)）；
   Inworld 明确说 realtime session 关闭后服务端记忆只保留 15 分钟，长期状态要客户端自己存 DB
   （[官方说明](https://docs.inworld.ai/realtime/usage/long-term-memory.md)）；
   Convai 的长期记忆是「用户 × 角色」事实集，不是可回溯的世界状态
   （[官方说明](https://docs.convai.com/api-docs/plugins-and-integrations/convai-unity-sdk/features/long-term-memory/how-long-term-memory-works.md)）。
   因此「事件是权威、快照只是缓存」仍然是更可靠的游戏底座。

5. **多角色并发：官方文档里没有「多写者共享世界」的锁 / 版本 / 冲突方案。**
   Convai 的聊天房间是「一次只处理一条消息」，消息框在回合期间锁定
   （[官方说明](https://docs.convai.com/api-docs/no-code-experiences/chat-experiences/running-the-room/how-a-turn-works.md)）；
   SillyTavern 群聊的群历史永远共享，只是决定「谁来说」
   （[官方文档](https://docs.sillytavern.app/usage/core-concepts/groupchats/)）；
   AI Dungeon 多人模式让所有人共享输入，官方说没有人数上限，并承认会出现 overlapping actions；
   文档没有给出并发控制说明（[官方说明](https://help.aidungeon.com/faq/do-you-support-multiplayer)）。
   WenJing 的「单 worker + 每 session 行锁 + CAS」不是落后，而是更严格。

6. **可见性：行业默认是「共享上下文」，不是「按 viewer 投影」。**
   AI Dungeon 明确：Story Card 的 spoiler 预览「不阻止 AI 使用该卡，也不让内容私有」
   （[官方说明](https://help.aidungeon.com/faq/story-cards)）；
   SillyTavern 群聊「无论选哪种，群聊历史始终在成员间共享」
   （[官方文档](https://docs.sillytavern.app/usage/core-concepts/groupchats/)）；
   Convai 的长期记忆严格按 `end_user_id + character_id` 隔离，但官方没有公开「同一场多角色对话内按角色隔离私密事实」的机制；
   它公开的隔离维度是 user×character 的长期记忆
   （[官方说明](https://docs.convai.com/api-docs/plugins-and-integrations/convai-unity-sdk/features/long-term-memory/how-long-term-memory-works.md)）。
   WenJing 的 `plot_entries_for(viewer)` + `world_facts`（公开 + 只说给该角色听的私密事实）
   （`backend/app/domain/game/game_runtime.py:909`、`backend/app/domain/agents/tools.py:22`）是更稀缺的能力。

7. **可重建性取决于「原始 episode 是否保留」。**
   Zep/Graphiti 把 episode 标为 ground truth（[官方文档](https://help.getzep.com/v4/concepts.md)）；
   Memobase 默认在处理后删除 blob，只留 profile / event（[官方 README](https://github.com/memodb-io/memobase)）；
   Inworld 明确「你的 DB 才是跨会话长期状态的 source of truth」（[官方说明](https://docs.inworld.ai/realtime/usage/long-term-memory.md)）。
   WenJing 的事件流天然满足「删派生索引不影响状态」，这是应该守住的不变量。

8. **不建议为 2–6 个角色引入外部记忆服务。**
   Mem0 / Zep / Supermemory / Cognee 的默认假设是「用户偏好 / 企业上下文 / 跨会话助手」，不是「多角色共享世界 + 分支回放 + 逐步可见性」；
   它们可以作为**可丢弃的派生检索索引**，由事件流喂数据，绝不能反向决定游戏状态。

### 0.1 能抄 / 别抄（速查）

| 判断 | 可抄 | 依据 |
|---|---|---|
| 上下文拼装 | 预算化：Required / Dynamic 分桶，硬上限，超限按优先级裁剪 | AI Dungeon context 说明 |
| 记忆写入 | 命令提交后异步整理；会话结束批量抽取 | Convai、Memobase、Letta、LangMem、Redis |
| 记忆建模 | 事实带时间窗 / 来源事件 / viewer；事件、关系、目标分开 | Zep、Charisma、Mem0 |
| 检索 | 语义 + 关键词 + 实体 + 时间多信号融合；importance/recency/reinforcement | Mem0、LangMem、AI Dungeon |
| 版本化 | 记忆可提交、可回滚、可审计 | Letta MemFS（git） |
| 可见性 | 读取口统一按 viewer 投影；公开必须是显式动作 | WenJing `plot_entries_for`、jubensha-ai `known_evidence` |
| 反模式 | 向量库当权威、每角色一份世界、热路径建图、摘要改写历史 | 见 §0 第 3 条、§6.8 |

---

## 1. 问题拆解：产品文档里的「记忆」到底在说什么

「角色记忆」经常被混成四个不同问题，再加上一个横向的可见性问题：

| 层面 | 回答的问题 | 权威性要求 | 常见载体 | 本轮产品里的典型说法 |
|---|---|---|---|---|
| **世界状态 world state** | 现在世界是什么样（时间、地点、谁在场、目标、资产） | 强一致、可回溯 | 事件流 / 事务数据库 / 游戏图 | AI Dungeon 明确不做传统 RPG game state；Chub 用 chat tree + message state |
| **角色记忆 character memory** | 这个角色「知道」什么、记得什么 | 每个角色视角不同、可重建 | 事件投影 / 有界窗口 / 私有仓 | Convai 按 user×character 存事实；Replika 分层记忆；WenJing `CharacterMemory` |
| **派生检索 recall index** | 给一个 cue，快速捞出相关历史 | 可最终一致、可重建 | 向量库 / KG / 倒排 | AI Dungeon Memory Bank（embedding）；Mem0 / Zep / Supermemory |
| **运行期上下文 working context** | 这一轮 prompt 里放什么 | 有界、可裁剪 | 内存 / prompt 拼装 | AI Dungeon 的 Required/Dynamic 预算；SillyTavern 的 prompt 注入 |
| **可见性 visibility** | 谁应该知道 / 不该知道 | 必须在读取口收口 | viewer 投影 / 命名空间 / 作用域 | WenJing `plot_entries_for`；Convai 的 user×character 作用域 |

关键判断：**只有前两者需要「权威」；检索索引与 working context 天然是派生 / 易失的。**
本轮看到的产品里，只有 Zep/Graphiti 把原始输入（episode）明确标成 ground truth、其余都从它派生
（[官方文档](https://help.getzep.com/v4/concepts.md)）；其余大多数产品把「记忆」直接等同于「可检索的文本块」，
没有回答「撤回 / 回溯 / 当时是否成立」的问题。

---

## 2. AI 剧本杀 & 互动叙事产品盘点

### 2.1 总表

| 产品 | 类型 | 记忆分层（官方口径） | 世界状态 / 分支 | 多角色并发 | 私有可见性 | 存储 / 写入时机 |
|---|---|---|---|---|---|---|
| **AI Dungeon** | AI 互动小说 | Auto Summary（每 15 动作）+ Memory Bank（每 6 动作一条 memory，embedding 检索）+ Story Cards（关键词触发）+ Plot Essentials / Author's Note | 无传统 game state；编辑/undo 不回算旧摘要 | 多人共享输入；未说明并发控制，官方承认会 overlapping | Story Card spoiler 只是 UI，不阻止 AI 使用 | story + summaries + vectors + cards；按固定动作间隔生成 |
| **Character.AI** | 角色聊天 | Pinned Memories（免费 15 / 付费 30 pins）+ 400 字符 Chat Memories + Auto Memories（c.ai+） | 未公开分支/回滚机制 | 单用户单角色聊天 | 记忆工具主要是用户侧，未公开按角色隔离 | 未公开；pins 由用户显式保存 |
| **Replika** | AI 伴侣 | 分层：Memory tab 可见 + 更深层系统从整体对话模式提取；自动 + 手动 | 无世界状态；聊天记录只保留 4 个月，但记忆/人格可延续 | 单用户单角色 | 单用户私有；未公开多角色 | 未公开；官方称「locally within your experience」，不应据此推断端侧存储 |
| **SillyTavern** | 本地 LLM 前端 | Character Card + World Info / lorebook + Summarize（滚动摘要）+ Data Bank RAG + Vector Storage | 分支聊天；群聊共享历史；scenario override 可继承 | 群聊有 reply order（manual/natural/list/pooled），共享历史 | 群聊历史所有成员共享；swap/join character cards | 本地 JSON + `/vectors` 文件；用户本地单机 |
| **Chub AI** | 角色聊天 | Lorebook（关键词、scan depth、token budget、recursive scanning）+ Chat Memory 摘要 | **完整 chat tree 分支**；Message State / Chat State / Initialization State | 以单聊天为中心；未见多写者并发文档 | lorebook 注入共享 prompt；未公开按角色隔离 | 未公开；分支状态按 message/chat 持久化 |
| **RisuAI** | 本地 / 跨平台聊天 | Lorebook + HypaMemoryV2/V3 + SupaMemory（README 口径） | 未公开 | 支持 group chats；未见并发文档 | 未公开 | 本地优先；未见服务端架构 |
| **筑梦岛** | 国内 AI 角色陪伴 | 官网只到产品层：单聊 / 群聊 / 小剧场 / 云端梦境「保存与重现记忆」 | 小剧场是「背景小传 + 特殊场景 + 片段故事」，不是可回溯世界状态 | 群聊存在；机制未公开 | 未公开 | 未公开 |
| **jubensha-ai（开源）** | 全 AI 剧本杀 | 三层：Identity / CharacterMemory（working_memory 30、personal_log 60、suspicion_map、known_evidence）/ PhaseDirector | 无事件溯源；只有 TTS 事件落库，重启丢状态 | 角色按阶段轮流发言，单进程 asyncio | `known_evidence` 只写发现者；公开需显式 `reveal_evidence` | 进程内存 + PostgreSQL（仅 TTS 事件）；无后台整理 |
| **百变大侦探 / 我是谜 / 戏精大侦探 / 谜案馆** | 国内剧本杀平台 | **未核验**（官方站点 transport error） | 未核验 | 未核验 | 未核验 | 未核验 |
| **Hidden Door / Janitor AI / Talkie / 星野 / 猫箱 / Glow / 冒泡鸭** | AI 角色扮演 | **未核验**（403 / transport error / 空响应） | 未核验 | 未核验 | 未核验 | 未核验 |

> 表中「未核验」的条目没有写入任何功能判断；原因与尝试过的 URL 见 §8。

### 2.2 逐条观察

#### AI Dungeon：目前公开得最细的「分层 + 预算 + 遗忘」

AI Dungeon 的 Memory System 由两块组成：**Auto Summarization** 与 **Memory Bank**，官方说它借鉴了 Voyage
（[官方说明](https://help.aidungeon.com/faq/the-memory-system)）。

- **Memory 的粒度是「六个动作的摘要」**：取玩家最近 6 个 action（含 AI 回复）交给摘要模型；
  新冒险进行到 12 个动作时，先摘要 1–6；之后每 6 个动作生成一条新 memory。
  这样最近 6 个动作永远保持原文，可编辑 / undo 而不影响已生成的 memory
  （[官方说明](https://help.aidungeon.com/faq/the-memory-system)）。
- **Auto Summary 是另一条更粗的线**：每 15 个动作总结整体剧情；在两次 summary 之间用 memory 填缝，
  保证「每个部分都被追踪」；summary 过长会自动压缩
  （[官方说明](https://help.aidungeon.com/faq/the-memory-system)）。
- **Memory Bank 用 embedding 做相关性检索**：每个 memory 存文本 + 向量；当故事超出 context 后，
  用最近动作的 embedding 对 memory bank 排序，取最相关的填进 context；bank 满了以后按「最少使用」淘汰，
  被淘汰的称 Forgotten Memories
  （[官方说明](https://help.aidungeon.com/faq/the-memory-system)）。
- **Memory Bank 容量按订阅分层**：Free 25、Champion 100、Legend 200、Mythic 400
  （[官方说明](https://help.aidungeon.com/faq/the-memory-system)）。
- **context 预算是显式的**：Required 元素（Instructions、Plot Essentials、Story Summary、Author's Note、
  Front Memory、Last Action）尽量全量；若超过 context 的 70%，按 Author's Note → Plot Essentials →
  AI Instructions → Story Summary 的优先级裁剪。Dynamic 元素拿剩余空间：约 25% Story Cards、
  约 50% History（Memory Bank 关闭时最多 75%）、约 25% Memory Bank；最终按固定顺序拼装
  （Instructions → Plot Essentials → Story Cards → Story Summary → Memory Bank → History → Author's Note → Last Action → Front Memory）
  （[官方说明](https://help.aidungeon.com/faq/what-goes-into-the-context-sent-to-the-ai)）。
- **Story Cards 是「关键词触发的世界事实」**：只有 Entry 会进 context，且冠以 `World Lore:`；
  Trigger 在输入或输出中出现才激活；AI 不知道 Story Card 的存在；最多 5000 张
  （[官方说明](https://help.aidungeon.com/faq/story-cards)）。
  注意：Creators 的 `Player preview → Contains spoilers` **只隐藏玩家界面上的名称/类型/Entry，
  不阻止 AI 使用该卡，也不让内容私有**（[官方说明](https://help.aidungeon.com/faq/story-cards)）。
- **它不是世界状态机**：官方明确说 AI Dungeon 是 collaborative storytelling，没有把 Voyage 的
  health / quests / inventory / levels / player characteristics 那套 game state 搬过来
  （[官方说明](https://help.aidungeon.com/faq/the-memory-system)）。
- **多人模式没有给出并发方案**：host 的 AI 设置对所有玩家生效；官方说「目前没有人数上限」，
  并承认人多时会出现 overlapping actions（[官方说明](https://help.aidungeon.com/faq/do-you-support-multiplayer)）。

**对 WenJing 的启示**：这是「记忆分层 + 预算 + 遗忘」最完整的公开样本；但它把「世界状态」让给了叙事文本，
且摘要与历史编辑之间没有强一致。WenJing 应该学它的预算与分层，而不是学它的状态模型。

#### Character.AI：记忆是「用户可管理的 pins + 自动摘要」，不是世界状态

Character.AI 的官方帮助中心（Zendesk）能通过 API 取到全文；HTML 文章页对抓取返回 403，但内容本身可核验。

- 2024 年的 Pinned Memories：所有用户可在每个 chat 中保存并 pin **5 条消息**，帮助角色记住重要细节
  （[官方帮助](https://support.character.ai/hc/en-us/articles/24327914463003-Pinned-Memories)）。
- 2026 年的订阅对比已经变成：Free **15 pins**、lite **30 pins**、c.ai+ **30 pins**；
  Memory 能力分 Basic / Better / Best，Lorebook 分 Basic / Basic / Advanced
  （[官方帮助](https://support.character.ai/hc/en-us/articles/56173313531675-About-c-ai-lite)）。
  **同一官方帮助中心的口径随时间变化**，引用时要看清日期。
- 2025 年 3 月上线 **Auto Memories**：自动捕捉对话中的重要细节和事实；刚上线时不可编辑
  （[官方社区更新](https://support.character.ai/hc/en-us/articles/35409588582683-Community-Update-March-2025)）。
- 2026 年的角色创作指南把记忆工具描述为「mostly user-side」：用户控制 pinned messages、
  **400 字符的 Chat Memories 字段**，以及 c.ai+ 的 auto-memories；创作者能控制的是 Definition 的稳定性
  （[官方帮助](https://support.character.ai/hc/en-us/articles/50609303987099-6-Refining-and-Testing-your-Character)）。

**判断**：Character.AI 的记忆是「用户侧可管理 + 平台自动摘要」，没有公开的 per-character 知识边界、
世界状态或并发方案。它的 Lorebook 是关键词式世界信息，不是可回溯世界状态。

#### Replika：分层记忆 + 聊天记录与记忆解耦

- 官方明确说记忆是**分层**的：一部分在 Memory tab 可见，另一部分在更深层系统里，从整体对话历史中提取模式；
  自动记忆效果最好，手动添加是补充；删除记忆会影响某些细节的召回
  （[官方帮助](https://help.replika.com/hc/en-us/articles/37208679176077-How-does-Replika-s-memory-work)）。
- 官方称这套系统「works locally within your experience」，并说不会保留对话的永久记录
  （[官方帮助](https://help.replika.com/hc/en-us/articles/37208679176077-How-does-Replika-s-memory-work)）。
  这句话容易被误解为「端侧存储」；官方没有给出存储架构，**不应据此推断**。
- 聊天记录只保留最近 **4 个月**，但官方说这不影响 Replika 的记忆、人格或训练
  （[官方帮助](https://help.replika.com/hc/en-us/articles/4411154990605-Is-the-chat-history-infinite)）。
  这是「记忆与原始 transcript 解耦」的产品级例子，但没有说明记忆如何重建。
- Ultra 订阅提供「保存记忆 + 查看哪些记忆在对话中被使用」
  （[官方帮助](https://help.replika.com/hc/en-us/articles/37292892831885-What-is-Replika-Ultra)）。

**判断**：Replika 是「用户画像型长期记忆」的典型；没有世界状态、分支、多角色并发。它的价值在于证明
「记忆不必等于聊天记录」，但也暴露了「不可解释的深层记忆」问题（用户只能看到一部分）。

#### SillyTavern：本地单机、共享历史、prompt 工程优先

SillyTavern 是本地安装的 LLM 前端，不是托管服务
（[官方文档](https://docs.sillytavern.app/)）。

- **Character Card + World Info / lorebook**：角色卡是持久对话的 prompt 集合；World Info 用关键词激活世界信息
  （[官方文档](https://docs.sillytavern.app/)）。
- **Summarize 扩展**：自动生成 / 存储 / 使用聊天摘要；摘要写在 chat 文件 metadata 里；
  删除或编辑带摘要的消息会回退到上一个有效摘要；支持 Restore Previous；官方明确提醒摘要可能丢细节或幻觉，
  建议人工校正（[官方文档](https://docs.sillytavern.app/extensions/summarize/)）。
- **Data Bank (RAG)**：附件分 Global / Character / Chat 三种作用域；Vector Storage 用 Vectra 把 embedding
  存在用户数据目录的 `/vectors` JSON 文件里；文档按 chunk 检索后注入 prompt
  （[官方文档](https://docs.sillytavern.app/usage/core-concepts/data-bank/)）。
- **群聊**：无论 `Swap character cards` 还是 `Join character cards`，**群聊历史始终在所有成员间共享**；
  `Swap` 只把当前发言者的角色卡放进 context，`Join` 把所有成员的角色卡拼成一个 prompt
  （[官方文档](https://docs.sillytavern.app/usage/core-concepts/groupchats/)）。
  reply order 支持 manual / natural order / list order / pooled order；可以 mute、force talk、auto-mode
  （[官方文档](https://docs.sillytavern.app/usage/core-concepts/groupchats/)）。

**判断**：SillyTavern 的群聊是「多角色共享一个聊天历史」，不是「多角色各自有私有记忆 + 共享世界」。
它的 Summarize 与 Data Bank 是 WenJing 可以借鉴的「滚动摘要 + 分作用域 RAG」拼装方式，
但它的状态模型是单机文件，不是并发服务。

#### Chub AI：分支感知的 state 是三家里最接近事件溯源的

Chub AI 官方文档有几个值得注意的设计：

- **Lorebook**：关键词触发，支持 Scan Depth、Token Budget、Recursive Scanning、Priority、Probability、Constant、
  Selective / Secondary Keywords；默认大小写不敏感、整词匹配
  （[官方文档](https://docs.chub.ai/docs/advanced-setups/lorebooks.md)）。
  这和 AI Dungeon Story Cards / SillyTavern World Info 是同一类「按 cue 注入世界事实」的机制。
- **Chat Tree**：官方称支持完整 tree branching，类似 ChatGPT 的分支，可用于 swipe 或多路径 choose-your-own-adventure
  （[官方文档](https://docs.chub.ai/docs/the-basics/just-chatting.md)）。
- **Stage state 分三种**（这是最有价值的）：
  - **Initialization State**：扩展第一次实例化时创建一次，之后每次加载都复用；
  - **Message State**：给定消息的当前状态，`beforePrompt` / `afterResponse` 返回；
    官方特别说「在 linear chat 里属于 chat state 的东西，比如到达当前点的 path，也应该放在 message state」；
  - **Chat State**：整个 chat 共用、**跨所有分支**的状态；官方说它「在任何其他 UI 里没有对应概念」，
    举例是 fog of war；并警告 health / position / path 都不该放这里
    （[官方文档](https://docs.chub.ai/docs/stages/developing-a-stage/state.md)）。

**判断**：Chub 的 message state / chat state 切分，实际上是在教扩展作者「哪些状态属于分支、哪些属于全局」。
这比大多数产品只给一个「chat memory」要精细。WenJing 的 `CharacterMemory` 与 `RuntimeAssets` 也可以明确标注
「哪些是分支内、哪些是跨分支缓存」。

#### RisuAI：README 只到功能层

RisuAI README 声明支持 group chats、Lorebook、HypaMemoryV2/V3 memory compression、SupaMemory context management、
TTS、regex、插件等（[官方 README](https://raw.githubusercontent.com/kwaroran/RisuAI/main/README.md)）。
但 README 没有给出这些 memory 的内部结构、写入时机、检索方式或并发模型；本轮没有抓到可用的 wiki 页面
（`github.com/kwaroran/Risuai/wiki` transport error），因此**不写入实现判断**。

#### 筑梦岛：产品层有「群聊 / 小剧场 / 云端梦境」，机制未公开

筑梦岛官网可访问，提供 1v1 单聊、群聊、小剧场（人物背景小传、平行世界、补充设定、片段故事、番外）、
以及「云端梦境：随时保存与重现美好梦境，回味每一分每一秒的点滴记忆」
（[官方网站](https://www.zhumengdao.com/)）。
这些都是产品功能描述，没有公开记忆分层、世界状态权威、并发或存储架构；**只能当作产品形态参考，不能当实现依据**。

#### 开源 AI 剧本杀：jubensha-ai 的「私有仓 + 显式公开」值得看

`jubensha-ai` 是一个全 AI 角色扮演的剧本杀开源项目（[GitHub](https://github.com/JianWang97/jubensha-ai)）。
本仓库已有源码级分析 `docs/research/jubensha-ai.md`，本轮复核其要点：

- 角色层分 Identity / CharacterMemory / PhaseDirector；`CharacterMemory` 含 `working_memory`（deque 30）、
  `personal_log`（容量 60，按 importance 淘汰）、`suspicion_map`、`known_evidence`
  （`docs/research/jubensha-ai.md`）。
- **知识边界落在私有记忆结构**：搜证结果只写发现者 memory；`reveal_evidence` 只能公开自己 `known_evidence` 里的证据，
  公开是一个显式工具动作，而不是模型在叙述里顺嘴说出（`docs/research/jubensha-ai.md`）。
- **但它没有事件溯源**：对话 / 推理 / 阶段切换只进内存列表；只有 TTS 事件落库；服务重启即丢状态；
  无提议 / 验证、无整体审校、无配额控制（`docs/research/jubensha-ai.md`）。

**判断**：jubensha-ai 的「私有仓 + 显式公开动作」是 WenJing 可以直接借鉴的**知识边界机制**；
它的持久化与并发是反面教材。

#### 国内剧本杀平台：本轮没有可引用的一手页面

对百变大侦探（`bcdzt.com` / `bcdzt.cn`）、我是谜（`woshimi.com` / `woshimi.cn`）、
谜案馆（`mianguan.com`）的官方站点抓取均返回 transport error；戏精大侦探没有找到可访问的官方文档页。
因此本轮**不写入**它们的 AI 记忆能力、世界状态或并发结论。若后续要补，优先找官方帮助中心 / 官方技术博客 /
官方 API 文档，而不是应用商店文案或二手测评。

---

## 3. NPC / 角色记忆引擎盘点

### 3.1 总表

| 引擎 | 记忆分层 | 世界状态 | 多角色 / 并发 | 可见性 | 写入时机 | 存储 |
|---|---|---|---|---|---|---|
| **Inworld** | session 内 facts + rolling summary；跨会话靠客户端持久化 | 无游戏世界状态；realtime session 关闭即丢 | 每个 session 独立；未见共享世界并发 | 未公开按角色投影 | session 内每 N 轮抽取；跨会话由客户端 re-inject | 服务端临时状态 + 你的 DB（可选 pgvector） |
| **Convai** | 会话 buffer + `MemoryRecord` 长期事实；Knowledge Bank（RAG / In-Context） | 无世界状态；一次一回合的聊天房间 | 房间一次一条消息；多角色各自回答 | 长期记忆按 `end_user_id + character_id` 隔离，不跨角色 | 会话结束时批量抽取；dedup update | Convai 托管；提供 Memory API |
| **NVIDIA ACE** | Agent API 自带 conversation history；RAG API 检索开发者数据库 | 无持久世界状态；游戏状态由应用负责 | MultiAgent 样例：两个 Agent 共享一个 SLM、各自 identity/history | 应用自己控制 | 应用驱动；未见跨会话记忆服务 | 端侧模型 + 开发者 RAG DB |
| **Charisma.ai** | 5 类结构化 memory（Word / Sentence / Decision / Counter / True-false）+ Tags | 故事图 + Gates 决定分支 | 未公开并发文档 | 作者定义的 gate 条件；未见 per-character 私有记忆 | 交互点显式写入 / 作者编排 | 未公开 |
| **Scenario** | 不是角色记忆引擎；是图像 / 视频 / 3D 生成与模型训练平台 | 不适用 | 不适用 | 不适用 | 不适用 | 不适用 |

### 3.2 Inworld：Character Studio 已退役，记忆变成「session 内自动 + 跨会话自己存」

这是本轮最重要的「对象已变化」发现之一：

- **旧 Character Studio 已退役**。官方说明：characters、scenes、knowledge、triggers、variables、interactions、
  voice studio、player profiles 等不再可用；能力迁移到 Inworld Portal 和 **Agent Runtime**
  （[官方文档](https://docs.inworld.ai/character-studio-deprecation.md)）。
  Runtime 仍提供 knowledge retrieval、safety、long-term memory、expressive voice、emotion、relationship modeling
  （[官方文档](https://docs.inworld.ai/character-studio-deprecation.md)）。
- 当前文档首页主体是 **Voice / Inference**（TTS、STT、Realtime、Router）
  （[官方文档](https://docs.inworld.ai/)；[llms.txt](https://docs.inworld.ai/llms.txt)），
  不再是旧的 Character Engine 文档结构。
- **Realtime 的长期记忆机制**（[官方文档](https://docs.inworld.ai/realtime/usage/long-term-memory.md)）：
  - Realtime session 是临时的：服务端只保留 WebSocket 生命周期 + 默认 **15 分钟**空闲 TTL；之后服务端记忆消失。
  - `providerData.memory` 开启后，服务端**周期性**让 LLM 从对话中抽取 durable facts 和 rolling summary，
    前插到 system prompt，并裁掉旧 transcript，保持 context 有界。
  - 抽取状态通过 `session.updated` 返回，形状含 `version`、`facts`、`summary`、`context_text`、
    `turns_since_gen`、`total_turns`、`items_trimmed`；客户端用 `version` 去重写 DB。
  - 跨会话恢复靠客户端：Option A 把 `facts` + `summary` 存成一行（KV / Postgres JSON），每次新 session 注入
    `instructions`；Option B 用向量库（pgvector / Pinecone / Weaviate）只召回 top-K facts。
  - 可调参数：`turn_interval`（默认 5）、`max_facts`（如 50）、`max_memory_length`（如 2000 字符）。
  - 官方原话：**"your DB is the source of truth for long-term state"**，realtime API 本身不跨会话持久。

**判断**：Inworld 的文档把「记忆是派生的、外部 DB 才是权威、客户端负责 re-inject」讲得最清楚。
它没有游戏世界状态，也没有多角色共享世界的并发语义；适合做「对话型 NPC」，不适合直接承载剧本杀世界。

### 3.3 Convai：user×character 作用域 + 会话末批处理 + 明确的能力边界

Convai 的长期记忆文档非常坦诚，几乎是一份「不要误解记忆」的清单：

- **会话生命周期**：connect 时发送 `end_user_id` + `character_id`；Convai 解析出已存事实并注入 context；
  对话中的新信息**不实时写入**，先进 session buffer；session 结束时处理 transcript，抽取 `MemoryRecord`
  （姓名、角色、偏好、完成任务、陈述的历史等），存到 `end_user_id + character_id` 下；下次 connect 再注入
  （[官方文档](https://docs.convai.com/api-docs/plugins-and-integrations/convai-unity-sdk/features/long-term-memory/how-long-term-memory-works.md)）。
- **作用域**：每条记忆严格属于一个 user–character 对；用户 A 在角色 X 上的记忆，用户 B 和角色 Y 都看不到；
  多角色之间**没有跨角色共享**
  （[官方文档](https://docs.convai.com/api-docs/plugins-and-integrations/convai-unity-sdk/features/long-term-memory/how-long-term-memory-works.md)）。
- **去重**：语义等价的新事实会更新已有 `MemoryRecord`，不产生重复；`MemoryAddResult.Event` 返回 `"update"` 或 `"add"`
  （[官方文档](https://docs.convai.com/api-docs/plugins-and-integrations/convai-unity-sdk/features/long-term-memory/how-long-term-memory-works.md)）。
- **明确不做**：不做实时查询（只在 connect 时注入，角色不能在对话中查询记忆库）；不保证每句话都被存；
  不跨角色共享；默认不开启
  （[官方文档](https://docs.convai.com/api-docs/plugins-and-integrations/convai-unity-sdk/features/long-term-memory/how-long-term-memory-works.md)）。
- **Knowledge Bank**：账号级文件库，可连接到任意角色；两种模式——RAG（只接受 `.txt` / `.csv`，检索相关段落）
  与 In-Context（整库每轮放进 prompt，支持 image / PDF / audio / video，取决于所选 LLM）
  （[官方文档](https://docs.convai.com/api-docs/convai-playground/character-customization/knowledge-bank.md)）。
- **多角色聊天房间**：一次只处理一条消息；消息和它引出的回复算一个 turn；回合期间消息框锁定；
  caption 会报告 `2 of 4 responded`、`1 listening`、`1 did not answer` 等；Auto 模式下角色可以保持沉默
  （[官方文档](https://docs.convai.com/api-docs/no-code-experiences/chat-experiences/running-the-room/how-a-turn-works.md)）。

**判断**：Convai 是「单用户 × 多角色」场景里最成熟的产品化记忆：**per-user-per-character 隔离 + 会话末批处理 +
明确不实时**。它的「不跨角色共享」对 WenJing 有直接参考价值；但官方没有公开「同一世界内角色 A 不知道 B 的私密事实」
这种更细的 viewer 投影。

### 3.4 NVIDIA ACE：提供 Agent / Chat / RAG 原语，记忆由应用负责

- ACE 是「speech + intelligence + animation」的模型与插件套件，面向游戏中的 knowledgeable / actionable /
  conversational 角色，提供云端与端侧模型
  （[官方页面](https://developer.nvidia.com/ace)）。
- **Game Agent SDK** 提供三组 API：**Agent**（有状态，拥有 conversation history，驱动推理循环和 tool-call 链）、
  **Chat**（无状态，应用自己控制推理）、**RAG**（semantic / lexical / hybrid 检索开发者数据库）
  （[官方 README](https://github.com/NVIDIA/game-agent-sdk)）。
- **MultiAgent-Sample**：两个 Agent 共享一个 SLM，但各自有 distinct identities 和 conversation histories
  （[官方 README](https://github.com/NVIDIA/game-agent-sdk)）。
- 没有看到「跨会话长期记忆服务」或「世界状态回溯」的官方设计；端侧 SLM + 开发者 RAG 是主要形态
  （[官方 README](https://github.com/NVIDIA/game-agent-sdk)）。

**判断**：ACE 的「Agent 持有 history、RAG 检索外部知识」是干净的运行时切分，但它把长期记忆与世界状态留给应用。
对 WenJing 的启示是：**记忆不是模型能力，是应用编排**。

### 3.5 Charisma.ai：作者定义的结构化记忆 + Gates，适合确定性叙事

Charisma 的 memory 不是 LLM 自动抽取，而是作者显式定义的五类：

- **Word**：从玩家回答中抓特定词（如名字），依赖 Categories；
- **Sentence**：记住玩家在某个交互点说的整句话；
- **Decision**：记住玩家做过的决定或走过的路线；
- **Counter**：记住某件事发生了多少次，可 increase / decrease / set；
- **True/false**：布尔记忆；
- **Tags**：不用预先创建 memory，直接在某角色节点上 set/unset，等价于轻量 true/false。
  （[官方文档](https://docs.charisma.ai/memories-gates)）

**Gates** 用这些记忆 + 情绪 / 心情 / 与玩家的关系 / tag 来决定下一个节点走哪条路；所有条件满足才放行，
否则走 alternative route；官方提醒必须留一条 non-gated route，否则玩家会卡住
（[官方文档](https://docs.charisma.ai/memories-gates)）。

**判断**：Charisma 是「确定性叙事 + 作者编排」的代表。它没有 LLM 自主抽取，也没有并发/多租户文档，
但它证明了**结构化 memory + gate 条件**可以让状态可解释、可测试——这正是 WenJing 的 Stage3 目标判定可以借鉴的。

### 3.6 Scenario：不是记忆引擎

Scenario 官方文档的主体是图像 / 视频 / 3D 生成、模型训练、批量资产处理、CDN、Webhooks
（[官方文档](https://docs.scenario.com/)）。它不在本轮「角色记忆 / 世界状态 / 多角色并发」的范围内；
把它列进来容易造成错误类比。

---

## 4. 通用记忆服务盘点

### 4.1 总表

| 服务 | 开源 / 托管 | 记忆分层 | 写入 / 合并 | 检索 | 存储 | 多租户 / 并发 | 可重建 |
|---|---|---|---|---|---|---|---|
| **Letta（原 MemGPT）** | 开源（letta-code）+ Cloud | MemFS 文件系统 + 会话；root 文件进 system prompt，目录按需读 | Agent 自己编辑 + `/remember`；dreaming 后台整理 | 默认文件搜索；可选 MemFS Search（keyword / semantic / hybrid） | git 仓库（Markdown + YAML frontmatter） | 每 agent 独立 MemFS；shared memory；git worktree 并发 | git 历史可回滚；语义索引可选、可重建 |
| **Mem0** | 开源 + Platform | user / agent / run 作用域；SQL facts + vector + entity | 单次 ADD-only 抽取；显式 update/delete；entity linking | semantic + BM25 + entity + temporal 多信号 | SQL（事实权威）+ vector + entity store | 用 filters 隔离；未见并发保证 | 有 memory history；派生索引可重建（取决于配置） |
| **Zep / Graphiti** | Graphiti 开源；Zep 托管 / BYOC | entities + facts + episodes + observations + thread summaries + user summary | 增量 ingestion；事实失效不删除；bi-temporal | semantic + BM25 + graph traversal | 图数据库（Neo4j / FalkorDB / Neptune；Kuzu 弃用） | Graphiti 默认 `SEMAPHORE_LIMIT=10`；参考 server 无鉴权/租户 | episode 溯源；可点时间查询 |
| **LangMem** | 开源库 | semantic / episodic / procedural；profiles vs collections | memory manager 抽取/合并/更新；hot path 或 background | BaseStore：直接读、语义搜索、metadata filter | 任意存储；LangGraph `BaseStore` / `AsyncPostgresStore` | namespace 隔离；未见并发保证 | 取决于底层 store |
| **Cognee** | 开源 + Cloud | graph + vector + relational；session distillation | `remember` / `improve` / `forget`；会话经验审核进永久图 | graph / vector / code 检索；自动路由 | 图 + 向量 + 关系；单 Postgres demo | 默认 multi-tenant（需鉴权） | 源数据 + 图；`forget` 可删 |
| **Redis Agent Memory** | 托管（Redis Iris）+ V0 开源归档 | session（TTL）+ long-term facts + vectors | 后台从 session 抽取并提升 | 向量 + 事实检索 | Redis | 托管服务；未见游戏并发语义 | 有 LongMemEval harness；V0 可研究 |
| **Memobase** | 开源 + Cloud | user profile slots + event timeline | buffer flush（1024 token / 1h / manual）；固定 3 次 LLM 调用 | profile / event / context API | Postgres + Redis + FastAPI | 多用户；未见并发语义 | **默认处理后删 blob**，除非配置持久化 |
| **Supermemory** | 开源 local + 托管 | documents（RAG）+ memories（用户事实）+ profiles（static / dynamic） | 自动抽取、矛盾消解、过期遗忘；graph engine | hybrid（RAG + memory） | graph engine（local）+ 文档 / 记忆 | container tags / projects 隔离 | 源文档 + memory；可重建性未公开 |
| **Motorhead** | 开源（**已弃用**） | session window + incremental summary + Redis VSS | window 满后 summarize 一半；增量摘要 | 文本 + VSS | Redis | 单 session；已停止维护 | 不适用（不建议采用） |

### 4.2 Letta / MemGPT：从「OS 分页」转向「git 版本化文件记忆」

Letta（原 MemGPT）当前官方文档把长期记忆落成 **MemFS**，而不是只讲「上下文窗口分页」：

- Letta 仓库 README 明确：当前源码在 `letta-ai/letta-code`；`archive` 分支是 retired V1 API server
  （[官方 README](https://raw.githubusercontent.com/letta-ai/letta/main/README.md)）。
- **MemFS 是 git-backed memory filesystem**：memory 是 agent state 的一部分，存在 agent 自己的 git 仓库里；
  投影到运行机器上就是普通文件；编辑只有 commit + push 后才成为「到处都有的记忆」
  （[官方文档](https://docs.letta.com/concepts/memfs)）。
- **分层是靠路径与 `MEMORY.md` 索引**：root 下的文件每轮进 system prompt（identity、重要用户偏好、durable project facts、
  critical workflow rules）；有自己 `MEMORY.md` 的目录默认不进 context，靠索引按需读；
  这样 active context 保持精简（[官方文档](https://docs.letta.com/concepts/memfs)）。
- **默认没有语义 / 向量索引**：用普通文件搜索和 read 工具找记忆；要 keyword / semantic / hybrid 得装 MemFS Search mod，
  semantic/hybrid 还依赖 QMD 建索引（[官方文档](https://docs.letta.com/concepts/memfs)）。
- **版本与并发**：每次编辑都 commit，因此有 version history、conflict resolution、saved/uncommitted 边界；
  dreaming / memory doctor 等 memory subagents 用 git worktree **并发更新**而不阻塞主 agent
  （[官方文档](https://docs.letta.com/concepts/memfs)）。
- **dreaming 是后台整理**：background subagents 复盘最近对话、合并 lessons、更新 memory，不打断当前工作；
  可配置在 N 个 agent steps 后或 context compaction 时运行，也可以让 agent 二次 review 再应用
  （[官方文档](https://docs.letta.com/configuration/memory)）。
- **容量**：Free 每个 memory repo 5 MiB，Pro 50 MiB（只算每个 branch/tag 最新快照，不算 git history）
  （[官方文档](https://docs.letta.com/configuration/memory)）。

**判断**：Letta 现在更像「agent 自己维护的、可版本化的知识库」，而不是「游戏世界状态」。它的 git worktree 并发、
root/目录分层、dreaming 后台整理都值得借鉴；但**git 分支是文件版本，不是游戏叙事分支**，不能直接当 WenJing 的回溯机制。

### 4.3 Mem0：ADD-only 抽取 + SQL 事实权威 + 多信号检索

- README 的新算法（2026-04）强调 **single-pass ADD-only extraction**：一次 LLM 调用，不做 UPDATE/DELETE，
  记忆累积、不覆盖；agent 确认的事实与用户事实同等权重；entity linking；多信号 retrieval
  （semantic + BM25 + entity）；temporal reasoning
  （[官方 README](https://raw.githubusercontent.com/mem0ai/mem0/main/README.md)）。
- 官方 how-it-works：`add` 时先 context lookup，再 fact extraction、dedup + embedding、entity extraction；
  自动路径是 additive，用户说「我从 Austin 搬到 Seattle」不会静默改写旧事实，需要显式 `update` / `delete`
  （[官方文档](https://docs.mem0.ai/core-concepts/how-it-works)）。
- **存储分三处**：SQL 存 facts + metadata（**source of truth**）、vector 存 embeddings、entity store 存实体关系；
  Platform 上 entity store 还支撑 Graph Memory；OSS 只有 entity overlap boost，没有 graph memory
  （[官方文档](https://docs.mem0.ai/core-concepts/how-it-works)）。
- **作用域**：`user_id` / `agent_id` / `run_id` + metadata；官方强调 search 一定要带 filter，避免不同用户/agent/session 串数据
  （[官方文档](https://docs.mem0.ai/core-concepts/how-it-works)）。
- **厂商 benchmark**：README 给出 LoCoMo 92.5、LongMemEval 94.4、BEAM 1M 64.1 / 10M 48.6，token 约 6.7–7.0K，
  p50 约 0.88–1.09s；并明确这些是 **managed platform** 的数字，OSS 只是方向相似、不保证相同
  （[官方 README](https://raw.githubusercontent.com/mem0ai/mem0/main/README.md)）。

**判断**：Mem0 的「ADD-only + 多信号 + SQL 权威」适合做**派生的用户事实层**；但它没有世界状态、分支、角色知识边界。
如果 WenJing 要用，应该把它当「可丢弃的 recall 索引」，而不是游戏状态库。

### 4.4 Zep / Graphiti：bi-temporal 事实 + episode 溯源，但明确不是「agent memory 产品」

- Graphiti 是构建 / 查询 **temporal context graph** 的开源框架：entities、facts（带 temporal validity windows）、
  episodes（raw data，ground truth，所有派生事实都可追溯到这里）、custom types（Pydantic ontology）
  （[官方 README](https://raw.githubusercontent.com/getzep/graphiti/main/README.md)）。
- 事实变化时**旧事实失效而不删除**；支持「现在为真」与「某时刻为真」；增量构图；hybrid retrieval
  （semantic + BM25 + graph traversal）
  （[官方 README](https://raw.githubusercontent.com/getzep/graphiti/main/README.md)）。
- 后端：Neo4j / FalkorDB / Amazon Neptune；**Kuzu 已弃用**（上游不维护）
  （[官方 README](https://raw.githubusercontent.com/getzep/graphiti/main/README.md)）。
- 并发：ingestion 默认 `SEMAPHORE_LIMIT=10` 限制并发以避 LLM 429；参考 REST/MCP server **无认证、无授权、无租户隔离、
  无 prompt-injection 防护**，官方明确说不要暴露到不可信网络
  （[官方 README](https://raw.githubusercontent.com/getzep/graphiti/main/README.md)）。
- Zep v4 文档把 facts 的四个时间戳讲得很清楚：`created_at` / `valid_at` / `invalid_at` / `expired_at`；
  事实是 edge，检索默认 target 是 facts；Context Block 会带 validity window
  （[官方文档](https://help.getzep.com/v4/facts.md)）。
- Zep 还区分 facts / entities / episodes / thread summaries / observations / user summary，并提供 Context Block 组装
  （[官方文档](https://help.getzep.com/v4/concepts.md)）。
- **重要措辞**：Graphiti README 明确说「Neither is an agent memory product: Graphiti is a framework for building graphs,
  and Zep unifies, governs, and serves an enterprise's context.」
  （[官方 README](https://raw.githubusercontent.com/getzep/graphiti/main/README.md)）
  也就是说，Graphiti 是框架、Zep 是企业上下文层；它们不承诺做「游戏角色记忆」。

**判断**：Zep/Graphiti 的 bi-temporal 建模值得借鉴（事实带 valid window、失效不删除、episode 溯源）；
但把它当世界状态权威会引入图数据库运维与租户/鉴权成本，且它没有「角色私有可见性」与「游戏分支」语义。

### 4.5 LangMem：把「记忆类型」和「写入时机」讲得最清楚

LangMem 把长期记忆分成三类：

- **Semantic**：事实与知识；两种表示——**Collection**（无界知识，检索）与 **Profile**（严格 schema 的当前状态，
  每次更新覆盖同一文档）；
- **Episodic**：过去经验，作为 few-shot / 成功案例；
- **Procedural**：系统行为 / 人格 / 响应模式，可优化 prompt。
  （[官方文档](https://langchain-ai.github.io/langmem/concepts/conceptual_guide/)）

写入时机明确分两种：

- **Conscious / hot path**：对话中由 agent 主动存，立即更新，但增加延迟与工具选择复杂度；
- **Subconscious / background**：对话后或空闲时让 LLM 复盘、抽取模式，不拖慢交互。
  （[官方文档](https://langchain-ai.github.io/langmem/concepts/conceptual_guide/)）

存储：核心 API 不依赖特定存储；stateful 版本用 LangGraph `BaseStore`，namespace 可分层（org / user / app），
支持直接 get、语义 search、metadata filter；生产用 `AsyncPostgresStore`，README 明确 `InMemoryStore` 重启即丢
（[官方 README](https://raw.githubusercontent.com/langchain-ai/langmem/main/README.md)；
[官方文档](https://langchain-ai.github.io/langmem/concepts/conceptual_guide/)）。

**判断**：LangMem 的「profiles vs collections」「hot path vs background」是 WenJing 设计记忆表时最好的概念框架；
它的 namespace 思路可以直接映射到 `session_id / character / viewer`。

### 4.6 Cognee：remember / recall / improve / forget + 单 Postgres 图记忆 demo

- Cognee 是开源 AI memory platform：把文档、代码、对话转成可搜索的知识图；提供 `remember` / `recall` / `improve` /
  `forget` 四操作；文本变实体 / 关系 / chunk，代码变符号依赖图；**session distillation** 把会话经验审核后进永久图
  （[官方 README](https://raw.githubusercontent.com/topoteretes/cognee/main/README.md)）。
- 无 LLM key 也能用本地 GLiNER + 本地 embedding 跑文本 ingestion / retrieval；LLM-dependent 的 improve 阶段会跳过
  （[官方 README](https://raw.githubusercontent.com/topoteretes/cognee/main/README.md)）。
- **单 Postgres 跑整个 memory layer** 目前是 **demo feature**；生产版是 licensed product
  （[官方 README](https://raw.githubusercontent.com/topoteretes/cognee/main/README.md)）。
- 多租户：Docker 默认 multi-tenant，每个 `/api/v1` 调用都要认证；单用户 demo 才设 `ENABLE_BACKEND_ACCESS_CONTROL=false`
  （[官方 README](https://raw.githubusercontent.com/topoteretes/cognee/main/README.md)）。
- 厂商 BEAM：100K context 0.79、10M context 0.67；README 明确说两次设置使用不同对话、ingestion 模型、检索选择流程，
  比较前要读 methodology
  （[官方 README](https://raw.githubusercontent.com/topoteretes/cognee/main/README.md)）。

**判断**：Cognee 的「session 经验蒸馏进永久图」适合「经验/规则」型记忆；它的图 + 向量 + 关系三件套
对 WenJing 的「派生索引」有参考价值，但单 Postgres 图仍是 demo，不建议为 2–6 角色上生产图库。

### 4.7 Redis Agent Memory：session 热层 + 长期冷层 + 后台提升

- 两层：**session memory**（活跃会话状态，可配 TTL）+ **long-term memory**（抽取事实 + 文本 + 向量）
  （[官方 README](https://raw.githubusercontent.com/redis/agent-memory-server/main/README.md)）。
- 新事件进 session 后，后台抽取并提升到 long-term；强调「不拖慢在线 agent loop」
  （[官方 README](https://raw.githubusercontent.com/redis/agent-memory-server/main/README.md)）。
- 现在作为 Redis Iris 的托管服务；`V0/` 是原始开源实现，保留为研究工件，不是生产分发
  （[官方 README](https://raw.githubusercontent.com/redis/agent-memory-server/main/README.md)）。
- 官方 LongMemEval harness 强调「结果依赖 provider 版本、split、模型、检索设置、运行日期，不是永恒排名」；
  另外提到一个组合 Instruct + Remis 的研究配置达到 86.5%、约 $0.07/session，但 **Remis 尚未进产品、86.5 不是产品分数**
  （[官方 README](https://raw.githubusercontent.com/redis/agent-memory-server/main/README.md)）。

**判断**：这是「热 session + 冷事实 + 后台提升」最实用的成本结构；WenJing 的 `CharacterMemory`（热窗口）+
派生事实表（冷层）+ 后台整理，几乎可以照这个形状做，但不需要 Redis。

### 4.8 Memobase：用户 profile + event timeline，明确不走热路径

- Memobase 是 **user profile-based memory**：为每个用户维护结构化 profile slots（basic_info / education / interest /
  psychological / work 等，可自定义）+ 事件时间线
  （[官方 README](https://github.com/memodb-io/memobase)；
  [官方文档](https://docs.memobase.io/features/profile/profile)）。
- **写入不是热路径**：每个用户有 buffer；buffer 超过约 **1024 tokens** 或空闲约 **1 小时**，或手动 `flush()` 时，
  才把整段 buffer 处理进 memory；官方明确说「我们不在 hot path 里 memoize users」
  （[官方 README](https://github.com/memodb-io/memobase)）。
- 每条 event 包含 event summary（可选）、event tags（如 `emotion::happy`、`goal::buy_a_house`）、
  profile delta（必填，记录本次创建/更新了哪些 slot）、created time
  （[官方文档](https://docs.memobase.io/features/event/event)）。
- 默认会在处理完后**删除 blob**：「apart from the relevant memory, your data will not be stored with Memobase」；
  要保留需改 storage config
  （[官方 README](https://github.com/memodb-io/memobase)）。
- 工程：FastAPI + Postgres + Redis，支持 caching / auth / telemetry，完全 Docker 化；官方称在线延迟 <100ms、
  单次处理固定 3 次 LLM 调用、token 成本降约 40–50%（这些是厂商口径）
  （[官方 README](https://github.com/memodb-io/memobase)）。

**判断**：Memobase 的「profile + event + buffer flush」适合**用户画像型**记忆，不适合角色知识边界；
它默认删 blob 的设计提醒我们：**如果不保留原始事件，派生记忆就不可重建**。

### 4.9 Supermemory：把「documents」与「memories」明确分开

- Supermemory 明确区分 **Documents**（静态知识，RAG，不随用户变化）与 **Memories**（从对话/文档中抽取的、
  绑定用户的、随时间演化的事实）；官方说「Memory is not RAG」
  （[官方文档](https://supermemory.ai/docs/concepts/memory-vs-rag)）。
- 能力：自动抽取事实、维护 user profile（static + dynamic）、处理知识更新 / 矛盾 / 过期遗忘、hybrid search
  （RAG + memory）、connectors、multimodal extractors
  （[官方 README](https://raw.githubusercontent.com/supermemoryai/supermemory/main/README.md)）。
- 存储：local 版首次启动会设置 embedded Supermemory graph engine、本地 embedding 和凭证；
  数据都在 `~/.supermemory`，可备份或迁移；云版另有文档 / RAG 与 connector 层
  （[官方 README](https://raw.githubusercontent.com/supermemoryai/supermemory/main/README.md)）。
- 厂商 benchmark：LongMemEval 95% Recall@15、99.4% context reduction、~50ms profiles、#1 on LongMemEval / LoCoMo /
  ConvoMem；这些是官方自报，未独立复现
  （[官方 README](https://raw.githubusercontent.com/supermemoryai/supermemory/main/README.md)）。

**判断**：Supermemory 的「documents vs memories vs profiles」三分法很适合产品解释；但它的默认场景是个人助手 /
企业知识，不是游戏世界。

### 4.10 Motorhead：已弃用，不要采用

Motorhead README 顶部直接标 **DEPRECATED / support no longer maintained**；它提供 3 个简单 API：
`GET /sessions/:id/memory`（返回窗口内消息 + 增量 summary）、`POST`（存消息）、`DELETE`；
窗口满后 summarize 一半；可选 Redis VSS 检索
（[官方 README](https://raw.githubusercontent.com/getmetal/motorhead/main/README.md)）。
它只适合作为「极简 session memory」的历史参考，不应进入新系统。

---

## 5. 横向对比矩阵

### 5.1 产品 / 引擎：记忆、世界状态、并发、可见性

| 对象 | 记忆分层 | 世界状态权威 | 分支 / 回溯 | 多角色并发 | 私有可见性 | 写入时机 | 公开评测 |
|---|---|---|---|---|---|---|---|
| **AI Dungeon** | Auto Summary + Memory Bank + Story Cards + Plot Essentials | 无 game state；故事文本即世界 | 编辑 / undo；不回算旧摘要 | 多人共享输入；未说明并发控制 | Story Card spoiler 不私有 | 每 6 / 15 动作生成 | 无 |
| **Character.AI** | Pins + 400 字 Chat Memories + Auto Memories | 无 | 未公开 | 单用户单角色 | 用户侧控制，未公开角色隔离 | 自动 + 手动 pin | 无 |
| **Replika** | 可见 Memory tab + 深层模式 | 无 | 无 | 单用户单角色 | 单用户私有 | 自动 + 手动 | 无 |
| **SillyTavern** | Card + World Info + Summarize + Data Bank | 无；本地 chat 文件 | 分支聊天；群聊共享历史 | reply order；单活跃发言者 | 群聊历史共享 | 摘要 / RAG 按配置 | 无 |
| **Chub AI** | Lorebook + Chat Memory + Stage state | chat tree + message state | **完整 chat tree** | 以单聊天为中心；未见多写者并发文档 | lorebook 注入共享 prompt | 作者/扩展写入 | 无 |
| **Inworld** | session facts + summary；跨会话客户端存 | 无；session 关闭即丢 | 无 | 每 session 独立 | 未公开 | 每 N 轮 + 客户端 re-inject | 无 |
| **Convai** | buffer + MemoryRecord + Knowledge Bank | 无 | 无 | 房间一次一条消息 | **user×character 隔离；不跨角色** | 会话末批处理 | 无 |
| **NVIDIA ACE** | Agent history + RAG | 无；应用负责 | 无 | MultiAgent 样例共享 SLM | 应用控制 | 应用驱动 | 无 |
| **Charisma.ai** | 5 类结构化 memory + Tags | 故事图 + Gates | 作者编排的分支 | 未公开 | gate 条件；未见按角色 | 交互点写入 | 无 |
| **jubensha-ai** | Identity / Memory / PhaseDirector | 无事件溯源 | 无 | 单进程轮流发言 | **known_evidence 私有 + 显式 reveal** | 实时（内存） | 无 |
| **WenJing（现状）** | Identity / working / personal / rejected / world facts / goals | **事件流** | **branch_path + active_events** | 每 session 串行 + CAS | **plot_entries_for(viewer) + world_facts** | 命令内追加 + 快照 | 事件流可回放 |

### 5.2 记忆服务：能否当权威、能否重建、是否适合游戏

| 服务 | 权威存储 | 时间 / 因果表达 | 语义召回 | 可见性 / 租户 | 可重建 | 适合当 WenJing 世界权威？ |
|---|---|---|---|---|---|---|
| **Letta MemFS** | git 文件 | 中（commit 历史） | 默认无；可选 | 每 agent repo；shared memory | 强（git） | 否；适合 agent 知识库 |
| **Mem0** | SQL facts | 中（temporal metadata） | 高（多信号） | user/agent/run filter | 中（history；索引可重建） | 否；适合派生用户事实 |
| **Zep/Graphiti** | 图数据库 | **高（bi-temporal）** | 高（hybrid + graph） | 参考 server 无鉴权；Zep 有治理 / 访问控制 | 高（episode 溯源） | 否；适合派生语义索引 |
| **LangMem** | 取决于 store | 中 | 取决于 store | namespace | 取决于 store | 否；它是库，不是权威 |
| **Cognee** | 图 + 向量 + 关系 | 中 | 高 | 默认 multi-tenant | 中（源数据 + 图） | 否；适合经验/知识 |
| **Redis Agent Memory** | Redis | 中 | 高 | 托管 | 中 | 否；适合热/冷两层 |
| **Memobase** | Postgres + Redis | 中（event timeline） | 中 | 多用户 | **弱（默认删 blob）** | 否；适合用户画像 |
| **Supermemory** | 图 + 向量 + 文档 | 中（temporal/矛盾） | 高 | container tags | 中 | 否；适合个人助手 |
| **Motorhead** | Redis | 低 | 低 | 单 session | 弱 | 否；已弃用 |

读法：**「并发正确性 / 可回溯」与「语义召回」是两条轴。**
事件溯源在正确性 / 可回溯上最优，召回需要外挂；知识图谱在时间表达与召回上最优，但正确性、可见性、游戏分支要自己补。
Zep 的治理 / 访问控制能力（RBAC、ABAC、审计、内容策略）见其官方文档索引
（[llms.txt](https://help.getzep.com/v4/llms.txt)）；Graphiti 的开源参考 server 则明确没有这些。

---

## 6. 对 WenJing 的落地建议

### 6.1 保持不变（现状是对的）

- **事件是权威**：世界状态、目标、资产、角色记忆都从 `EventStore.active_events()` / `branch_path()` 派生；
  `RuntimeAssets.rebuild(store)` 不落库，快照只是缓存。
- **每 session 串行 + 行锁 + CAS**：`services/session_store.py` 的 `with_for_update` 与 version 检查，
  等价于 per-session actor；单 worker 是当前正确性的一部分。
- **有界读取窗口**：`CharacterMemory.trim()` 只保留最近 `CHARACTER_MEMORY_LIMIT`（10）条，
  事件流才是全量权威（`backend/app/domain/agents/character.py`）。
- **按 viewer 投影**：`plot_entries_for(viewer)` 是多 agent「共享事件、按可见性投影」的正确抽象
  （`backend/app/domain/game/game_runtime.py:909`）；`WorldView` 的 docstring 明确说 viewer 裁剪是机制层知识边界，
  不是隐私装饰（`backend/app/domain/agents/tools.py:22`）。

### 6.2 建议补的第一层：把「角色记忆」拆成可重建的事实表

不要替换 `CharacterMemory`，而是在事件流之上加一张**派生表**（可删除、可重建）：

```text
memory_fact(
  id,
  session_id,
  subject_character,        -- 记忆属于谁
  viewer_scope,             -- public / character:<name> / player
  kind,                     -- fact / event / relationship / goal / preference
  text,
  source_event_seq,         -- 溯源：哪条事件产生的
  valid_from_seq,
  valid_to_seq,             -- 失效不删除；回溯换分支时按 active 事件重算
  importance,               -- 可选：用于检索排序
  last_used_seq,            -- 可选：recency / reinforcement
  embedding                 -- 可选：pgvector；可为 NULL
)
```

写入规则：

- **只由事件流异步重建**；查询走「当前有效 + 该 viewer 可见」；
- **不反向写 EventStore**；事实表删了不影响状态；
- **失效用 `valid_to_seq`**，不物理删除；这借的是 Zep/Graphiti 的「旧事实失效而不删除」
  （[官方文档](https://help.getzep.com/v4/facts.md)）；
- **`viewer_scope` 必须在写入时就带上**，不要等到 prompt 拼装时才过滤；这是 WenJing 比多数产品强的地方。

如果只想做最小版本：先做 `kind = fact / event / goal` 三类 + `viewer_scope`，不做 embedding。

### 6.3 建议补的第二层：上下文预算器

把 prompt 拼装从「需要什么塞什么」改成显式预算，参考 AI Dungeon 的 Required / Dynamic 分桶
（[官方说明](https://help.aidungeon.com/faq/what-goes-into-the-context-sent-to-the-ai)）：

| 桶 | WenJing 内容 | 规则 |
|---|---|---|
| **Required** | 角色 identity / 稳定 system prompt；当前 stage + 目标；当前矛盾 / direction；最后一条玩家动作 | 尽量全量；超过总预算 70% 时按固定优先级裁剪，**永远不裁 identity / 当前目标 / 最后动作** |
| **Dynamic: 叙事** | `plot_entries_for(viewer)` 最近 N 条；`personal_log` 最近 N 条；`world_facts` | 按「最近 + 重要」排序，硬上限 |
| **Dynamic: 世界信息** | 剧本大纲 / 角色名册 / 场景信息 | 只在角色参与的场景可见；按 token 预算裁剪 |
| **Dynamic: 检索** | 派生事实表的 top-K（可选 embedding / BM25） | 只在有剩余预算时注入；可完全关闭，不影响状态 |

建议同时记录每次拼装的 token 数（按桶），作为测试断言；这比只看「回答像不像」更能发现回归。

### 6.4 建议补的第三层：热路径只追加，后台整理

把「记忆整理」从命令请求里拿出去：

- 命令提交后，事件流追加完成即返回；整理任务由 outbox / 后台 worker 消费 `event_seq`；
- 后台任务做：摘要、事实抽取、冲突失效、importance / last_used 更新、embedding 重算；
- 任务必须**幂等**（按 `source_event_seq` / `version` 去重），失败可重试；
- **整理永远不能改写历史事件**；只能写派生表 / 快照缓存；
- 参考实现：Convai 会话末批处理（[官方文档](https://docs.convai.com/api-docs/plugins-and-integrations/convai-unity-sdk/features/long-term-memory/how-long-term-memory-works.md)）、
  Memobase buffer flush（[官方 README](https://github.com/memodb-io/memobase)）、
  Letta dreaming（[官方文档](https://docs.letta.com/configuration/memory)）、
  LangMem background（[官方文档](https://langchain-ai.github.io/langmem/concepts/conceptual_guide/)）、
  Redis Agent Memory 后台提升（[官方 README](https://raw.githubusercontent.com/redis/agent-memory-server/main/README.md)）。

### 6.5 可见性：保留「唯一读取口 + 显式公开动作」

- 继续把 `plot_entries_for(viewer)` / `view_plot_log` / `view_world_facts` 作为角色读取叙事的**唯一口**；
  不要让 `plot_context` / `current_direction` 这类 write-only 全局广播直接暴露给角色（AGENTS.md 已有此约定）。
- 借 jubensha-ai 的「公开是显式动作」：如果未来要做「角色主动揭露秘密 / 证据」，
  应该是一个命令 / 工具动作并写入事件，而不是让模型在叙述里顺嘴说出
  （`docs/research/jubensha-ai.md`）。
- 借 Convai 的 per-user-per-character 隔离：如果未来有多用户 / 多角色，记忆 key 至少是
  `session_id + character + viewer`，不要只按 `character` 存。

### 6.6 并发与多副本

- 继续坚持「单 worker + 每 session 串行 + 行锁 / CAS」；
- 后台整理任务与命令路径共享同一 session 版本时，必须走同一 CAS 或只写 append-only 派生表；
- 要扩多副本，第一选择是 **session 粘性路由**，第二选择是把互斥下沉到 PG（行锁 / advisory lock）；
- **不要**让两个副本同时持有一个 session 的运行时对象；也不要把 WS outbox / 在途生成留在进程内
  （AGENTS.md 的生产部署约束）。

### 6.7 评测：不要只追 LoCoMo

外部服务的 benchmark（Mem0 / Supermemory / Cognee / Redis）衡量的是「跨会话事实召回」，不是游戏一致性。
WenJing 更应该自建三类测试：

1. **回放一致性**：同一事件流 → 同一 viewer 看到同一叙事摘要；换分支后目标 / 资产 / 记忆自动回退。
2. **派生索引可丢弃**：删除 memory_fact / embedding 后，重放事件能重建；游戏状态不变。
3. **可见性回归**：角色 A 的 `personal_log` / 私密 `world_facts` 不出现在角色 B 的 tool 输出里；
   不在场的角色看不到该场景的 `plot_entries_for`。

### 6.8 什么时候才考虑外部记忆服务

只有在「**纯对话型陪伴 / 用户画像**」且「不需要游戏世界状态、分支、角色知识边界」时，才考虑
Mem0 / Zep / Supermemory / Memobase。即使采用，也应该是：

- 由事件流 / outbox **单向喂数据**；
- 只作为**可丢弃的派生索引**；
- 不承载权威状态、不承载可见性规则；
- 先验证「删掉它不影响游戏状态」，再谈接入。

---

## 7. 参考来源

> 以下仅列**本轮实际抓取成功**的页面；失败 / 未核验的 URL 见 §8。

### 本仓库

- `AGENTS.md`
- `docs/research/agent-memory-architecture-survey.md`
- `docs/research/jubensha-ai.md`
- `backend/app/domain/agents/character.py`
- `backend/app/domain/agents/tools.py`
- `backend/app/domain/game/game_runtime.py`
- `backend/app/services/session_store.py`

### AI 剧本杀 / 互动叙事

- AI Dungeon 官网：<https://aidungeon.com/>
- AI Dungeon FAQ 索引：<https://help.aidungeon.com/faq>
- AI Dungeon Memory System：<https://help.aidungeon.com/faq/the-memory-system>
- AI Dungeon context 组成：<https://help.aidungeon.com/faq/what-goes-into-the-context-sent-to-the-ai>
- AI Dungeon Story Cards：<https://help.aidungeon.com/faq/story-cards>
- AI Dungeon Plot Essentials：<https://help.aidungeon.com/faq/plot-essentials>
- AI Dungeon 多人模式：<https://help.aidungeon.com/faq/do-you-support-multiplayer>
- Character.AI 帮助中心搜索（Zendesk API）：<https://support.character.ai/api/v2/help_center/articles/search.json?query=memory>
- Character.AI Pinned Memories：<https://support.character.ai/hc/en-us/articles/24327914463003-Pinned-Memories>
- Character.AI Auto Memories（2025-03 社区更新）：<https://support.character.ai/hc/en-us/articles/35409588582683-Community-Update-March-2025>
- Character.AI 订阅与 pins 对比：<https://support.character.ai/hc/en-us/articles/56173313531675-About-c-ai-lite>
- Character.AI 角色创作指南（memory 工具说明）：<https://support.character.ai/hc/en-us/articles/50609303987099-6-Refining-and-Testing-your-Character>
- Replika 官网：<https://replika.com/>
- Replika 帮助中心搜索（Zendesk API）：<https://help.replika.com/api/v2/help_center/articles/search.json?query=memory>
- Replika 记忆机制：<https://help.replika.com/hc/en-us/articles/37208679176077-How-does-Replika-s-memory-work>
- Replika 记得什么：<https://help.replika.com/hc/en-us/articles/360000874712-What-does-my-Replika-remember-about-me>
- Replika 聊天记录保留期：<https://help.replika.com/hc/en-us/articles/4411154990605-Is-the-chat-history-infinite>
- Replika Ultra：<https://help.replika.com/hc/en-us/articles/37292892831885-What-is-Replika-Ultra>
- SillyTavern 文档首页：<https://docs.sillytavern.app/>
- SillyTavern Data Bank (RAG)：<https://docs.sillytavern.app/usage/core-concepts/data-bank/>
- SillyTavern Summarize：<https://docs.sillytavern.app/extensions/summarize/>
- SillyTavern Group Chats：<https://docs.sillytavern.app/usage/core-concepts/groupchats/>
- SillyTavern GitHub：<https://github.com/SillyTavern/SillyTavern>
- Chub AI 文档首页：<https://docs.chub.ai/>
- Chub AI Lorebooks：<https://docs.chub.ai/docs/advanced-setups/lorebooks.md>
- Chub AI Stage State：<https://docs.chub.ai/docs/stages/developing-a-stage/state.md>
- Chub AI Just Chatting（chat tree）：<https://docs.chub.ai/docs/the-basics/just-chatting.md>
- RisuAI README：<https://raw.githubusercontent.com/kwaroran/RisuAI/main/README.md>
- 筑梦岛官网：<https://www.zhumengdao.com/>
- jubensha-ai GitHub：<https://github.com/JianWang97/jubensha-ai>

### NPC / 角色记忆引擎

- Inworld 文档首页：<https://docs.inworld.ai/>
- Inworld llms.txt：<https://docs.inworld.ai/llms.txt>
- Inworld Character Studio 退役说明：<https://docs.inworld.ai/character-studio-deprecation.md>
- Inworld Realtime long-term memory：<https://docs.inworld.ai/realtime/usage/long-term-memory.md>
- Convai 文档首页：<https://docs.convai.com/>
- Convai llms.txt：<https://docs.convai.com/api-docs/llms.txt>
- Convai Memory：<https://docs.convai.com/api-docs/convai-playground/character-customization/memory.md>
- Convai Knowledge Bank：<https://docs.convai.com/api-docs/convai-playground/character-customization/knowledge-bank.md>
- Convai 多角色回合：<https://docs.convai.com/api-docs/no-code-experiences/chat-experiences/running-the-room/how-a-turn-works.md>
- Convai 长期记忆入口：<https://docs.convai.com/api-docs/plugins-and-integrations/convai-unity-sdk/features/long-term-memory.md>
- Convai 长期记忆机制：<https://docs.convai.com/api-docs/plugins-and-integrations/convai-unity-sdk/features/long-term-memory/how-long-term-memory-works.md>
- NVIDIA ACE：<https://developer.nvidia.com/ace>
- NVIDIA Game Agent SDK：<https://github.com/NVIDIA/game-agent-sdk>
- Charisma 文档首页：<https://docs.charisma.ai/>
- Charisma Memories and Gates：<https://docs.charisma.ai/memories-gates>
- Scenario API 文档：<https://docs.scenario.com/>

### 通用记忆服务

- Letta README：<https://raw.githubusercontent.com/letta-ai/letta/main/README.md>
- Letta 文档首页：<https://docs.letta.com/>
- Letta Memory & dreaming：<https://docs.letta.com/configuration/memory>
- Letta MemFS：<https://docs.letta.com/concepts/memfs>
- Mem0 README：<https://raw.githubusercontent.com/mem0ai/mem0/main/README.md>
- Mem0 llms.txt：<https://docs.mem0.ai/llms.txt>
- Mem0 How it works：<https://docs.mem0.ai/core-concepts/how-it-works>
- LangMem README：<https://raw.githubusercontent.com/langchain-ai/langmem/main/README.md>
- LangMem Core Concepts：<https://langchain-ai.github.io/langmem/concepts/conceptual_guide/>
- Cognee README：<https://raw.githubusercontent.com/topoteretes/cognee/main/README.md>
- Redis Agent Memory README：<https://raw.githubusercontent.com/redis/agent-memory-server/main/README.md>
- Motorhead README：<https://raw.githubusercontent.com/getmetal/motorhead/main/README.md>
- Graphiti README：<https://raw.githubusercontent.com/getzep/graphiti/main/README.md>
- Zep llms.txt：<https://help.getzep.com/llms.txt>
- Zep v4 llms.txt：<https://help.getzep.com/v4/llms.txt>
- Zep v4 Concepts：<https://help.getzep.com/v4/concepts.md>
- Zep v4 Facts：<https://help.getzep.com/v4/facts.md>
- Memobase GitHub：<https://github.com/memodb-io/memobase>
- Memobase Profile：<https://docs.memobase.io/features/profile/profile>
- Memobase Event：<https://docs.memobase.io/features/event/event>
- Supermemory README：<https://raw.githubusercontent.com/supermemoryai/supermemory/main/README.md>
- Supermemory Memory vs RAG：<https://supermemory.ai/docs/concepts/memory-vs-rag>

---

## 8. 调研局限

- **Exa 不可用**：`web_search_exa` / `web_fetch_exa` / `agent_run` 全部 402，本轮无法做关键词广搜与结果排序；
  可能漏掉 2026 年下半年新出的产品 / 国内闭源服务。
- **抓取失败 / 未核验的对象**：
  - 百变大侦探（`bcdzt.com`、`bcdzt.cn`）、我是谜（`woshimi.com`、`woshimi.cn`）、谜案馆（`mianguan.com`）：
    transport error；未找到可访问的官方 AI 能力文档。
  - 戏精大侦探：未找到可访问的官方页面。
  - Hidden Door（`hiddendoor.co`、`hiddendoor.com`、blog）：transport error 或空响应；未核验。
  - Talkie（`talkie-ai.com`、`/en`、帮助中心）：403；未核验。
  - 星野（`xingyeai.com`）：transport error；MiniMax 官网（<https://www.minimaxi.com/>）本轮抓到的内容没有星野的记忆架构说明。
  - 猫箱（`maoxiang.doubao.com`）、Glow（`glow.cn`）、冒泡鸭（`maopaoya.com`）：transport error；未核验。
  - Janitor AI（`janitorai.com`、`docs.janitorai.com`）：403 / transport error；未核验。
  - Character.AI 的文章 HTML 页对抓取返回 403；本轮通过官方 Zendesk API 取到全文，URL 仍列官方 `html_url`。
  - SillyTavern World Info 页面、Chat Vectorization 页面：transport error；本轮用 Data Bank / Summarize / Group Chats 页面替代。
  - RisuAI wiki：transport error；只用 README，不写内部实现。
  - Charisma Memory Nodes 页面：transport error；只用 Memories and Gates 页面。
  - Letta 旧版 docs 的 `llms.txt`、Memobase 的 `llms.txt`：transport error；改用具体页面。
- **未做源码级核验**：除本仓库自身与 `jubensha-ai` 的本仓库既有分析外，本轮产品均只读官方文档 / README，
  未 clone 源码逐行核对；因此「实现细节」只写到官方愿意公开的粒度。
- **厂商 benchmark 不可直接横比**：Mem0 / Supermemory / Cognee / Redis 的分数均为厂商自报，模型、数据划分、
  检索配置、版本不同；Redis README 自己就强调「不是永恒排名」。本报告只把它们当作「能力方向」的证据，
  不作为选型排名。
- **产品口径会变化**：Character.AI 的 Pinned Memories 从 2024 年的「每 chat 5 条」到 2026 年的「15 / 30 pins」，
  说明官方帮助中心本身也在演进；Inworld 的 Character Studio 已退役、Motorhead 已弃用、Letta V1 API 已归档。
  引用具体数字时务必看页面日期。
- **「多角色并发」证据不足**：本轮没有找到任何官方文档描述「多写者共享世界」的锁 / 版本 / 冲突解决；
  本报告的并发判断主要来自「官方文档没有说」与产品级回合约束，不应理解为厂商内部一定没有实现。
- **未覆盖**：语音 / 实时打断 / TTS 与记忆的交互、模型侧长上下文能力、成本与限流细节；这些与本轮主题正交，
  可另开调研。
