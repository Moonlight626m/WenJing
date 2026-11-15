# 美术 Agent 团队与分层立绘：案例、机制与重组方案（2026-11-15）

> **性质**：带日期的调研快照，非规格，不追改。结论可能随模型与价格变化而过期。
> **调研日期**：2026-11-15。
> **范围**：文境配图链路（`design_assets` 离线批量 + `SceneAssetScheduler` 运行期补图 +
> Ark Seedream 5.0 flash）的三块短板——运行时出图的工程做法、分层立绘与透明背景、
> 美术 agent 的分工与风格护栏。
> **与已有文档的关系**：`docs/design/image-generation-quality.md` 是现行设计草案；
> `docs/research/realtime-ai-art-in-games-survey.md` 是第一轮广度调研（案例清单 +
> 模型选型 + 改进清单），本文是第二轮**逐项深挖**，不重复其结论，只补机制细节、
> 关键数字与可落地方案。
> **分工说明**：第 1 章来自「运行时案例」组，第 2–9 章来自「分层立绘与透明背景」组，
> 第 10–15 章来自「agent 团队与风格护栏」组；各组参考来源与未核实项见对应章节末。

---

## 0. 总结论（先看这段）

1. **运行时出图的真实工程做法是「库存 + 检索」，不是「现场生成」**：
   Jeff Schomay 的 20–30 秒链路靠缓存池抹平（基线 20 条、一次补 10 条、单锁、读即删）；
   AWS Agentic Arcade 只有概念 / 标题 / box art 实时生成，角色与环境资产全部离线
   ComfyUI 预生成 + S3 Vectors 检索；Ubisoft 用 3 万+ 资产、每资产 6 视角嵌入，
   检索 < 1 秒。详见第 1 章。
2. **文境该抄的是「补货策略 + 检索优先」**：按叙事前瞻预热库存（文境有事件流，
   命中率高于盲补）；把 `image_search` 从降级方案升格为第一优先候选，检索不到再生成。
3. **分层立绘不用自研**：Ren'Py `layeredimage` 的语义（group 槽位 / attribute 变体 /
   互斥组 / `always` / `when` / 每层 `offset` 与 `alpha` / 声明顺序即绘制顺序）就是事实
   标准，前端照抄数据模型即可，代价为零。详见第 3 章。
4. **透明背景有三条路，推荐顺序明确**：① Seedream 5.0 **图层拆分**（同 provider，
   一次调用出「1 张底图 + 最多 16 个带透明通道的图层」）；② **BiRefNet** 生成后抠图
   （MIT，Cloudflare 实测 general 变体 IoU 0.87 / Dice 0.92，DIS5K 上远超 U2-Net）；
   ③ **Qwen-Image-Layered**（Apache 2.0，fal $0.05/张，整图拆 3–8 层）作第二意见。
   **LayerDiffuse 不推荐**（仓库最后推送 2024-06-16，已被超越）。详见第 4 章。
5. **表情差分走「编辑式续画」**：只重画 face 图层再与 base 合成，而不是整张重生成。
   Seedream 的坐标 / 框选 / 箭头交互编辑与 Qwen-Image-Edit-2511 都支持。详见第 7 章。
6. **风格护栏要量化，不能停在形容词**：配色分布（主/辅/点缀比例）、材质倾向与磨损
   分布（占比 + 均匀还是聚集在边缘）、正负向约束词 + **版本号**（版本号要同时进
   prompt、rubric 与去重键，换版本即换产出）。腾讯访谈口径称一致率从 40% 提到 90%+，
   但无指标定义，只能当方向参考。详见第 10 章。
7. **agent 团队收敛为四个角色**：Casting（LLM，选角：剧本 → 结构化需求清单）、
   Painter（LLM，画师：只吃「角色卡 / 场景 / 镜头」三段）、Reviewer（VLM，只出 gate
   结果 + 分级分 + 失败标签）、Harness（非 LLM，管候选张数与重绘轮次）。依据是腾讯
   访谈的「Agent 负责做事，Harness 负责让做事可控」。详见第 14 章。
8. **评审要拆 gate 与 graded**：先过硬门槛（性别年龄、关键物件、安全），再按 rubric
   分级；CLIP / DINO / DreamSim 做廉价粗筛，VLM 只在粗筛失败或终稿时调用。
   详见第 13 章。
9. **反方观点值得记住**：Summer Engine 认为 AI 的优势在「写生成器」而非「当生成器」；
   arXiv 2607.00527 也把延迟、边际成本、一致性漂移列为运行时生成的硬伤。文境的正确
   方向是「离线尽量确定、运行时尽量检索、生成兜底」。详见第 1.4–1.5 节。
10. **不建议**：采购像素风 sprite 平台（Layer.ai / AutoSprite / Spritesheets.ai 面向
    动画序列帧，文境要静态立绘 + 差分）、LoRA / 自托管推理、照搬 AWS 的 supervisor
    架构（文境单 worker，`SceneAssetScheduler` 已够）。详见第 7.4、14.6 节。

---

## 1. 运行时出图的真实工程案例

### 1.1 Jeff Schomay：无限迷宫游戏的实时资产生成管线

**它是什么**
独立开发者 Jeff Schomay 为实验游戏 *Lost*（itch.io）做的"无限探索"后端：玩家每走一步，
后端现场生成一段场景描述和一张配图。2023 年 AI Engineer Summit 演讲，代码开源。

**怎么做（架构细节）**
链路是严格的三段：

1. **场景 JSON**：先用 GPT-3.5-turbo + 详细 prompt 产出符合固定 JSON 结构的场景；
   再挑 50 条人工筛选的样例做 **fine-tune**，并把 prompt 简化成不含结构说明的版本
   （训练后模型自己会守格式）。
2. **校验**：`validate_scene()` 逐字段检查 `title` / `on_discover` / `on_return`、
   `stats` 只能是 `vigor` / `courage`、`diff` 必须是整数——不合格直接丢弃。
3. **配图**：把 `title` + `description` 拼成 `forest scene - <title>: <desc>`，
   交给 **Leonardo.Ai 上自己训练的模型**（512×512、guidance 11、promptMagic v2、
   highContrast）；先 `sleep(10)` 再每 10 秒轮询一次，最多 10 次。

**缓存池是全文最有价值的部分**，实现只有一个函数：

- 每次客户端取场景（`/scene`）时，**另起一个后台线程**调 `ensure_enough_scenes()`；
- 加锁（`threading.Lock`）后数一遍库里的场景数：**低于 20 就一次性补 10 条**；
- 取场景 = `SELECT ... ORDER BY id DESC LIMIT 1` 然后 **DELETE**（读即删，队列语义）；
- 生成用 `ThreadPoolExecutor(max_workers=5)` 并发，每个任务完成即落库；
- 作者自己在 docstring 里写明局限：*"can run dry if concurrency is greater than
  the minimum threshold"*——并发超过基线库存就会断供。

**关键数字**

| 项 | 值 | 来源 |
|---|---|---|
| 整条链路延迟 | **20–30 秒** | 作者原文，明确说"请求新场景时延迟太大" |
| 缓存基线 / 单次补货 | **20 条 / 10 条** | `app.py::ensure_enough_scenes` |
| 生成并发 | 5 个线程 | `gen_openai.py` |
| 图像分辨率 | 512×512 | `gen_leonardo.py`；作者把超分列为后续改进 |
| 单次生成上限 | 30 条（`/gen/<n>` 防滥用） | `app.py::gen_n` |
| 图像托管 | 直接存 Leonardo CDN URL | 样例 scene 的 `image` 字段即 `cdn.leonardo.ai/...` |

**一手来源**
- 正文：https://blog.jeffschomay.com/lost-in-an-infinite-maze-building-a-real-time-generative-ai-game-assets-pipeline
- 后端源码（缓存池实现）：https://github.com/jschomay/lost-game-ai-asset-server （Python，**无 LICENSE 文件**）
- 客户端：https://github.com/jschomay/Lost
- 游戏：https://enegames.itch.io/lost

**对文境的启示**
1. **20–30 秒的延迟用"库存"抹平，而不是用更快的模型**——这条经验与文境现状完全同构
   （渐变占位 + 后台补图）。差别在于他是"盲补"（不知道玩家下一步去哪），文境有事件流，
   可以按叙事前瞻补，命中率天然更高。
2. **"读即删"的队列语义不适合文境**：文境的同一场景图可能被多次读取（回放、回溯、多端），
   应当用"查得到就复用"的缓存语义，而不是消费即销毁。
3. **他的断供条件值得抄成指标**：库存 < 并发时断供。文境应显式定义"在途任务数 / 待补场景数"
   的关系，而不是等玩家看到占位图才发现补不过来。
4. 反面教材：把 provider 的 CDN URL 直接写进业务数据，24 小时后失效（Ark 的 URL 同样是
   24 小时有效期，文境用 `b64_json` 转存是对的）。

---

### 1.2 AWS「Agentic Arcade」：四 Agent 美术团队 + 异步预生成

**它是什么**
AWS re:Invent 2025 的互动 demo：参会者在几分钟内做出一个可玩的浏览器游戏。四个 AI agent
对应游戏工作室的四个岗位，资产大部分**离线预生成**，运行时只做检索。

**怎么做（架构细节）**

*Agent 分工*（supervisor-worker 模式）：

| Agent | 职责 |
|---|---|
| Director | 定品类、主题、目标，产出整体创意 |
| Artist | **监督 box art 生成**、用向量嵌入**检索角色资产包**、配色与音效选择 |
| Developer | 选玩法机制、生成配置文件 |
| Playtester | 试玩并给改进建议 |

调度：**DynamoDB 当任务队列 + Lambda 派发**，`Bedrock AgentCore` 编排、`Strands Agents`
保证结构化输出；agent 在单次会话内保留短期记忆，四个站点之间传递上下文。

*资产生成与运行时的分离*（这是关键）：

- 离线：`ComfyUI` 工作流以 **JSON 配置**形式定义（模型、参数、后处理、输出规格），
  作为 **GPU 容器任务跑在 ECS** 上，模型放 **EFS** 加速冷启动，**SQS** 管队列；
  批量生成资产库 + 计算向量。
- 运行时：只有**游戏概念、标题、box art** 是真·实时生成；角色精灵、环境、音效
  全部走 **S3 Vectors 语义检索**（Titan 多模态嵌入），"结果在数秒内返回"。

*Agentic QC*：每个资产进库前过一轮多模态评审（`Nova Lite`），维度是
**可辨识度 / 题材契合 / 视觉一致性 / 内容安全**；不达标就**自动改 prompt 重生成**。

*架构分层*：React + CloudFront → API Gateway（HTTP + WebSocket）+ Lambda + Cognito →
  FastAPI on Fargate / ECS + SQS → DynamoDB（会话状态与任务队列）+ S3 + S3 Vectors + EFS →
  Bedrock（Claude / Nova / Stable Diffusion / Titan）+ Guardrails；前端用 Excalibur.js 渲染。

**关键数字**

| 项 | 值 | 来源 |
|---|---|---|
| 端到端体验 | "几分钟"做出可玩游戏 | 官方博客 |
| 运行时检索 | "数秒内" | 官方博客（无精确 p50/p99） |
| 实时生成范围 | 仅概念 / 标题 / box art | 官方博客 |
| QC 维度 | 4 项 | 官方博客 |
| 代码 | 示例仓库 MIT-0 | `aws-samples/sample-agentic-arcade-game-starter`（5★，2026-08 仍在更新） |

**一手来源**
- https://aws.amazon.com/blogs/gametech/ai-assisted-game-production-from-static-concept-to-interactive-prototype
- https://github.com/aws-samples/sample-agentic-arcade-game-starter

**对文境的启示**
1. **`ArtDirector` 草案的工业版几乎就是这个分工**：Artist 负责"选 / 生成 / 校验"，
   Director 定方向，QC 用多模态打分并回炉。文境的 `VisionReviewAgent` 已经是 QC，
   缺的是"Artist 的检索权"——现在只有生成，没有"从已有资产里挑"。
2. **"能预生成的都预生成，运行时只做检索"** 是他们对延迟的唯一解。文境可以照此切一刀：
   角色头像 / 立绘（跨场景复用）预生成，只有"新场景空镜"按需生成。
3. **ComfyUI 工作流即 JSON 配置** 的思路值得注意：它把"生成配方"变成可版本控制、可测试的
   数据，而不是散落在代码里的 prompt 拼接。文境的 `build_generation_prompt` 目前是代码，
   若要做 A/B，可以考虑把配方外置成版本化配置。
4. **QC 与生成解耦**：评审是"进库门槛"，不是"生成流程的一步"，所以失败可以无限重试而不阻塞
   上游。文境把它做成 `SceneDesigner` 内部循环，耦合更紧——好处是简单，坏处是重试预算
   与生图预算绑死。

---

### 1.3 Ubisoft「From Brief to Scene」：30k 资产、1 秒检索、分钟级装配

**它是什么**
Ubisoft 在 DigiPro / SIGGRAPH 2026 的工程报告：在既有 USD 微服务基础设施之上加一层
"智能层"，把会议记录和创意简报直接变成带 concept 预览图的资产选角表，再自动摆场景。

**怎么做（架构细节）**
三阶段，每一段都有明确的技术选型：

1. **简报分析**：`N8N`（工作流自动化平台）+ `ComfyUI` 生图管线，把**会议转录 / 创意简报**
   转成结构化 **asset casting list**，并附 concept previz 图——"几分钟"完成。
2. **资产发现**：`YOLO-World`（开放词表检测）负责"图里有什么"，`CLIP` 做语义检索，
   在 **3 万+ 生产索引 USD 资产**里找匹配项；每个资产在**六个视角**上都做了嵌入，
   检索"**不到 1 秒**"。
3. **场景装配**：一个通过 **MCP** 连到 Blender 的 AI agent，用自然语言把检索到的资产
   摆进场景。

定位很克制：主要面向**快速原型和占位资产**，不是终稿。

**关键数字**

| 项 | 值 |
|---|---|
| 资产库规模 | **30,000+** 生产索引 USD 资产 |
| 每资产嵌入 | **6 个视角** |
| 检索延迟 | **< 1 秒** |
| 简报 → 选角表 + previz | **分钟级** |
| 整体收益 | 前期资产工作 **天 → 分钟** |

**一手来源**
- DigiPro 议程页（摘要原文）：https://digiproconf.org/program/program-4
- ACM DL 扩展摘要：https://dl.acm.org/doi/full/10.1145/3819990.3820033
  （**抓取失败，本文数字全部来自 DigiPro 公开摘要**；全文结论未核实）
- 前作：DigiPro 2022 的 USD 微服务基础设施

**对文境的启示**
1. **检索层的成本可以忽略，生成层才是瓶颈**：3 万资产 < 1 秒。文境的
   `image_search`（Openverse / Wikimedia）如果被当成"降级方案"，其实可以升格为
   **第一优先的候选来源**——先检索、检索不到再生成，成本曲线会好看很多。
2. **"每资产多视角嵌入"是给一致性用的**：单视角嵌入只能匹配"看起来像"，
   多视角才能匹配"是同一个东西"。文境若做角色卡，参考图也应覆盖多角度。
3. **定位克制值得学**：他们明说这是原型/占位，不是终稿。文境可以对内区分
   "课堂可用的图"与"教师审核后的终稿"，前者允许检索+占位，后者才走贵模型。
4. **MCP 接 DCC 工具**是一条独立的技术路线：让 agent 直接操作编辑器，而不是只产出文件。
   对文境（Web 前端）暂不适用，但如果将来做教师端可视化编辑，这是现成范式。

---

### 1.4 Summer Engine 的立场：AI 写生成器，而不是 AI 当生成器

**它是什么**
AI 原生引擎厂商 Summer Engine 的一篇立场文（2026），专门拆"AI 做程序化生成"到底指什么。

**核心论点**
把两件事分开：

- **AI 写生成器**（设计期）：你描述想要的世界，AI 写出程序化生成代码——噪声栈、房间拼接、
  植被规则。这段代码是确定性的，运行时**没有 AI 参与**。
- **AI 当生成器**（运行期）：游戏在跑的时候调模型现场发明任务、布局或纹理。

作者的论据是三个具体缺陷，不是笼统的"质量不行"：

1. **延迟可感知**——玩家能感觉到卡顿；
2. **每次会话都有边际成本**——不是一次性开发成本；
3. **一致性会漂移**——"一旦你需要两个东西匹配"就出问题。

再加一条工程上的：**可复现性**。确定性生成器"毫秒级、零边际成本、可离线、同种子同世界"；
运行时调模型则"同样的输入给不出同样的输出"。作者的原话很扎心：bug 报告
"seed 4471 的地牢有个到不了的房间"能修，"模型那次做了个怪东西"没法修。

**关键数字**
- 确定性生成器：**毫秒级**、**零边际成本**、可离线（作者定性描述，无 benchmark）。
- 文中的判断："已发布游戏里**极少**真·实时生成"——定性，无统计口径。

**一手来源**
- https://www.summerengine.com/blog/ai-procedural-generation-for-games
- **利益相关**：Summer Engine 本身卖 AI 原生引擎，其"AI 写生成器"路线与产品定位一致，
  引用时需打折。

**对文境的启示**
1. 这篇的价值是**给"运行时生成"划出诚实边界**：文境做的不是"实时渲染"，而是
   "异步补图 + 占位"，恰好落在作者认可的那一侧（不阻塞玩法、可降级）。
2. **"可复现性"是文境已经赢的地方**：事件流 + 去重键让同一场景的图可追溯、可回放。
   如果把配图做成"每次进场景重新生成"，就会丢掉这个优势。
3. **"AI 写生成器"对文境有一层隐喻**：剧本生成 workflow 是"设计期 AI"，运行期配图是
   "运行期 AI"——两者的成本模型和验收标准应该分开管，不要用同一套预算和评审。

---

### 1.5 arXiv 2607.00527《AI-Native Games: A Survey and Roadmap》

**它是什么**
2026 年的综述：给"AI 原生游戏"下可操作的定义，筛了 **53 款**公开可得的 AI 原生游戏/原型，
做双轴分类，并单列运行时经济性。

**定义（三段必要条件）**
1. **生成式 AI 必须存在**（不是传统寻路/有限状态机）；
2. **核心循环必须依赖它**（解释玩家动作、产出内容或后果、裁决语义规则、控制关键 NPC、
   演化世界状态）；
3. **不可被平凡替代**（换成一套人工资产或确定性机制，核心体验就塌了）。

判定是**反事实**的：抽掉 AI，玩法是否崩溃。所以"有 AI 生成美术但可选/可替换"不算 AI 原生。

**G/N 双轴**
- G 轴：玩家面对的游戏类型；
- N 轴：让生成式 AI 不可替代的主导机制。
语料集中在**语言类**（叙事冒险、认知互动、生成式叙事）；语义裁决、多 agent 仿真、
生成式建造、关系/陪伴类明显偏少。

**与图像生成直接相关的结论（§V-C）**
- 语料**压倒性是文本驱动**的，多模态仍是短板；
- 举出的图像相关例子：*1001 Nights*（玩家讲故事 + 生成视觉后果）、
  *AI: Art Impostor*（把 prompt-to-image 直接做成玩法：画、猜、骗、社交判断）、
  *Whispers from the Star*（实时语音）。

**运行时经济性（§V-E，最值得抄的一节）**
- **延迟是"推理成本变成可玩性问题"的地方**：输入 → 等推理 → 才有反馈的节奏一旦变长或
  不可预测，就从"玩"变成"等远程服务"。
- **不要每次交互都调大模型**：高频低风险行为交给小模型或传统 AI，大模型只留给
  语义不确定真正要紧的时刻。
- **缓存要把"临时生成"变成"持久游戏状态"**：举 *Infinite Craft* 为例——两个元素一旦
  合成过，结果就固定下来，后续直接复用。同理适用于规则裁决、生成实体、NPC 记忆、世界变更。
- 其他手段：蒸馏、量化本地推理、投机解码、多 agent 场景批处理。
- **商业模式**两条路：外部化推理成本（本地/端上，如 *Suck Up!*、*AI Roguelite*；
  或 BYOK 让玩家自己付 API 钱），或持续收费（订阅 / 点数 / 混合）。
  结论是 **token 计费还不是成熟模式，推理成本可能超过玩家付费意愿**。

**一手来源**
- 摘要：https://arxiv.org/abs/2607.00527
- 全文 HTML：https://arxiv.org/html/2607.00527v2 （本轮抓取，引用到 §III-A / §V-C / §V-E）

**对文境的启示**
1. **"把生成结果变成持久状态"正是文境的事件溯源**：`asset_ready` 事件一旦写入，
   图就固定了，后续回放/回溯读的是事件而不是重新生成。这条文境已经做对了，
   可以在设计文档里明确写成契约。
2. **"高频低风险用小模型、语义不确定才用大模型"** 可以直接映射到文境的槽位分级：
   空镜/背景用 flash，含人物的关键场面用 pro，评审只对含人物的图开。
3. **延迟要当设计约束而不是后端细节**：文境现在的"渐变占位 + 叙事不等图"就是这条原则的
   实现，值得在文档里点明出处，避免以后有人为了"图更完整"把它改成同步等待。
4. **多模态仍是短板**——文境已经有视觉评审，比语料里大多数项目靠前，但"评审维度"
   仍可扩（情节关键物件、与角色卡同一人）。

---

### 1.6 Hidden Door：paperdoll 的机制细节

**它是什么**
AI 叙事游戏，但美术 **100% 人工绘制**。角色不是生成出来的，而是用**手绘图层 + 标签 +
向量相似度**在运行时拼出来的。

**怎么做（架构细节）**

*图层结构*：
- 三层主干：**body / face / outfit**；
- 每层可含子层：face 层可以有基础脸型、眼鼻耳嘴、头发、胡须、眼镜、穿孔、疤痕；
- 帽子是"特殊混乱"——它同时和头发、耳朵、角色卡上边界交互。

*标签体系*（这是核心资产，不是图层文件）：
- 每块素材**人工打标签**，三类：时代/题材（`scifi`、`regency`、`modern`）、
  气质（`fancy`、`mysterious`、`punk`）、字面描述（`jewelry`、`scar`、`vampire`）。
- 标签既保证"该出现的出现"（维多利亚侦探配烟斗/猎鹿帽），也保证
  "不该出现的不出现"（没有僵尸的故事里不该有僵尸脸）。

*选择算法*：
- 创建角色时，系统已知：描述、故事角色、性格、世界观与修饰符（比如 "Zombies!" 模式），
  甚至"口袋里有什么"；
- 把词映射到多维向量，**算语义相似度**给每个候选资产打分；
- **从高分候选里带随机性挑选**——所以两个玩家故事里的"抱抱吸血鬼"会越来越不一样，
  且随着资产库增长差异越大。

*地点美术*：纯人工管线，原则是"戏剧舞台"——前景 / 中景 / 背景三层式构图；
需求是"小尺寸可读"（移动端）、"快速大量产出"、"地点是概念的锚点而非精细还原"；
参考 Mary Blair 与 Eyvind Earle。

**关键数字**
- 图层主干 3 层、子层类型"每种累积数十个选项"——定性，无精确资产总数（**未核实**）。
- 选择延迟、库规模：**未公开**。
- "预生成 + 语义匹配"的地点图策略来自 GamesBeat 采访（**二手**）；官方博客只描述人工管线，
  未披露预生成规模。

**一手来源**
- 角色系统：https://www.hiddendoor.co/blog/art-system-characters-behind-the-scenes
- 地点美术：https://www.hiddendoor.co/blog/location-art-design-inspiration-process
- 服装设计补充篇（文中链接）：https://www.hiddendoor.co/blog/art-system-character-outfit-design-behind-the-scenes

**对文境的启示**
1. **"标签 + 向量 + 随机性"三件套**足以在**零生成**的前提下做出近乎无限的变化。
   文境若要引入分层，第一件事不是画图层，而是定义**标签词表**——它决定了未来
   "检索得到什么"和"评审该拦什么"。
2. **"不该出现的不出现"是负向约束**：标签不只用于召回，也用于排除（无僵尸世界不出僵尸脸）。
   文境现在的 prompt 只有正向锚点，缺一个显式的"负面清单"。
3. **随机性要留**：同一角色在不同故事里应当允许不同，但同一故事内必须稳定。
   文境的分支/会话边界正好是这条随机性的天然作用域。
4. **不要照搬"人工图层"**：Hidden Door 的代价是内容被资产库覆盖度限制，新增题材要先画。
   文境每篇课文都是新题材，只能取"结构"（分层 + 标签 + 组装），不能取"资产"。

---

### 1.7 本组小结

1. **延迟的解法是库存，不是更快的模型**。Jeff Schomay 用 20 条基线库存抹平 20–30 秒延迟，
   AWS 用"离线预生成 + 运行时检索"把实时范围压到只剩 box art。文境已有占位与后台补图，
   缺的是**补货策略**：按叙事前瞻预热，而不是等玩家走到才发请求。
2. **检索层便宜到可以忽略，生成层才是成本中心**。Ubisoft 3 万资产 < 1 秒；AWS 检索"数秒内"。
   文境应把 `image_search` 从"降级方案"升格为**第一优先候选**，检索不到再生成。
3. **Agent 团队的分工已经有工业模板**：Director 定方向 / Artist 选与生成 / QC 打分回炉。
   文境的 `ArtDirector` 草案与之同构，差的是 Artist 的**检索权**和 QC 的**独立预算**。
4. **"生成结果必须变成持久状态"是共识**。arXiv 综述用 Infinite Craft 举例，文境用事件溯源
   实现得更彻底——这条应当写进契约，防止未来被改成"每次重新生成"。
5. **Hidden Door 证明分层的关键是标签体系，不是图层文件**。文境若做角色卡/立绘分层，
   第一步应是定义标签词表（正向召回 + 负向排除），第二步才是图层与合成。

---

## 2. 分层立绘与透明背景：结论

1. **立绘数据模型不用自研**：Ren'Py 的 `layeredimage` 已经是事实标准——图层槽位（group）+ 变体（attribute）+ 互斥 + `always` + `when` 条件 + 每层 `offset`/`alpha`，前端照抄这套语义即可，代价是零。
2. **透明背景有三条路，优先级明确**：
   - **Seedream 5.0 图层拆分**（同 provider，一次调用出「1 张底图 + 最多 16 个带透明通道的图层」）——最省事，不引入新厂商；
   - **BiRefNet 生成后抠图**（MIT，SOTA 分割，fal / Cloudflare / Scenario / Layer 均有托管）——最稳，单张毫秒级到秒级；
   - **Qwen-Image-Layered**（Apache 2.0，整图拆 3–8 个 RGBA 层，fal $0.05/张）——Seedream 拆层不够好时的第二意见。
   - **LayerDiffuse 不推荐**：2024 年的 SD 时代方案，仓库最后推送 2024-06-16，已被 Qwen-Image-Layered 在重建指标上超过。
3. **表情差分应该走「编辑式续画」而不是重生成**：只重画 face 图层，再与 base 合成。Seedream 的交互编辑（坐标/框选/箭头）与 Qwen-Image-Edit-2511 都支持；后者是 Apache 2.0 开放权重、多人一致性更强，但自托管要 GPU。
4. **平台侧工具（Layer.ai / AutoSprite / Spritesheets.ai）解决的是「像素风动画序列帧」**，文境要的是静态立绘 + 表情差分，属于用错工具——只借它们的**资产组织方式**（统一画布、透明 PNG、atlas 元数据），不必采购。
5. **一句话**：数据模型抄 Ren'Py，透明背景用 Seedream 图层拆分兜底 BiRefNet，差分用编辑式续画。

---

## 3. 分层立绘的数据模型：Ren'Py `layeredimage`

### 3.1 `layeredimage`（官方文档）

**它是什么**
Ren'Py 的「一张立绘 = 多个图层按属性组合」机制。官方动机写得很直白：4 套服装 × 4 种发型 × 6 种表情 = 96 种组合，为每种组合存一张静态图会吃掉大量磁盘和工时。它在 **init 阶段**声明，运行时按属性选择图层。

**怎么做（机制/参数）**
- **`group`**：把属性分组并**互斥**（同一组里 `show eileen a b` 报错）；组名 `multiple` 是保留字，表示组内不互斥。
- **`attribute`**：一个属性对应一个 displayable；`default` 表示未指定时默认显示；`null` 表示只做登记、不绑图（配合 `when` 做条件显示）。
- **`always`**：无条件常显的图层（如半透明前发）。
- **`when`**：布尔表达式，基于当前属性集（`and` / `or` / `not` / 括号）；旧写法 `if_any` / `if_all` / `if_not` 已废弃但兼容。
- **`if`**：运行时条件（转成 `ConditionSwitch`），**这是唯一允许「运行时会变的数据」的入口**。
- **`attribute_function` / `config.adjust_attributes`**：把传入属性集改写成另一套（例如「穿私服就换专用前发」）。
- **`LayeredImageProxy`**：把同一立绘代理到别处（侧边头像、加变换后复用）。
- **`offset`**：每个属性可单独指定像素偏移；默认图片水平居中、底边贴窗口底边。
- **`alpha`**：0–1 浮点；中文实战里前发用 `166/255` 做碎发半透明。
- **自动裁剪**：Ren'Py 加载前会把图裁到非透明像素的包围盒，所以**不需要自己裁**。
- **文件名模式**：`layeredimage名_group名_variant名_attribute名`，用下划线连接；`auto` 组会按这个模式自动扫描已有图片。
- **关键限制**：官方明确「layered images 不应该使用运行时会变的数据」——除了 `if` 的条件，块内所有表达式（含 `format_function`）都在 init 时求值一次。

**关键数字**
- 示例组合数：4 服装 × 4 发型 × 6 表情 = 96。
- `auto` 组可把 13 行显式声明压缩成 3 行，且新增表情不需要改代码。

**一手来源**
- https://www.renpy.org/doc/html/layeredimage.html

**对文境的启示**
- 立绘不需要「一张图一个角色」，而是「一个角色 = 若干槽位 + 每槽若干变体」；角色卡里的 `Appearance` 只负责**生成**这些变体，**选择**由运行时状态决定。
- 「不该用运行时会变的数据」这条对文境反而合适：图层结构在剧本定稿时就固定，运行时只切换属性。

### 3.2 中文实战：offset 对齐与前发遮挡

**它是什么**
一篇把商业游戏（KRKR 引擎）立绘移植到 Ren'Py 的实录，包含真实清单文件里的对齐数据。

**怎么做（机制/参数）**
- 每个 `attribute` 带自己的 `offset`，从原引擎清单里逐项核对；作者原话「前发图层的 offset 最敏感，差一个像素效果就惨不忍睹」。
- 前发用 `always` + `alpha 166/255` 做半透明碎发遮挡。
- 「同一朝向的不同服装共用同一套前发」用 `always`；「私服专用前发」用 `if_any[...]` 分组切换。
- 非 ASCII 文件名可用但不推荐，建议全 ASCII。

**关键数字**
- 单个角色：2 个朝向 × 6 套服装 + 手腕差分 = 12 + 6 个基础图层，再叠加表情、脸红、前发图层。

**一手来源**
- https://www.cnblogs.com/eslzzyl/p/17219130.html

**对文境的启示**
- **对齐是分层立绘的第一大坑**：生成式产出每张图的角色位置都不同，必须统一画布（固定 canvas + 角色锚点），否则 offset 无从谈起。建议生成时就要求「角色脚底中线对齐画布中轴、头顶留固定边距」。
- 前发/遮挡层是「同一角色换表情不换脸」的关键：脸层变化、前发层不变，视觉上就是同一个人。

### 3.3 可直接落地的 JSON 数据模型（由上述语义推导）

```json
{
  "character_id": "kong_yiji",
  "canvas": { "width": 1024, "height": 1536, "anchor": "bottom-center" },
  "draw_order": ["base", "outfit", "face", "hair_front", "accessory"],
  "slots": {
    "base": {
      "default": "neutral_pose",
      "variants": {
        "neutral_pose": { "asset_id": "ast_...", "offset": [0, 0], "alpha": 1.0 }
      }
    },
    "outfit": {
      "default": "qipao",
      "variants": {
        "qipao":  { "asset_id": "ast_...", "offset": [0, 0] },
        "cotton": { "asset_id": "ast_...", "offset": [0, 0] }
      }
    },
    "face": {
      "default": "neutral",
      "variants": {
        "neutral": { "asset_id": "ast_...", "offset": [12, -980] },
        "smile":   { "asset_id": "ast_...", "offset": [12, -980] },
        "sad":     { "asset_id": "ast_...", "offset": [10, -976] }
      }
    },
    "hair_front": {
      "always": true,
      "alpha": 0.65,
      "variants": { "default": { "asset_id": "ast_...", "offset": [6, -1002] } },
      "when": "not hat"
    }
  },
  "selection": {
    "face": "character.expression",
    "outfit": "scene.outfit"
  }
}
```

映射关系：`group` → `slots` 键；`attribute` → `variants` 键；`always` / `when` / `offset` / `alpha` 原样保留；**数组顺序即绘制顺序**（Ren'Py 的绘制顺序也是声明顺序，与画图软件相反）。

---

## 4. 透明背景：三条路

### 4.1 BiRefNet（生成后抠图）

**它是什么**
高分辨率二值图像分割（DIS）模型，专门解决「前景/背景分离 + 细边缘」；学术出处 CAAI AIR'24，代码 MIT。被 Cloudflare、Scenario、Layer、fal 等直接集成。

**怎么做（机制/参数）**
- 两个模块：**Localization Module（LM）**用全局语义定位主体，**Reconstruction Module（RM）**用 bilateral reference 重建边缘。
- bilateral reference 分内外两路：**inward reference**（原图 patch 补细节）+ **outward reference**（梯度图引导关注细节密集区）；另有辅助梯度监督。
- 输出**软遮罩**（0–255 连续），不是二值硬边——这对发丝、半透明布料是必要的。
- 常见变体：general / portrait / DIS / HRSOD / COD；v2 强化了细发与半透明物体的边缘。

**关键数字**
- 论文在 DIS 五个测试集与 HRSOD / COD 上全面超过既有 SOTA。
- Cloudflare 实测（两套数据集平均）：`birefnet-general` **IoU 0.87 / Dice 0.92**；对比 `U2-Net` 在 Humans 集 IoU 0.89/Dice 0.94 但 DIS5K 只有 **0.39 / 0.52**；`isnet-general-use` 0.82 / 0.89。
- fal：最高 **2048×2048**，3 个变体（Light / Heavy / Portrait），按计算秒计费。
- Layer：BiRefNet v2 **0.1 CU / 百万像素**。
- Cloudflare：`segment=foreground` 走 Images 变换计费，**$0.50 / 1000 次唯一变换**（免费额度 5000 次/月）。
- 仓库：`ZhengPeng7/BiRefNet`，MIT，4,408 stars，最后推送 2026-10-25。

**一手来源**
- 论文：https://arxiv.org/abs/2401.03407
- Cloudflare 评测与接入：https://blog.cloudflare.com/background-removal
- fal：https://fal.ai/models/fal-ai/birefnet
- 仓库：https://github.com/ZhengPeng7/BiRefNet
- Scenario 托管：https://www.scenario.com/models/birefnet-background-removal
- Layer 模型页：https://layer.ai/models/nankai-birefnet-v2

**对文境的启示**
- 文境生成的是**课本插画风格**（水墨/淡彩），不是照片；BiRefNet 的 anime 变体与 ToonOut 相关工作说明它对风格化图像的边缘也适用（论文侧有第三方扩展，未直接验证文境风格）。
- 最现实的用法：**先生成「带简单纯色背景的立绘」，再 BiRefNet 抠图**。比要求模型直接画透明背景稳定得多。

### 4.2 LayerDiffuse（原生透明生成）

**它是什么**
让扩散模型**直接输出真 RGBA**（不是 RGB + 后贴遮罩）的方案：训练一个透明 VAE，把 alpha 编码成 latent offset，再自定义解码器同时还原 RGB 与 alpha；可选前景/背景 LoRA 做多层生成。

**怎么做（机制/参数）**
- 训练阶段：透明 VAE 在 RGBA 上训练，透明区域用「上下文感知的颜色」填充避免硬边；alpha 编码为 compact latent → latent offset。
- 推理阶段：基础模型先生成普通 RGB latent，叠加预计算的透明 offset，再走正常扩散；多层模式由 fg/bg LoRA 分别引导并共享注意力保持对齐。
- 只训练 VAE（与可选 LoRA），扩散主干冻结。

**关键数字**
- 仓库 `lllyasviel/LayerDiffuse`，**Apache-2.0**，2,222 stars，**最后推送 2024-06-16**（不活跃）。
- 与「生成后抠图」的差别：抠图适用于任何模型/已有图；LayerDiffuse 需要模型侧适配（SD1.5/SDXL 系）。

**一手来源**
- Runware 技术说明：https://runware.ai/blog/introducing-layerdiffuse-generate-images-with-built-in-transparency-in-one-step
- 仓库：https://github.com/lllyasviel/LayerDiffuse

**对文境的启示**
- 思路值得记（透明是生成的一部分，不是后处理），但**工程上不推荐**：2024 年停更、绑定 SD 生态、与文境现用的 Seedream 不兼容。

### 4.3 Qwen-Image-Layered（整图拆层）

**它是什么**
端到端把**一张 RGB 图拆成多个语义解耦的 RGBA 层**，每层可独立移动/缩放/改色/替换，合成后能还原原图。CVPR 2026 论文，Apache 2.0 权重。

**怎么做（机制/参数）**
- 三个关键设计：**RGBA-VAE**（RGB 与 RGBA 共享 latent 空间，避免两个 VAE 的分布错配）、**VLD-MMDiT**（可变层数分解）、**多阶段训练**（把预训练生成模型逐步改造成拆层器）。
- 训练数据来自 **PSD 文档**的自动抽取与标注流水线（解决多层真值稀缺）。
- 提示词是**整图描述**，不是逐层控制。
- 支持导出 PPTX/PSD；官方提供 Gradio demo。
- 层数可变，典型 **3–8 层**。

**关键数字**
- 论文：https://arxiv.org/abs/2512.15603 ；CVPR 2026 开放版可查。
- fal 托管：**$0.05 / 张**，返回多张 PNG（每层一个 URL）。
- 权重 20B 级（Qwen-Image 系），自托管需要 GPU。
- 论文称其 RGBA-VAE 在 PSNR / SSIM / rFID / LPIPS 上优于 AlphaVAE 与 LayerDiffuse。

**一手来源**
- HF 模型卡：https://huggingface.co/Qwen/Qwen-Image-Layered
- 论文：https://arxiv.org/abs/2512.15603
- fal：https://fal.ai/models/fal-ai/qwen-image-layered

**对文境的启示**
- 这是「**先出整图，再拆成可编辑图层**」的路线，和文境「先有完整场面图」的现状天然契合：一张场景图可以拆成背景 / 人物 / 前景装饰，后续换表情只动人物层。
- 但 20B 自托管不现实；**只能走托管 API**（fal $0.05/张），比重新生成一张便宜。

### 4.4 Seedream 5.0 图层拆分（同 provider 内，最省事）

**它是什么**
火山方舟 Seedream 5.0 pro / flash 的官方能力之一：把单张图的**主体、背景、文字、装饰元素**自动拆成 **1 张底图 + 最多 16 个独立、带透明通道的图层**，便于移动、缩放、替换、调色。

**怎么做（机制/参数）**
- 能力矩阵（官方文档）：文生图 ✓、单/多图生图 ✓、**交互编辑 ✓**、**图层拆分 ✓**、原生多语种生成 ✓。
- **交互编辑**支持坐标、框选、箭头指定编辑位置，做局部替换 / 物品定位 / 区域生成。
- 图层拆分场景的输入约束：**仅支持单张图**，格式 PNG / JPEG，总像素 ≥ 512×512。
- 通用参考图约束：最多 **10 张**、单张 ≤30MB、宽高比 [1/16, 16]。
- 生成数量：支持单图 / 多张图层（**1 张底图 + 16 张图层**）。
- 分辨率档：1K / 1.5K / 2K；限流 500 张/分钟。
- 价格（前文已述）：flash 0.12 元/张、pro 0.30 元/张（火山方舟模型价格页）。

**一手来源**
- Seedream 5.0 pro 文档：https://www.volcengine.com/docs/ark/seedream-5-0-pro
- 提示词指南：https://www.volcengine.com/docs/ark/seedream-4-0-5-0-prompt-guide
- 价格：https://www.volcengine.com/docs/ark/model-pricing

**对文境的启示**
- **这是本报告最有行动价值的一条**：文境已经在用 Seedream，图层拆分不需要新厂商、新 key、新计费体系，只多一个请求参数/模式。
- 可行路径：生成场面图 → 图层拆分 → 背景层与人物层分离 → 后续换表情只编辑人物层，背景零重生成。
- 未核实：拆层是否额外计费、拆层质量在水墨/淡彩风格下的表现、16 层上限对「多人物场景」是否够用。

---

## 5. 平台侧工具链

### 5.1 Layer.ai

**它是什么**
面向游戏工作室的 AI 资产平台（自称 400+ 工作室在用），覆盖 image / 3D / video / audio，带自定义风格训练与 API/MCP。

**怎么做（机制/参数）**
- sprite 工作流：文生 sprite / 图生 sprite / sprite sheet；**统一单元格 PNG + 透明背景**，可直接进 Unity / Godot / GameMaker / Unreal Paper2D。
- 透明实现两条：模型直接给透明背景，或「要求纯色 chroma-key 背景 → 生成后自动跑一次抠图」。
- 平台内有 `BiRefNet v2`（0.1 CU/百万像素）等模型，可作为工作流节点；模型页提供 API reference 与 MCP server URL。

**关键数字**
- 计费：**Creative Units（CU）**，无席位费、无套餐门槛；**$10/月起含 300 CU**，之后**每 1000 CU 加 $60**；未用 CU 最多 10% 结转。
- 示例模型单价：GPT Image 2.5 Sunburst 1.7 CU/百万像素；Gemini 3.1 Flash Image 2 CU/次（1K）。

**一手来源**
- https://layer.ai/pricing
- https://layer.ai/use-cases/sprite-generation
- https://layer.ai/models/nankai-birefnet-v2

**对文境的启示**
- 文境不需要它的 sprite 动画，但它的**计费模型（按 CU、无席位费）**和**「模型即工作流节点」的组织方式**值得借鉴：文境的 ArtDirector 也可以把「生成 → 抠图 → 评审」做成可复用节点链，而不是写死在代码里。
- 采购价值低：多引入一个平台，等于多一套 key、配额与合规面。

### 5.2 AutoSprite

**它是什么**
「单张图 → 动画序列帧」的生成服务，覆盖角色、道具、3D 模型、过场。

**怎么做（机制/参数）**
- 上传一张图或文生图作为角色基准，选动作（idle / walk / run / jump / attack / 自定义），输出 **PNG spritesheet + atlas 帧数据**。
- 一致性宣称：跨帧保持设计、比例、颜色、细节；导出时 pivot 与 baseline 对齐，便于替换。
- **REST API**：创建/列出角色、请求动画、轮询异步任务、下载资产；有 **MCP** 接入；Advanced Mode 支持批量队列与可复用 moveset。

**关键数字**
- 定价：**$12/月起**；免费档 15 credits/月 + 每日登录 credits。

**一手来源**
- https://www.autosprite.io
- 对比页（第三方）：https://ludo.ai/compare/best-ai-sprite-generators

**对文境的启示**
- 文境不做逐帧动画，**不适用**。唯一可借的是「pivot / baseline 对齐」这条工程纪律——对应立绘的锚点与 offset。

### 5.3 Spritesheets.ai / Ludo / Scenario Retro Diffusion

**它是什么**
精灵表 / 像素风的生成工具与聚合对比。

**怎么做（机制/参数）**
- **Spritesheets.ai**：单图 + prompt → 精灵表；导出 PNG（预乘 alpha）+ JSON/XML atlas；Po2 尺寸优化。未在页面找到 API 说明。
- **Ludo**：一站式游戏资产（sprite + 其他），sprite sheet 未订阅带水印。
- **Scenario**：托管 Retro Diffusion 动画模型，返回 walk/run/idle 的 GIF 或 sprite sheet；Pro 起可训练自定义模型。

**关键数字**（均来自 ludo.ai 的对比页，属第三方口径）
- Spritesheets.ai：$5.99/月（6000 tokens，最多 12 张表）与 $14.99/月（15000 tokens）。
- Ludo：$20/月（年付 $15）；Scenario：$15/月起；Layer：$10/月起；AutoSprite：$12/月起；PixelLab：$12/月（年付 $8.25）。

**一手来源**
- https://www.spritesheets.ai
- https://ludo.ai/compare/best-ai-sprite-generators
- https://www.scenario.com/pricing

**对文境的启示**
- 全部是**像素风 / 序列帧**定位，与「课本插画静态立绘」不匹配。**不采购**。
- 唯一有信息量的观察：这类工具都把「透明 PNG + atlas 元数据 + 统一单元格」当作交付标准——文境若做立绘，也应把这三样作为资产契约的一部分。

### 5.4 Jenova（视觉小说立绘）

**它是什么**
面向视觉小说的一站式 agent 平台，宣称覆盖「角色设定 → 主立绘 → 表情/嘴型图层 → 剧本 → UI」，并有 API。

**怎么做（机制/参数）**
- 可验证的流程描述：先锁定一份**角色设定（character bible：轮廓、眼型、发量、服装标志、锁定待机姿势）**，生成主立绘，再在同一会话里迭代「说话 / 皱眉」图层，最后与背景、对白框、名牌在 Ren'Py 里组装。
- 明确区分两种做法：**每种表情存整图**（好上手、难维护）vs **分层基础身体 + 服装 + 眉毛 + 嘴型 + 脸红**（商业做法，控体积与组合数）。

**关键数字**
- 页面引用：独立游戏 2D 美术外包 $10,000–50,000；初级单张 $50–150，资深角色美术 $500–1,500+。
- 引用 GDC 2026：36% 从业者工作中使用生成式 AI；另一处「95% 受访开发者已用 AI 自动化重复任务」——**两个数字口径不一致，按营销文案看待**。

**一手来源**
- https://www.jenova.ai/zh/resources/visual-novel-sprite-generator

**对文境的启示**
- **「角色设定先行」与文境的角色卡思路一致**，可佐证方向正确。
- 「分层 vs 整图」的取舍讲得最清楚：分层是为了**控制组合数与文件体积**，不是为了好看。
- API 存在性只有一句营销文案，**未核实**文档、定价与 SLA。

### 5.5 PicLumen（视频演示）

**它是什么**
一个图像生成平台，演示了「保持角色设计、只改姿势/张嘴」并一键去背景。

**怎么做（机制/参数）**
- 演示流程：生成角色 → 输入「同一角色、嘴张开」→ 去背景 → 生成背景图 → 编辑成卡通风格 → 在 Godot 里组装。

**关键数字**
- 无官方文档或价格可核实。

**一手来源**
- https://www.youtube.com/watch?v=2rj4HAxWffM （**视频演示，非官方文档**）

**对文境的启示**
- 只作为「编辑式续画 + 抠图」这条组合在实操上可行的旁证，不作为选型依据。

---

## 6. 模型侧：多参考图与编辑式续画（补新核实）

> 前文已述的部分不重复；以下只列**新核实到或前文未写清**的细节。

### 6.1 Seedream 5.0 pro / flash

**它是什么**
火山方舟的图像生成/编辑模型族，文境现用 flash。

**怎么做（机制/参数）**
- 前文已述：10 张参考图、base64 data URL、按 kind 抬升像素档。
- **新增核实**：pro 与 flash **都支持**单/多图生图、交互编辑、图层拆分、原生多语种生成；交互编辑支持坐标/框选/箭头；图层拆分输入仅单图（PNG/JPEG）、总像素 ≥512×512。

**关键数字**
- 分辨率 1K / 1.5K / 2K；生成 1 底图 + 16 图层；限流 500 张/分钟；参考图 ≤30MB、宽高比 [1/16, 16]。
- 价格：flash 0.12 元/张、pro 0.30 元/张（前文已述）。

**一手来源**
- https://www.volcengine.com/docs/ark/seedream-5-0-pro

**对文境的启示**
- 同一个 adapter 就能覆盖「生成 / 编辑 / 拆层」三种模式，不需要新 provider——这是最低成本的架构演进路径。

### 6.2 Nano Banana Pro（Gemini 3 Pro Image）

**它是什么**
Google 的图像生成/编辑模型，主打复杂构图下的多元素一致性。

**怎么做（机制/参数）**
- 官方原文：可混合 **最多 14 张图**、保持 **最多 5 个人** 的一致性与相似度。
- 支持**局部编辑**（选择/细化/变换任意区域）、改相机角度、改焦点、调色、改光照（日/夜、景深）。
- 支持 2K / 4K 与多宽高比；改宽高比时可**保持角色在画面中的位置不变**。

**关键数字**
- 14 图 / 5 人（官方）；2K、4K；价格前文已述（$0.134–0.24）。

**一手来源**
- https://blog.google/technology/ai/nano-banana-pro/

**对文境的启示**
- 「改宽高比但角色位置锁定」对文境有用：同一张立绘要适配横屏/竖屏舞台时，不必重画。

### 6.3 Qwen-Image-Edit-2511

**它是什么**
Qwen 的开放权重图像编辑模型（Apache 2.0，20B BF16），2509 的升级版。

**怎么做（机制/参数）**
- 官方 diffusers 示例接受 **image 列表**（多图输入），可按指令「保留图一的人、套用图二的材质」。
- 能力重点：**减少图像漂移**、单人/多人一致性、**内置社区 LoRA**（多角度、角色一致性，无需外挂）、工业设计与材质替换、几何推理（辅助线/结构编辑）。
- 2509 已支持 1–3 张输入图；2511 强化多人融合（把两张单人图合成合影）。

**关键数字**
- Apache 2.0；20B BF16；HF 1.49k likes；托管走阿里云百炼 / Model Studio，也有 GGUF 本地版。
- 单价：**未核实**（百炼按 token/张计费，未读到确切数字）。

**一手来源**
- https://huggingface.co/Qwen/Qwen-Image-Edit-2511
- ComfyUI 原生工作流：https://docs.comfy.org/tutorials/image/qwen/qwen-image-edit-2511

**对文境的启示**
- 表情差分场景下，2511 的「减少漂移」正是需要的；但自托管要 GPU，**只能走托管**。
- 内置 LoRA 意味着不需要为每个角色训模型——与文境「不训 LoRA」的约束不冲突。

### 6.4 FLUX.1 Kontext

**它是什么**
Black Forest Labs 的上下文图像编辑模型族（Pro / Max / Dev），输入图 + 指令，保持主体身份不变。

**怎么做（机制/参数）**
- 多轮编辑：每一步在上一步结果上继续改。
- **Pro 只接受单张参考图**（TheRouter 的接口元数据 `max_reference_images: 1`）；第三方页面称「3 张以上参考图自动切到 Max」，**未在 BFL 官方文档核实**。
- Dev 是 12B 开放权重版本；Pro/Max 闭源仅托管。

**关键数字**
- 价格：Pro **$0.04/张**、Max **$0.08/张**（SiliconFlow 官方博客；BFL 官方定价页给的是计算器默认费率）。
- 输出约 1MP；尺寸档 1024×1024 / 1024×1536 / 1536×1024 / 1280×720 / 720×1280。

**一手来源**
- https://www.siliconflow.com/blog/next-gen-image-generation-editing-flux-1-kontext-now-available-on-siliconflow
- https://therouter.ai/models/black-forest-labs--flux-kontext-pro

**对文境的启示**
- 单图多轮编辑 + 便宜，适合做「表情差分」这类**小改动**；但文境已有 Seedream，引入 FLUX 的边际收益主要是编辑质量，需 A/B 才能定。

---

## 7. 对文境的落地方案（推荐）

### 7.1 立绘数据模型（直接可用）

采用 §3.3 的 JSON 形状，落到契约层：
- 新增 `CharacterSprite` 契约：`character_id` + `canvas` + `draw_order` + `slots` + `selection`。
- `AssetKind` 增加 `SPRITE_LAYER`，每个图层资产带 `(character_id, slot, variant, offset, alpha)` 元数据。
- 前端按 `draw_order` 依次叠 `<img>`（或 canvas），`selection` 由角色状态映射。
- **生成侧硬约束**：所有立绘层必须同一画布尺寸、角色锚点（脚底中轴）一致，否则 offset 无效。

### 7.2 透明背景（推荐顺序）

1. **Seedream 5.0 图层拆分**（首选）：同 provider，一次调用出 1 底图 + ≤16 透明层；先做 PoC 验证水墨风格下的拆层质量。
2. **BiRefNet**（兜底）：拆层不达标时，生成「纯色背景立绘」→ BiRefNet 抠图；fal / Cloudflare / Layer 均可，MIT 许可，成本极低。
3. **Qwen-Image-Layered**（第二意见）：fal $0.05/张，一次拆 3–8 层，适合「已有整图要变成可编辑资产」。
4. **不推荐 LayerDiffuse**：停更、生态不匹配。

### 7.3 表情差分（推荐顺序）

1. **编辑式续画**：以 base 层为底图，只改 face 区域（Seedream 交互编辑 / Qwen-Image-Edit-2511 / FLUX Kontext）。
2. **固定 face 层偏移**：所有表情共用同一画布与 offset，换脸不换位。
3. **前发/遮挡层常显**：保证「换表情仍是同一张脸」。

### 7.4 不建议

- **序列帧动画**（AutoSprite / Spritesheets.ai / Ludo）：文境是静态插画 + 对白，用不上。
- **自托管拆层/编辑模型**：Qwen-Image-Layered 与 Qwen-Image-Edit-2511 都是 20B 级，与「不引入 GPU 常驻」直接冲突。
- **为每个角色训 LoRA**：与「每篇课文临时生成角色」的成本模型冲突（前文已述）。
- **Layer.ai / Scenario 采购**：能力可被现有 provider + BiRefNet 覆盖，多引入平台只增加 key 与合规面。

---

## 8. 参考来源（本轮实际抓取，2026-11-15）

**分层立绘**
- Ren'Py Layered Images 官方文档：https://www.renpy.org/doc/html/layeredimage.html
- 中文实战（offset / 前发 / 迁移）：https://www.cnblogs.com/eslzzyl/p/17219130.html
- 入门教程：https://bast13.itch.io/renpy-layered-images

**透明背景与拆层**
- BiRefNet 论文：https://arxiv.org/abs/2401.03407
- BiRefNet 仓库（MIT）：https://github.com/ZhengPeng7/BiRefNet
- Cloudflare 评测与 `segment` 接入：https://blog.cloudflare.com/background-removal
- Cloudflare Images 定价：https://developers.cloudflare.com/images/pricing
- fal BiRefNet：https://fal.ai/models/fal-ai/birefnet
- Scenario BiRefNet：https://www.scenario.com/models/birefnet-background-removal
- Layer BiRefNet v2：https://layer.ai/models/nankai-birefnet-v2
- LayerDiffuse 技术说明：https://runware.ai/blog/introducing-layerdiffuse-generate-images-with-built-in-transparency-in-one-step
- LayerDiffuse 仓库：https://github.com/lllyasviel/LayerDiffuse
- Qwen-Image-Layered HF：https://huggingface.co/Qwen/Qwen-Image-Layered
- Qwen-Image-Layered 论文：https://arxiv.org/abs/2512.15603
- Qwen-Image-Layered on fal：https://fal.ai/models/fal-ai/qwen-image-layered
- Seedream 5.0 pro 文档：https://www.volcengine.com/docs/ark/seedream-5-0-pro
- Seedream 提示词指南：https://www.volcengine.com/docs/ark/seedream-4-0-5-0-prompt-guide

**平台与工具**
- Layer 定价：https://layer.ai/pricing
- Layer sprite：https://layer.ai/use-cases/sprite-generation
- AutoSprite：https://www.autosprite.io
- Spritesheets.ai：https://www.spritesheets.ai
- Ludo 对比页（第三方）：https://ludo.ai/compare/best-ai-sprite-generators
- Scenario 定价：https://www.scenario.com/pricing
- Jenova 中文页：https://www.jenova.ai/zh/resources/visual-novel-sprite-generator
- PicLumen 实操视频：https://www.youtube.com/watch?v=2rj4HAxWffM

**模型侧**
- Nano Banana Pro 官方博客：https://blog.google/technology/ai/nano-banana-pro/
- Qwen-Image-Edit-2511 HF：https://huggingface.co/Qwen/Qwen-Image-Edit-2511
- Qwen-Image-Edit-2511 ComfyUI 文档：https://docs.comfy.org/tutorials/image/qwen/qwen-image-edit-2511
- FLUX.1 Kontext（SiliconFlow 官方博客，含价格）：https://www.siliconflow.com/blog/next-gen-image-generation-editing-flux-1-kontext-now-available-on-siliconflow
- FLUX.1 Kontext Pro 接口元数据：https://therouter.ai/models/black-forest-labs--flux-kontext-pro

---

## 9. 未核实与局限

1. **Seedream 图层拆分的实际质量与计费**：官方文档只写能力与输入约束，未写拆层是否单独计费、16 层上限在水墨/多人物场景下的表现；需要文境自己做一次 PoC。
2. **Qwen-Image-Edit-2511 的托管单价**：未读到阿里云百炼的逐张价格。
3. **Jenova API**：只有一句营销文案，无文档、无定价、无 SLA。
4. **AutoSprite / Spritesheets.ai 的 API 细节**：AutoSprite 有 REST + MCP 的说明；Spritesheets.ai 未在页面找到 API。
5. **Ludo 对比页的价格**：是第三方（本身卖工具）口径，且部分为年付折算价。
6. **FLUX 参考图数量**：Pro 单图有接口元数据佐证；「3 张以上切 Max」「FLUX.2 8 张 / FLUX 3 10 张」均为第三方页面，未在 BFL 官方文档核实。
7. **Nano Banana Pro 的 14 图 / 5 人**：本次读到了 Google 官方博客原文，可信度较前次调研提升。
8. **Cloudflare `segment`**：官方博客写明是 beta，且计费按 Images 变换计；长期可用性未承诺。
9. **未做实测**：本报告全部结论基于官方文档与公开评测，没有跑过任何模型对比；「Seedream 拆层优于 BiRefNet」「编辑优于重生成」都需要文境自己 A/B。

---

## 10. 风格护栏与 Agent / Harness 分工

### 10.1 腾讯游戏学堂访谈：风格包（Style Pack）与 Agent + Harness

**它是什么**
腾讯游戏学堂「初光·AI 游戏夜话」的一篇访谈实录，受访者是做 AI 原生游戏引擎与 AIGC 美术管线的团队（Kaka、Dira）。这是中文公开材料里少见的、把「美术管线为什么不可控、怎么变可控」讲成工程机制的一篇。**性质是访谈口径，不是论文或可复现实验**，下文的数字与结论都按受访者自述理解。

**怎么做**
- **风格包（Style Pack）**：把一款游戏的美术调性拆成可量化维度，每个生成节点在出图/出模型前都从风格包拉取对应约束。访谈给出的维度清单是：
  - 配色分布（主色 / 辅色 / 点缀色的比例）
  - 材质倾向（金属占比、木头占比、锈迹脏污占比）
  - 粗糙度层次
  - 磨损 / 污迹分布（均匀分布还是聚集在边缘）
  - 风格约束提示词（正向 + 负向）
- **Agent 四角色**：`Designer`（策划/制片，入口与分类）、`Artist`（美术，资产清单、风格一致性、检索与生成、骨骼动画匹配）、`Developer`（程序/玩法，规则、模块、配置、先跑通 placeholder）、`Reviewer`（测试/评审，只看证据，不创造内容）。Designer 先分类再决定谁开工，不是每次都全员上。
- **Harness 四职责**：状态（现在做到哪一步、当前活跃任务）、记忆（用户确认过的事实，如「主角是女性、赛博朋克、限时积分」）、工具（每个 Agent 能用什么工具，Reviewer 不许改工程）、验证（`WorkPlan` 是权威任务状态；改过工程后旧验证证据自动失效；Reviewer 消费证据而不是自己重跑）。
- **美术管线三类断点**：
  1. **生成质量断点**——布线、贴图、MRO、面数。典型例子是 PBR 物理失真：AI 给的 Roughness 全挤在 0.3–0.5，Metallic 给出 0.4/0.6 这种物理上不存在的值；解法是加「PBR 物理约束器」硬规则（Roughness 按材质类型限区间、Metallic 强制二值化）。
  2. **格式/规范断点**——通道排列、命名、UV 岛边距、法线方向；占比最大；解法是「S1 硬规则门禁」，每步生成后自动过一套工程规则，不合格自动打回。
  3. **语义/上下文断点**——不同人对「脏」的理解不一致导致风格漂移；解法是把这些理解固化成 Skill + 美学评审，统一项目组口径。

**关键数字**
- 一致率：改进前「卡在 40% 左右」，改用风格包后「干到 90%+」。**受访者未说明该指标的度量方法**（是人工抽检、还是某种相似度阈值），因此只能当作方向性证据，不能当作可复现 benchmark。
- 交付时长（受访者口径）：C 端「能看的模型」5–10 分钟；B 端可入引擎的场景资产 1–2 天，同质量传统外包「8–10 倍时间以上」。
- 四条拆 Agent 的理由：避免目标漂移、避免上下文污染、方便并行推进、方便问题归因。

**一手来源**
- 腾讯游戏学堂访谈全文：http://gameinstitute.qq.com/news/detail/326

**对文境的启示**
- 「护栏才是产品，模型只是引擎」这句话对文境尤其成立：文境换不起模型，但可以把 `DEFAULT_STYLE` 从一段文字升级成**带版本号的结构化风格包**，并让每张图的 prompt、去重键、评审 rubric 都引用同一个版本。
- Harness 的「验证证据随版本失效」直接对应文境的 `asset_jobs` 与 `assets` 行：**旧图不能证明新 prompt 的效果**，重绘后必须重新评审，不能复用上次的通过结论。
- 三类断点可平移：文境的「格式断点」是尺寸档位/宽高比/水印；「生成质量断点」是性别年龄与身份漂移；「语义断点」是「这个场景该画成什么样」的团队口径——最后这条正是文境现在缺的（画师只拿到一段自由文本）。

---

### 10.2 ybuild-ai 的 AI Game Art Pipeline Skill

**它是什么**
一个开源的 agent skill（MIT，304 stars，4 次提交），由 Y Build 发布，用于「把 AI 生成的图和视频变成能进游戏运行时循环的资产」。它不是 prompt 合集，也不是模型榜，核心主张是 **provider-neutral**：仓库里不带任何厂商 SDK 或密钥。

**怎么做**
- **核心规则**：`Pick the pipeline by runtime job, not by model hype.`（按运行时任务选管线，不按模型热度选。）
- **运行时任务 → 管线映射**：
  | 运行时任务 | 推荐管线 |
  |---|---|
  | 静态道具 / 物品 / 特效图标 | 图像模型 + 风格参考 + 可移除背景 |
  | 已有 / 品牌角色 | **优先复用既有 canonical 精灵图，而不是重生成** |
  | 战斗角色动画 | 关键帧优先 + 2D 网格 + 后处理 + 人工筛选 |
  | 走跑 / 身体力学 | 优先视频动作参考；3D 骨骼只在清理成本可接受时用 |
  | 环境循环 | 视频模型 → 抽帧 |
  | 过场 / Boss 入场 | 全屏视频转帧 + 代码驱动的命中逻辑 |
  | 运行时手感 | 确定性代码：顿帧、震屏、粒子、拖尾、音效 |
- **确定性后处理脚本**（不带模型调用）：`provider_stub.py`（适配器接口）、`chroma_key_magenta.py`（抠洋红背景）、`sheet_contact.py`（生成带编号的 contact sheet 供人工筛选）、`extract_video_frames.py`（视频抽帧并缩放）。
- **场景化参考文档**：`static-assets.md` / `battle-sprites.md` / `motion-video.md` / `backgrounds.md` / `runtime-shipping.md`，按任务只读相关那一份。
- **硬性告警**：有 canonical 角色表就不要重生成；复杂战斗姿势不要用 1×N 横条；过场视频不许拥有玩法语义（伤害、碰撞、目标追踪、冷却、音效归代码）；不要因为桌面好看就发超大背景图（查移动端纹理上限）；**AI 输出不是最终资产**，成品 = 生成图 + 清理 + 锚点 + 时序 + 压缩 + 运行时测试。

**关键数字**
- 304 stars、8 forks、4 commits、MIT（2026-11 快照）。
- 仓库没有给出任何效果指标或耗时数据——它是工作流规范，不是实验报告。

**一手来源**
- 仓库与 README：https://github.com/ybuild-ai/ai-game-art-pipeline-skill
- SKILL.md 原文：https://raw.githubusercontent.com/ybuild-ai/ai-game-art-pipeline-skill/main/SKILL.md

**对文境的启示**
- 它的组织方式**可以直接改造成文境的美术 agent 骨架**：把「runtime job」换成文境的 `AssetKind`（AVATAR / FULLBODY / BACKGROUND / SCENE_MONTAGE），每种 kind 给一条固定管线与一份检查清单。
- 「canonical 资产优先复用」是文境最该抄的一条：同一角色已有头像/立绘时，新场景应当**复用而不是重画**（这正是文境参考图机制的上位规则）。
- 「AI 输出不是最终资产」提醒文境：`assets` 行的 READY 不等于可交付，评审与后处理（尺寸、水印、格式）要算进管线，而不是事后补。
- provider-neutral 与文境的 `ImageGenPort` 同构——这条已经做对了，不必改。

---

## 11. 多 Agent 编排的先例

### 11.1 AWS Agentic Arcade：supervisor-worker 与 agentic QC

**它是什么**
AWS for Games 官方博客披露的一个可玩 Demo（Agentic Arcade）的架构，用多 agent 把「概念 → 可玩原型」串起来。**厂商博客口径**，但给出了具体的 agent 分工与评审回路，是公开材料里最接近「美术 agent 团队」的工业实现。

**怎么做**
- **四个专职 agent**：
  - `Director Agent`：游戏概念、题材、目标，做创意探索与定义；
  - `Artist Agent`：**协调视觉资产选择**——监督 box art 生成，用向量嵌入检索角色资产包；
  - `Developer Agent`：玩法机制配置、选机制、生成配置文件；
  - `Playtester Agent`：试玩并给下一步建议。
- **supervisor-worker 模式**：supervisor agent 派任务给 worker agent，worker 执行并回报；**evaluation agent 在资产进入资产库之前校验质量**。实现上用 DynamoDB 做任务队列、Lambda 做派发、Bedrock AgentCore + Strands Agents 驱动模型调用；agent 在单次会话内维持短期记忆，跨调用传递上下文。
- **agentic QC**：每个生成资产都过一道多模态评估，用 Amazon Nova Lite 按四个维度打分——**可辨识度、题材契合度、视觉一致性、内容安全**；不达阈值就**自动改写生成 prompt 并重生成**。

**关键数字**
- QC 四个维度是明确给出的；阈值与通过率未公开。
- 资产生成是**异步预生成**（ComfyUI headless on ECS），运行时主要做向量检索；只有概念、标题、box art 是真·实时生成。

**一手来源**
- AWS for Games Blog：https://aws.amazon.com/blogs/gametech/ai-assisted-game-production-from-static-concept-to-interactive-prototype

**对文境的启示**
- Artist Agent 的职责描述（「协调选择 + 监督生成 + 检索资产」）比文境现在的「画师只写 prompt」更完整：**检索与复用是美术 agent 的一等职责，不是附属**。
- agentic QC 的「不达标 → 自动改 prompt → 重生成」正是文境 `RetryPolicy` 该有的形态；差别在于文境已有 `VisionReviewAgent`，只需补「把评审意见回灌给画师」这一步（现有实现是重绘时带上意见，方向对）。
- 但**不要抄 supervisor-worker 与任务队列**：文境单进程、命令串行，`SceneAssetScheduler` 已经是更简单的等价物；引入队列只会增加一层没人消费的复杂度。

---

### 11.2 Ubisoft「From Brief to Scene」：agent 编排是「平台 + 检索 + 单 agent」

**它是什么**
Ubisoft 在 SIGGRAPH 2026 / DigiPro 发表的端到端 agentic 3D 资产管线，建立在 2022 年那套 USD 微服务之上。**论文/演讲口径**，有明确的组件与数字。

**怎么做**
- 三阶段：创意简报分析 → 智能资产发现 → 场景布局装配。
- **简报 → 选角清单**：用工作流自动化平台 **N8N** + **ComfyUI** 生图管线，把会议转录和创意简报转成结构化「资产选角清单」（asset casting list）加概念预演图，几分钟内完成。
- **资产发现**：**YOLO-World** 开放词表检测 + **CLIP** 语义检索，在 3 万多个已索引的 USD 资产里找匹配项；每个资产在**六个视角**上做嵌入。
- **场景装配**：一个通过 **MCP** 连到 Blender 的 agent，用自然语言指令把检索到的资产摆进场景。

**关键数字**
- 资产库规模 30k+ USD 资产，每个资产 6 视角嵌入；检索**不到 1 秒**。
- 定位是**快速原型与占位填充**，把前期资产工作从「天」压到「分钟」；不用于最终资产。

**一手来源**
- DigiPro 2026 议程页（含摘要）：https://digiproconf.org/program/program-4
- ACM 论文条目：https://dl.acm.org/doi/10.1145/3819990.3820033

**对文境的启示**
- 关键洞察：**它不是一群 agent 在聊天，而是「工作流平台 + 检索服务 + 单个操作 agent」**。文境对应过来就是：剧本生成 workflow（已有）+ 资产检索/去重（已有 `build_dedup_key`）+ 画师单 agent。这个形态是对的，不需要把画师拆成一堆 agent。
- 「六视角嵌入」对文境有直接启发：角色卡如果只存一张正面头像，检索与一致性判断都弱；**多视角（正/侧/全身）既是参考图来源，也是相似度判断的基准**。
- 「检索优先于生成」：文境已有跨会话缓存复用，但只在完全同键时命中；可以再加一层语义检索（同课文、同角色、同风格的近似复用）。

---

## 12. 角色认知与行业数据

### 12.1 「AI art director」这个新角色（演讲观点）

**它是什么**
Yauheni Kruk 在 SIGGRAPH HIVE 2023 的演讲《AI Pipeline for 3D Content: From Idea to 3D Generation》。**这是演讲观点，不是实证研究**，但它是「AI 美术指导」这个角色定位被公开表述得最清楚的一次。

**怎么做（核心论点）**
- **从「老虎机」到「系统架构」**：每次点生成得到随机结果，这叫 slot machine，不是生产工具；要转成「有规格的输入」——不是输入 `cool cyberpunk soldier`，而是给出 subject、风格、构图等结构化规格。
- **独特性不是生成出来的，是被导演出来的**（"Uniqueness is not generated. It is directed."）：未来不属于最会写 prompt 的人，而属于能「导演系统」、能从 100 个输出里挑出该继续做哪个并说清为什么的人。
- **AI 美术指导拥有的是创作系统，不是创作产出**：他决定游戏长什么样，并搭建能规模化产出且保持一致性的架构。
- **「我们在替代等待，不是在替代艺术家」**：被压缩的是「想法 → 初稿 → 修改 → 批准」之间的等待。
- 未来工作室形态：设计师（玩家体验）、开发者（游戏系统）、AI 美术指导（视觉身份与创作系统）、技术美术（把 AI 输出清理到可交付）。

**关键数字**
- 无。演讲没有给量化结果。

**一手来源**
- 演讲视频：https://www.youtube.com/watch?v=RQl5ixJdB64

**对文境的启示**
- 「AI 美术指导拥有创作系统」正好是文境 `ArtDirector` 该站的层级：它不该自己写每一句 prompt，而该拥有**角色卡 + 风格包 + 评审 rubric**这三样可复用资产。
- 「结构化规格而非形容词堆砌」直接支持「输入收窄」：文境的画师 agent 现在吃全量事实，等于让它在没有规格的情况下自由发挥。

---

### 12.2 GDC 2026：生成式 AI 的实际使用率与用途分布

**它是什么**
GDC《State of the Game Industry》年度调查，2026 年有两份口径（3 月与 11 月）。这是行业里被引用最多的基准数据。

**怎么做**
- 11 月报告：2,600+ 名从业者、69 个国家；问「是否在工作中使用生成式 AI 工具」。
- 3 月报告：按角色/学科拆分使用率，并首次给出**按任务类型**的使用分布。

**关键数字**
- **40%** 的从业者在工作中使用生成式 AI（较上年 36% 上升）；**57%** 的使用者每天用（GDC 官方 11 月页）。
- 3 月报告：**36%** 个人使用；游戏工作室从业者仅 **30%**，而发行/支持/市场类公司为 **58%**。
- 用途分布（3 月报告官方文章）：研究/头脑风暴 **81%**、日常事务 **47%**、代码辅助 **47%**、原型 **35%**。
- 态度：**55%** 认为生成式 AI 对行业有负面影响、**35%** 认为喜忧参半、**8%** 正面（11 月页）；视觉/技术美术从业者的负面比例最高（3 月报告为 64%）。
- **资产生成 19%、程序化生成 10%、玩家可见功能 5%**——这三个数字来自第三方对报告的二次分析（ziva.sh），**未在 GDC 官方页面核实**，引用时需标注。

**一手来源**
- GDC 官方 11 月报告页：https://gdconf.com/state-of-the-game-industry-november-2026
- GDC 官方 3 月报告文章：https://gdconf.com/article/gdc-2026-state-of-the-game-industry-reveals-impact-of-layoffs-generative-ai-and-more
- 二手（用途细分数字）：https://ziva.sh/blogs/gdc-2026-generative-ai-game-development-data

**对文境的启示**
- 数据说明：**生成式 AI 在游戏业的主战场是生产力工具，玩家可见的生成仍是极少数**（5% 量级）。文境的课堂配图属于「玩家可见」这一侧，意味着没有现成的行业护栏可抄，必须自建评审与降级——这解释了为什么 `VisionReviewAgent` 是必要的而不是过度设计。
- 美术从业者是负面态度最强的群体（64%），课堂场景又涉及教师审核：文境把「教师逐场景审核」放在终审位置，既是产品设计，也是组织阻力最小的落点。

---

## 13. 视觉评审 rubric 的公开先例

### 13.1 OpenAI Cookbook：Image Evals（gate + 分级 rubric）

**它是什么**
OpenAI 官方 cookbook 里关于「图像生成/编辑怎么评测」的工程指南。**官方文档口径**，不是论文，但它给出的分层方法非常可直接落地。

**怎么做**
- **先 gate，再分级**：先用严格的 pass/fail 判定拦「硬失败」（缺必需组件、文案错、编辑溢出到非目标区域、不该改的地方被改了），再在硬失败受控之后加 **0–5 的 rubric 分级**。
- **生成类评测维度**：指令遵循（约束是否满足）、文字渲染（准确/可读/位置）、风格控制（美学匹配、品牌/角色一致性）、偏好对齐（rubric 标签 + 成对比较）。
- **编辑类评测维度**：变换正确性、局部性（只改该改的）、保持性（不该改的没改）、空间控制（改对了实例/区域）。
- **失败打标签**：把失败模式做成一致的标签，才能量化「什么在坏」、找到聚集的根因、跟踪调参进展。
- 评测循环：`Inputs → Model → Outputs → Graders → Scores → Feedback → Improvement`。

**关键数字**
- 无固定阈值；建议 0–5 分级，且「先硬 gate 后软分级」的顺序是明确主张。

**一手来源**
- https://developers.openai.com/cookbook/examples/multimodal/image_evals

**对文境的启示**
- 文境现在的 `VisionReviewAgent` 输出的是单一 score + reason，**混了 gate 与审美**——这正是它容易被「画得好看但画错了」骗过的原因。建议拆成：
  - **硬 gate（pass/fail）**：性别年龄、是否同一角色、在场人物是否齐全、关键物件是否出现；
  - **分级 rubric（0–5）**：构图、风格契合、叙事清晰度、美术质量。
- 「失败打标签」是文境最缺的一环：现在只有一条日志，无法回答「最近 100 张图里最常见的问题是什么」。加一个枚举标签就能做统计与针对性改 prompt。

---

### 13.2 Prometheus-Vision：自定义 rubric 的 VLM 裁判

**它是什么**
ACL 2024 Findings 论文《Vision-Language Model as a Judge for Fine-Grained Evaluation》，训练一个能按**用户自定义评分 rubric** 给「图像 + 回答」打分的 VLM 裁判。**论文口径**，有数据集与训练方法。

**怎么做**
- 每条评测样本由五个组件构成：**指令、真实图像、待评回答、自定义评分 rubric、参考答案**。
- 模型被训练为同时输出**语言反馈 + 分数决策**，而不只是分数。
- rubric 规模：从 50 条人工 rubric 出发，用 GPT-4V 扩展（每张图生成 3 条候选），再过一道「rubric 与图像是否对齐」的自动检查，最终扩到约 15K 条。
- 动机：通用指标（helpfulness / relevance / accuracy）抓不到「审美和谐」这类细粒度属性。

**关键数字**
- rubric 从 50 → 约 15,000 条；每图 3 条候选 + 对齐校验。具体性能数字见论文表格，本调研未逐项核对。

**一手来源**
- https://aclanthology.org/2024.findings-acl.672.pdf

**对文境的启示**
- 「rubric + 参考答案 + 反馈 + 分数」的四件套可以直接映射成文境的评审输入：图 + 角色卡（参考答案）+ rubric + 场景描述。
- **rubric 可以自动生成，但必须过对齐检查**：文境若按 `AssetKind` 自动生成 rubric（头像看脸、场面图看在场人物与物件），要加一步「这条 rubric 是否适用于这张图」的自检，否则会拿「有没有文字」去评一张空镜。

---

### 13.3 相似度指标：CLIP / DINO / DreamSim（廉价粗筛）

**它是什么**
不是单个产品，而是一类被广泛用于「判断两张图是否同一主体/同一风格」的嵌入指标。**方法口径**，成熟且便宜。

**怎么做**
- **CLIPScore**（0–100）：图文语义对齐度，不看画质；适合判断「图是否符合描述」。
- **CLIP / DINO 嵌入余弦相似度**：判断两张图是否同一主体，DINO 对主体形状更敏感。
- **DreamSim**：专门学习「人类感知的视觉相似度」的指标，比原始像素/PSNR 更贴近人的判断。
- 用法：先算相似度做粗筛（廉价、无 LLM 调用），再把可疑样本交给 VLM 复核。

**关键数字**
- CLIPScore 区间 0–100；其余指标无统一阈值，需按项目标定。

**一手来源**
- 指标综述（含 CLIPScore 定义）：https://huggingface.co/blog/PrunaAI/objective-metrics-for-image-generation-assessment
- 视觉生成评测资源汇总（DreamSim、CLIP/DINO 相似度等）：https://github.com/ziqihuangg/Awesome-Evaluation-of-Visual-Generation

**对文境的启示**
- 文境每张图都要过 VLM 评审的话成本与延迟都会上去。**先用 DINO/CLIP 与角色卡算相似度做粗筛**，相似度低于阈值才调 VLM，能把评审调用量压下一个量级。
- 这条与「参考图扩到 2–3 张」是配套的：参考图越多，相似度粗筛越准，VLM 复核越少。

---

## 14. 综合：文境的美术 agent 团队该怎么重组

### 14.1 输入收窄：全量事实 → 结构化三段

现在画师 agent 吃的是「全量事实」，等于没有规格。建议固定为三段，缺字段就显式写「未提供」，不要用剧情全文兜底：

| 段 | 内容 | 来源 |
|---|---|---|
| **角色卡段** | `Appearance` 七要素（gender/age 前置）+ 参考图 id 列表 + 本场景是否在场 | 剧本包 + `assets` |
| **场景段** | 地点、时间、在场角色、**关键物件/动作**（从 `world_chronicle` 或场景描述抽） | 剧本包 / 运行时事件 |
| **镜头段** | `AssetKind`、构图尾巴、画幅与尺寸档、**风格包版本** | `_KIND_TAILS` + 风格包 |

明确**不给**：剧情全文、其他角色记忆、未在场角色、上一轮对话原文。理由与腾讯访谈一致——上下文污染会让 agent 目标漂移。

### 14.2 角色与交接：Casting / Painter / Reviewer / Harness

不建议把画师拆成多个 LLM agent。建议是：

| 角色 | 类型 | 输入 | 输出 | 不许做什么 |
|---|---|---|---|---|
| **选角（Casting）** | LLM | 剧本包 / 事件 | 结构化「画面需求清单」（subject_key、kind、在场、关键物件） | 不写 prompt、不调生图 |
| **画师（Painter）** | LLM | 三段结构化输入 | prompt + negative + 参考图选择 | 不决定生成几张、不决定是否重绘 |
| **评审（Reviewer）** | VLM | 图 + 角色卡 + 需求清单 | gate 结果 + 分级分 + 失败标签 + 反馈 | 不改图、不改 prompt、不自行重跑 |
| **调度（Harness）** | 非 LLM | 上述全部 | 配额、重试、去重、状态 | 不创造内容 |

关键分工原则来自腾讯访谈：**「Agent 负责做事，Harness 负责让做事可控」**。候选张数、重绘轮次、预算上限都应属于 Harness，而不是让画师或评审自己决定——现在的 `media_image_candidates` / `media_image_regen_rounds` 已经是这个方向，保持即可。

### 14.3 评审 rubric：gate 与 graded 分离

**硬 gate（任一失败即拒）**
1. `gender_age_ok`：性别与年龄段符合 `Appearance` 硬锚点；
2. `identity_match`：与角色卡是同一人（脸型、发型、服装主特征）；
3. `presence_ok`：在场人物齐全，没有多余人物；
4. `key_props_present`：需求清单里的关键物件/动作出现；
5. `artifact_ok`：无严重畸变、无异常文字、无裁切。

**分级（0–5，用于选优而非否决）**
- 构图与景别、风格契合度、叙事清晰度、美术质量。

**失败标签枚举**（用于统计与回灌）
`wrong_gender_age` / `identity_drift` / `missing_prop` / `wrong_presence` / `style_drift` / `composition` / `low_quality` / `artifact`。

这套拆分直接对应 OpenAI cookbook 的「先 gate 后分级」与「失败打标签」，也解释了现有 `VisionReviewAgent` 为什么会给出「画得不错但锚点不符」的混合分——它把两类判断压进了一个 score。

### 14.4 风格护栏的量化

把 `DEFAULT_STYLE` 从一段固定文字升级成**带版本号的风格包**，至少包含：

- **配色分布**：主色 / 辅色 / 点缀色（可从一张授权风格样张统计，不必人工标）；
- **材质与笔触**：水墨 / 淡彩 / 线描的占比，边缘是硬线还是晕染；
- **对比度与饱和度区间**：给一个上下界，评审时可直接量；
- **正向约束词**（逐字追加）与**负向约束词**（当前缺失）；
- **`style_pack_version`**：进 prompt、进评审 rubric、**进去重键**——换版本就是换产出，不能命中旧缓存。

这条与「一张风格样张做 style reference」互补：文字护栏管下限，样张管上限。

### 14.5 与现有 `image-generation-quality.md` 草案的差异

| 草案现状 | 建议调整 | 理由 |
|---|---|---|
| ArtDirector = 编排器 + 5 组件 | 收敛为「Casting + Painter + Reviewer + Harness」 | 5 组件里有 3 个不是 agent，混在一起会让职责边界模糊 |
| 没有「选角」环节 | 新增 Casting，产出结构化需求清单 | 现在画师同时承担「理解剧情」与「写画面」，两类判断混在一个 prompt 里 |
| `VisionReviewer` 单一 score | 拆 gate / graded + 失败标签 | 见 §14.3 |
| `DEFAULT_STYLE` 一段文字 | 结构化风格包 + 版本号 | 见 §14.4 |
| 候选与重绘由 `SceneDesigner` 循环控制 | 移到 Harness，保持配额与预算在调度层 | 与腾讯访谈的 Harness 职责一致 |
| 参考图 = 1 张头像 | 角色卡多视角（正/侧/全身） | 见 §11.2 的六视角嵌入经验 |

### 14.6 不建议做的事

- **不要引入 supervisor / 任务队列**（AWS 那套是为多会话、多租户设计的；文境单 worker + 串行命令，`SceneAssetScheduler` 已足够）。
- **不要让 Reviewer 自己决定重绘**——它只产出证据，重绘由 Harness 按预算判定。
- **不要用「多生成几张随机挑」替代评审**：这与现行设计一致，GDC 数据也说明美术从业者对无评审的自动产出信任度最低。
- **不要把风格包做成训练**（LoRA/微调）：与「每篇课文临时生成角色」的成本模型冲突，这条判断不变。

---

## 15. 本轮核实边界

1. 腾讯访谈的「40% → 90%+」是**受访者口径**，未给出指标定义与测量方法，不能当作 benchmark 引用。
2. GDC 的「资产生成 19% / 程序化 10% / 玩家可见 5%」来自第三方二次分析，**未在 GDC 官方页面核实**；官方页面可核实的是 40% / 57% / 55% / 35% / 8%。
3. Ubisoft 论文的 ACM 全文未能抓取（页面拒绝），组件与数字来自 DigiPro 2026 官方议程页的摘要；论文内部的实验数字未核实。
4. Prometheus-Vision 的具体性能数字未逐项核对，只核实了方法与 rubric 规模。
5. AWS 博客未公开 QC 阈值与通过率；「agentic QC 有效」是厂商自述，没有独立评测。
6. 本文件没有做任何模型或管线的实测；§14 的重组建议是基于以上材料的工程判断，落地前应在文境自己的数据上做 A/B。

---

## 16. 本轮调研局限（合并说明）

1. **全程无实测**：三组结论都基于官方文档、论文与公开访谈，没有跑过任何模型或管线
   对比；第 7 章与第 14 章的重组建议是工程判断，落地前应在文境自己的数据上做 A/B。
2. **厂商口径与实证分开看**：腾讯「40% → 90%+」、Ubisoft 的 3 万资产与 1 秒检索、
   Hidden Door 的资产规模，均来自访谈 / 议程摘要而非可复现实验。
3. **反爬导致的缺口**：Ubisoft 的 ACM 全文抓取失败，数字取自 DigiPro 公开摘要。
4. **计费未核实**：Seedream 图层拆分是否额外计费、16 层在水墨 / 多人物场景下是否够用，
   均需实测；Qwen-Image-Edit-2511 的托管单价、Jenova 的 API 能力只有营销文案。
5. **本文与第一轮调研的关系**：第一轮
   `docs/research/realtime-ai-art-in-games-survey.md` 负责广度（案例清单、模型矩阵、
   12 条改进清单），本文负责深度（机制、数字、可落地数据模型与团队重组）。两文冲突时
   以更新的一手来源为准，并优先采信本文中标注了官方链接的数字。
