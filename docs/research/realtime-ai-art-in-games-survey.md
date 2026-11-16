# 游戏内实时 / 近实时 AI 美术生成：案例、架构与模型选型调研（2026-11-15）

> **性质**：带日期的调研快照，非规格，不追改。结论可能随模型与价格变化而过期。
> **调研日期**：2026-11-15。
> **范围**：WenJing 的配图链路（Stage2 离线 `design_assets`、Stage3 运行期
> `SceneAssetScheduler`、Ark Seedream 5.0 flash）。回答三个问题：同类产品怎么在
> 运行时出图？哪些一致性技术值得抄？哪些模型 / 架构更适合「课本插画」这个场景？
> **与已有文档的关系**：`docs/design/image-generation-quality.md` 是现行设计草案
> （P0–P3 已落地），`docs/research/volcengine-imagegen-integration.md` 是 Ark 接入
> 调研，`docs/research/branch-montage-dm-plan.md` 是场面图方案。本文不重复它们的
> 结论，只补「业界同类做法 + 模型选型 + 改进清单」。

---

## 0. 结论（先看这段）

1. **真正「运行时生成美术」的产品只有三条路**：
   - **预生成素材库 + 运行时组装 / 检索**：Hidden Door 用人工绘制的图层（paperdoll）
     按标签与向量相似度在运行时拼角色，地点图也是预生成后语义匹配；
   - **按需文生图**：AI Dungeon 的 `See` 命令，玩家或系统临时拼 prompt 出一张图；
   - **世界模型逐帧生成**：Genie 3、Decart Mirage / Oasis，毫秒级延迟，但画质、
     可控性、成本都还不适合「课文插画」。
2. **对文境最值得抄的不是「更快出图」，而是 Hidden Door 的「可组合素材 + 运行时
   组装」思想**：把「同一角色跨图一致」从概率性的 image-to-image 变成确定性的
   组装。完全照搬需要一支美术团队维护资产库，不现实；但可以取中间态——**更丰富的
   参考图 + 编辑式续画 + 分层 / 局部编辑 + 视觉评审**。
3. **一致性技术上，托管 API 已从「单参考图」进化到「多参考图 + 多角色」**：
   - Ark Seedream 5.0 pro / flash：官方最多 **10 张参考图**，支持多图输入与图层
     拆分；组图（「角色连贯、风格统一」的图像序列）在官方提示词指南中列于
     5.0 lite / 4.5 / 4.0，**5.0 pro / flash 的文档未列这一项**；
   - Google Gemini 3 Pro Image（Nano Banana Pro）：官方发布说明称最多 **14 张
     参考图**、**5 个人物**的角色一致性，1K/2K/4K；
   - Qwen-Image-Edit 2511：开源权重（Apache 2.0），多人一致性、原生 ControlNet
     条件。
   文境当前「1 张头像 + 文字锚点」处在「够用但可提升」的位置；**扩到 2–3 张参考图
   是成本最低、收益最直接的一步**。
4. **延迟上，托管 API 的「近实时」是十秒级，不是毫秒级**。Seedream 5.0 flash
   第三方实测「通常 20 秒以内」、pro「约 2 分钟」（未获官方 SLA）；这与文境
   「渐变占位、叙事不等图」的现状匹配。真要进 1 秒级必须自托管小模型
   （FLUX.2 klein 4B，Apache 2.0，RTX 5090 约 1.2 秒 / GB200 约 0.3 秒），
   与「不引入 GPU 常驻」的约束直接冲突，**不建议**。
5. **成本不是瓶颈，画质才是**。按 Ark 官方价 0.12 元/张，一篇课文 20 张图约
   2.4 元；开 2 候选 + 视觉评审约 5 元。相比 LLM 费用可以忽略，所以**应当按槽位
   选模型（草稿用 flash、终稿用 pro / 4K），而不是一味压单价**。
6. **合规是硬约束**：《人工智能生成合成内容标识办法》自 2025-09-01 施行，图片必须
   在适当位置加显著「AI 生成」显式标识、并在文件元数据加隐式标识。Ark 默认
   `watermark=true` 满足显式要求，但**转码 / 多规格可能丢元数据**，服务端要补隐式
   标识。课堂使用落在《著作权法》第二十四条第（六）项合理使用范围内（少量复制、
   不得出版发行），但「网络抓图做参考图」不在其中——现行「只用平台自有生成图做
   参考」的政策是对的。

---

## 1. 文境现状（判断基线）

现行链路（代码实证）：

```
Stage2 离线：
nodes.design_assets
  → SceneDesigner.design_scene            app/domain/game/media.py:679
    → LLMPromptWriter.write（画师转写）
    → build_generation_prompt             app/domain/game/media.py:516
    → ImageGenPort.generate               ark / openai adapter
    → 转码 → 上传 → assets 行 READY
  先生成人物头像，再用头像字节作参考图（design_assets）

Stage3 运行期：
GameRuntime 发意图（StepResult.asset_requests）
  → SceneAssetScheduler.schedule           app/services/scene_assets.py:94
  → asset_jobs 立 pending 票据
  → 后台任务 design_scene（带在场角色头像参考图）
  → asset_ready 事件推前端；失败降级为渐变占位
```

关键事实（作为后文判断约束）：

- **模型**：`doubao-seedream-5-0-flash-260915`，官方 0.12 元/张
  （`image_gen_ark.py:41`；价格见火山方舟模型价格页）。
- **参考图**：`reference_images` 以 base64 data URL 下发，Ark 最多 10 张
  （`image_gen_ark.py:59`）；当前实际只传 1 张（在场角色头像）。
- **去重**：`build_dedup_key` 含 org / 归属作用域 / subject / kind / 风格 /
  provider 版本，带参考图追加 `+ref` 后缀（`media.py:402`、`:719`）。
- **降级**：失败即占位，叙事不等图；`asset_jobs` 持久台账 + 崩溃恢复
  （`scene_assets.py` 模块 docstring）。
- **画风**：`DEFAULT_STYLE` 固定（课本插画 / 水墨 / 手绘线描淡彩），每张原样追加
  （`media.py:448`）。
- **已有质量手段**：七要素外貌锚点、头像去证件照化、参考图 image-to-image、
  候选 N 张 + VLM 视觉评审（默认 off）、教师逐场景审核。
- **明确不做**：LoRA / 微调、自托管推理、无视觉评审的多轮生成、网络抓图做参考图。
- **部署约束**：Python + FastAPI，单 worker；外部 provider 走 HTTP；不引入
  GPU 常驻组件。

**一句话诊断**：运行期的工程韧性（去重、台账、崩溃恢复、失败降级）已经做得比
大多数同类产品好；**短板在「一致性上限」和「叙事前瞻」**——现在是被动地等玩家
走到新场景才出图，且同一角色只靠一张头像参考。

---

## 2. 同类案例

### 2.1 预生成 + 运行时组装：Hidden Door（最值得研究）

Hidden Door 是一款 AI 叙事游戏，视觉上刻意做成 graphic novel / visual novel 的
样子。它的美术系统不是「运行时文生图」，而是：

- **角色 = 人工绘制的图层 + 标签 + 向量嵌入，运行时组装**。官方博客原话：
  「用 paperdoll 系统把插画师画好的图层动态组装起来，通过向量嵌入和标签匹配角色
  描述与故事上下文」；每个资产按标签与上下文打分，从高分候选里带随机性选择。
  这样能保证「单一 Hidden Door 画风」和角色头像的美感与一致性，同时又能为任意
  描述（比如「太空站哥特咖啡馆里的咖啡师」）拼出一个合理形象。
- **地点 = 预生成后语义匹配**。CEO Hilary Mason 在采访中说：团队「预生成一大批
  美术，然后把它与玩家输入的文字做语义匹配」，「美术是人画的，但在运行时组装」。
- **代价**：内容被资产库的覆盖度限制；新增风格 / 题材要美术先画。

**对文境的启示**：一致性问题的根解不是「更强的模型」，而是「把可复用的部分从
生成里拿出来」。文境不可能为每篇课文建资产库，但可以借鉴两点：

1. **角色卡固化为「文本 + 图像」双通道**（已在做），并让参考图覆盖多个角度；
2. **同一角色的新场景优先「编辑」而不是「重生成」**——用已有图做底图改场景，
   比每次从零生成更容易保持身份。

### 2.2 按需出图：AI Dungeon 的 `See`

AI Dungeon 的官方帮助文档写明：玩家用 `See` 命令可以临时出图；**prompt 留空时，
系统会根据最近几次行动、story cards、plot essentials 自动拼 prompt**。TechCrunch
2022 年的实测指出问题：风格不统一、细节会丢（提示里有「一捆钱」但图里没有）、
模型会抓关键词而忽略上下文。

**对文境的启示**：

- 「自动拼 prompt」这件事文境已经做了（画师层 + `build_generation_prompt`），
  而且做得更结构化（外貌七要素、构图尾巴、长度预算）。
- AI Dungeon 的失败模式正是文境视觉评审要拦的东西：**图文不符**。文境现在的
  `VisionReviewAgent` 只看人物锚点 / 性别年龄 / 构图，**没有检查「情节关键物件
  是否出现」**——这是可以补的评审维度。

### 2.3 离线资产平台：Scenario / Layer / Rosebud

- **Scenario**（官方定价页）：Starter $15/mo、Pro $45/mo、Max $75/mo；Pro 起可
  训练自定义模型（风格 / 角色 / 编辑 LoRA），训练图 **5 张起**，Pro 最多 25 张、
  Max 50 张、Enterprise 100 张；提供 REST API、webhook、Unity 插件。
- **Rosebud AI**（官方页面）：2D 精灵 / 动画 / 3D / 天空盒生成器，产物直接是
  Unity / Godot / Unreal / Roblox 可读格式；PixelVibe 已并入统一工具集。
- **Layer AI**：同类，主打移动游戏批量生产与消费制计费。

**对文境的启示**：这类平台解决的是「一个工作室有稳定美术方向，要批量产资产」。
文境的场景是「每篇课文临时生成一套角色」，**没有稳定的训练集，也不值得为单篇
课文训练 LoRA**——与现行「不做 LoRA」的判断一致。但它们的「风格模型 + 参考集」
思路可以降级使用：**用一张固定的「课本插画风格样张」做 style reference**，比纯
文字风格段更稳。

### 2.4 世界模型：Genie 3 / Decart Mirage / Oasis

- **Genie 3**（Google DeepMind 官方博客，2025-08-05）：文本 prompt 生成可交互
  世界，**720p、24 fps、一致性维持数分钟**；目前是研究预览，只对少量学术 / 创作
  者开放，**没有公开 API**。
- **Decart MirageLSD**：逐帧实时视频转换，Wired 实测 **768×432、20 fps、每帧约
  100 ms**；Oasis 是可玩的 Minecraft 风格实时生成世界。

**对文境的启示**：世界模型是「连续画面」的思路，解决的是「玩家每动一下画面就
变」；文境需要的是「一个场景一张静态插画」，用不上。**短期内只作为技术观察，
不进入选型**。

### 2.5 角色引擎：Inworld

Inworld 的 Character Engine / Runtime SDK 做的是 NPC 的对话、情绪、记忆、行为，
不是美术生成；它明确把自己定位为「角色与逻辑层」，与 Unreal / Unity 的
「环境与视觉层」互补。

**对文境的启示**：如果未来要做「NPC 自主发起行为」，Inworld 是架构参考；但配图
链路不应期待它来解决。文境现在的 NPC 反应 / 导演 / 世界构建分工与它同构。

### 2.6 引擎侧神经渲染：NVIDIA RTX Neural Shaders / Roblox Cube

- **NVIDIA RTX Neural Shaders**（官方技术博客）：把小型神经网络放进 shader，
  做纹理压缩（Neural Texture Compression 省最多 7–8 倍显存）、复杂材质近似
  （Neural Materials 快最多 5 倍）、辐射缓存。
- **Roblox Cube 3D**（官方 newsroom + GitHub）：开源 3D 生成基础模型，3D
  tokenization + 自回归生成，先出 mesh API，后续做场景布局。

**对文境的启示**：这些是 3D / 实时渲染管线的东西，与 2D 课文插画不在一个层面。
**只作为「如果将来做 3D 课堂场景」的储备**，现在不相关。

---

## 3. 架构模式：运行时出图的可抄清单

| 模式 | 做法 | 文境现状 | 建议 |
|------|------|----------|------|
| **预生成 / 前瞻预取** | 在玩家到达前，根据叙事图提前生成下一批场景图 | **缺**：只在进入新场景后发意图 | 引擎已知下一场景 / 分支候选，可在命令提交后顺带排程；去重键保证不重复付费 |
| **分级生成** | 先出低分辨率草稿，再细化 / 超分 | **缺**：一次直出终稿 | flash 先出 1K，教师审核通过后再用 pro / 2K 重绘；或对「人物在场」的图才用高质量档 |
| **占位与骨架屏** | 图没来之前用渐变 / 纯色占位，叙事继续 | **已有**：失败降级为渐变 | 保持；可加「生成中」的轻量提示，避免玩家以为没图 |
| **缓存与去重键** | 同一 (org, 场景, kind, 风格, 模型) 只付一次 | **已有**：`build_dedup_key` + `+ref` 后缀 | 保持；新增 provider / 模型 / 参考图组合时记得 bump |
| **请求合并 / 取消** | 同一 scene_key 在途只跑一个 | **已有**：进程内 `_inflight` + `asset_jobs` 唯一约束 | 保持 |
| **超时与降级** | provider 慢 / 失败不阻断主流程 | **已有**：后台任务 + FAILED 记录 + TTL 恢复 | 保持 |
| **队列与配额** | 每会话 / 每 org 生图上限 | **已有**：`MediaQuotaPort.try_acquire` + `max_images_per_session` | 保持 |
| **失败重试与幂等** | 崩溃后重排，`abandoned` 可重来 | **已有**：`asset_jobs` 的 pending / failed / abandoned 三态 | 保持 |
| **图文对齐校验** | 生成后检查关键物件 / 动作是否出现 | **部分**：视觉评审只看人物锚点 / 性别年龄 / 构图 | 增加「情节关键元素」评审维度；只对含人物的场面图开 |
| **同一角色跨图编辑** | 用已有图做底图改场景，而不是重生成 | **缺**：每次都从 prompt 重生成 | 新增「编辑式续画」路径：头像 / 上一张场面图作底图 + 场景指令 |
| **多镜头组图** | 一次调用生成同场景的多个镜头 / 连续画面 | **缺**：一 subject 一张 | Seedream 5.0 lite / 4.5 / 4.0 官方提示词指南列有组图；**5.0 pro / flash 未列**，用前需实测 |

**结论**：文境的「韧性」已经到位，缺的是「前瞻」和「一致性上限」。最值得补的
三件事按顺序是：**更丰富的参考图 → 编辑式续画 → 叙事前瞻预取**。

---

## 4. 一致性技术：能力、代价与适配

### 4.1 托管 API 的参考图能力（2026-11 现状）

| 方案 | 参考图 / 角色能力 | 接入方式 | 单价量级 | 自托管 | 适配文境 |
|------|------------------|----------|----------|--------|----------|
| **Ark Seedream 5.0 flash / pro** | 官方最多 10 张参考图；多图输入；组图（角色连贯、风格统一）；图层拆分 | HTTP（现有 adapter） | flash 0.12 元/张；pro 0.30 元/张（≤2.61M 像素） | 否 | **首选**：已在用，升级成本最低 |
| **Gemini 3 Pro Image（Nano Banana Pro）** | 官方发布说明：最多 14 张参考图、5 个人物一致、1K/2K/4K | Google API | $0.134/1K–2K；$0.24/4K | 否 | 备选：多角色一致性最强，但要走新 provider |
| **Gemini 3.1 Flash Image（Nano Banana 2）** | 多图参考、编辑一致性 | Google API | $0.067/1K；$0.101/2K；$0.151/4K | 否 | 备选：比 Pro 便宜，适合草稿 |
| **Gemini 2.5 Flash Image（Nano Banana）** | 单 / 多图编辑、角色一致性 | Google API | $0.039/张（官方；2027-03-15 停服） | 否 | 不推荐新接入（已弃用） |
| **FLUX Kontext pro / max** | 单图编辑、最多 4 张参考 | BFL API | $0.04 / $0.08（第三方价目表） | 否 | 备选：编辑式续画便宜 |
| **FLUX.2 klein 4B / 9B** | 统一生成 + 编辑 + 多参考；亚秒级 | API 或自托管 | $0.014–0.015/张（官方 release notes） | **是**（4B Apache 2.0，约 8–13GB 显存） | 不建议：与「无 GPU 常驻」冲突 |
| **Qwen-Image-Edit 2511** | 多图输入、多人一致性、原生 ControlNet 条件 | 开源权重 / 云 API | 视托管方 | **是**（Apache 2.0） | 观望：中文场景强，但需自托管或第三方云 |
| **Ideogram Character** | **1 张**参考图，锁定脸 / 发型 | Ideogram API | $0.10–0.20/张（官方价目表） | 否 | 不推荐：单参考图弱于现有方案 |
| **Midjourney Omni-Reference** | 1 张参考图 + `--ow` 权重 | Discord / 无正式 API | 订阅制 | 否 | 不推荐：不适合服务端集成 |

### 4.2 自托管适配器：为什么仍不建议

- **IP-Adapter / InstantID / PuLID / PhotoMaker** 都是「单图身份保持」的研究路线，
  需要自托管推理；PuLID 论文（arXiv:2404.16022）自称在 ID 保真与「不破坏原模型
  风格」之间更好，InstantID（arXiv:2401.07519）主打 zero-shot；但它们都依赖
  InsightFace 等组件（商用许可需单独确认），且要 GPU 常驻。
- **LoRA / DreamBooth** 需要每角色 10–30 张训练图与训练时间，与「每篇课文临时
  生成角色」的成本模型冲突。
- **结论**：保持「不自托管、不训练」的边界；把一致性收益交给托管 API 的多参考图
  与编辑能力。

### 4.3 一条容易忽略的经验：编辑优于重生成

Nano Banana / Kontext / Qwen-Image-Edit 这类「指令编辑」模型，在同一角色的新场景
上通常比「同 prompt 重生成」更稳：底图提供了身份与画风的强约束，模型只需要改
场景。代价是每次编辑都要带上底图（payload 变大），以及可能「改不动」大构图。

文境已有 `exclude_asset_ids` / `exclude_content_hashes` 的「重生成」语义，但
没有「以某张图为底图编辑」的路径。**这是最值得新增的一条 provider 能力**。

### 4.4 一个反例：语义覆盖

Google 支持论坛有用户报告 Nano Banana Pro 在编辑公众人物照片时会「按自己知道
的样子」改年龄 / 外貌（semantic override）。对虚构角色风险小，但说明「参考图
不是硬约束」；**视觉评审仍然是必要的兜底**。

---

## 5. 延迟与成本

### 5.1 量级对比

| 方案 | 延迟量级 | 单价 | 来源 |
|------|----------|------|------|
| Ark Seedream 5.0 flash | 约 20 秒内（第三方实测，未获官方 SLA） | 0.12 元/张 | 火山方舟模型价格页（官方）；延迟为第三方 |
| Ark Seedream 5.0 pro | 约 2 分钟（第三方） | 0.30 元/张（≤2.61M 像素） | 同上 |
| Gemini 3.1 Flash Image | 未核实 | $0.067/1K | Google 官方定价页 |
| Gemini 3 Pro Image | 未核实 | $0.134/1K–2K；$0.24/4K | Google 官方定价页 |
| GPT Image 1.5 | 未核实 | $0.009（low）– $0.20（high，竖版） | OpenAI 官方模型页 |
| FLUX Kontext pro / max | 未核实 | $0.04 / $0.08 | 第三方价目表（LiteLLM） |
| FLUX.2 klein 4B | 约 0.3 秒（GB200）/ 1.2 秒（RTX 5090） | $0.014/张 | BFL 官方模型页 |
| Ideogram Character | 未核实 | $0.10–0.20/张 | Ideogram 官方定价页 |

### 5.2 实时化技术：值不值得

- **LCM**（arXiv:2310.04378）：1–4 步出图，是「少步蒸馏」的基础工作。
- **SDXL-Lightning**（arXiv:2402.13929）：渐进式对抗蒸馏，1/2/4/8 步。
- **StreamDiffusion**（arXiv:2312.12491）：管线级优化，RTX 4090 上 1 步 img2img
  延迟 10.65 ms、最高 91 fps。
- **FLUX.2 klein**：官方亚秒级，4B 可在消费级 GPU 跑。

**判断**：这些都需要自托管 GPU。文境的「近实时」定义是「玩家进入场景后十秒级
补图，先看渐变占位」，**当前托管 API 已经满足**；把延迟从 20 秒压到 1 秒不会改变
玩法，却会引入 GPU 运维。**不建议**为实时化自托管。

### 5.3 成本其实不是约束

按一篇课文 20 张图估算：

- 全用 flash：20 × 0.12 = **2.4 元**；
- 开 2 候选 + 1 轮重绘：最多 60 张 ≈ **7.2 元**；
- 头像 / 终稿用 pro：假设 8 张 pro + 12 张 flash ≈ 8 × 0.30 + 12 × 0.12 = **3.84 元**。

相比 LLM 调用费用可以忽略。**结论：应该按槽位选模型（草稿 flash、终稿 pro），
而不是全局压单价。**

---

## 6. 画质与风格

### 6.1 课本插画 / 水墨 / 淡彩适合什么

- **Ark Seedream 5.0 官方提示词指南**明确支持「参考风格」「参考人物形象」
  「参考虚拟实体形象」等参考图用法，以及多图输入（替换 / 组合 / 迁移）和组图
  （「角色连贯、风格统一」的图像序列）。这意味着**文境可以用一张固定的风格样张
  做 style reference**，而不是只靠文字风格段。
- **中文文本渲染**是 Seedream 5.0 的强项（官方宣传原生多语种），但课文插画通常
  不需要图内文字，**构图尾巴里的「无文字无 logo」仍然要保留**。
- **FLUX 2 系列据第三方汇总不支持 negative prompt**（invideo 博客，未在 BFL
  官方文档核实），所以「非照片写实」这类负向措辞对 FLUX 可能无效；文境当前以
  正向描述为主（`DEFAULT_STYLE` 的写法）是正确的，换 provider 时不要依赖负向词。

### 6.2 风格一致性的三层手段

1. **固定 style block 逐字前置**（已有）：`DEFAULT_STYLE` 参与去重键，改画风即
   改产出；
2. **style reference 图**（可新增）：一张教师认可的「课本插画样张」作为额外参考
   图，比文字更稳；
3. **style LoRA**（不建议）：需要训练集与托管，与「每篇课文临时生成」冲突。

### 6.3 质量分级

- **草稿 / 候选**：flash 1K，便宜、快，用于评审和教师初筛；
- **终稿**：pro 2K（官方文档确认）；更高分辨率档（3K/4K）只见于第三方资料，
  官方 5.0 pro 文档未列，使用前需实测；
- **注意**：Ark 的像素下限 921 600、pro 低价档上限 261 万像素，尺寸档位要与
  `_ARK_LIFT_SIZES` 对齐（`image_gen_ark.py:51`）。

---

## 7. 合规

### 7.1 中国 AI 生成内容标识

- **《人工智能生成合成内容标识办法》**（国家网信办等四部门，2025-03-14 发布，
  **2025-09-01 施行**）：
  - 第四条：图片应在**适当位置添加显著的提示标识**；下载 / 复制 / 导出时文件
    必须保留显式标识；
  - 第五条：文件元数据中必须添加**隐式标识**（生成合成属性、服务提供者名称或
    编码、内容编号），鼓励数字水印；
  - 第八条：用户协议中说明标识方法与样式；
  - 第九条：用户申请无显式标识内容的，需协议界定责任并留存日志**不少于 6 个月**；
  - 第十条：任何组织和个人不得恶意删除、篡改、伪造、隐匿标识。
- **GB 45438-2025**《网络安全技术 人工智能生成合成内容标识方法》同日施行；
  据 PwC 与友盟的合规解读，图片显式标识的文字高度不应低于画面最短边长度的 5%
  （未直接读到国标原文，落地前以标准文本为准）。
- **对文境**：Ark 默认 `watermark=true` 满足显式标识；但 `response_format=b64_json`
  + 服务端转码（Pillow → webp / avif 多规格）**可能丢元数据**，需要在转码后补写
  隐式标识字段。教师上传的图若为 AI 生成，同样要标识。

### 7.2 课堂场景的版权边界

- **《著作权法》第二十四条第（六）项**：为学校课堂教学或者科学研究，翻译、改编、
  汇编、播放或者**少量复制**已经发表的作品，供教学或者科研人员使用，**但不得
  出版发行**——属于合理使用，需指明作者 / 作品名称。
- **边界**：
  - 课堂内使用生成的插图，落在合理使用范围内的可能性较高；
  - **网络抓取的角色图 / 插画作为参考图喂给生图模型**，涉及复制 / 改编，且
    难以主张合理使用——现行「只用平台自有生成图做参考」的政策应保持；
  - 教师上传素材需确认授权并记录来源（现有 `AssetCredit` / `source` 字段可承载）。
- **注意**：AI 生成物的著作权归属在国内仍有争议，不能把「生成图」当作可自由
  再许可的资产；平台条款应明确使用范围。

---

## 8. 给文境的改进清单（按收益 / 成本排序）

| # | 改进 | 改哪一层 | 预期收益 | 成本 / 风险 | 冲突 | 结论 |
|---|------|----------|----------|-------------|------|------|
| 1 | **参考图从 1 张扩到 2–3 张**（头像 + 全身 / 服装细节） | provider（`design_assets` / `SceneAssetScheduler`） | 身份与服装一致性明显提升 | payload 变大；Ark 10 张上限内无额外费用 | 无 | **现在就能做** |
| 2 | **编辑式续画**：同角色新场景用「底图 + 场景指令」而非重生成 | provider（新增 `edit` 路径） | 比同 prompt 重生成更稳，减少「换脸」 | 需新 adapter 分支与去重键（`+edit`）；大构图可能改不动 | 需确认 Ark / 其他 provider 的编辑接口 | **现在就能做（先做 PoC）** |
| 3 | **叙事前瞻预取**：引擎已知下一场景 / 分支候选，提前排程 | 调度层（`SceneAssetScheduler`） | 玩家到达时图已就绪，感知延迟下降 | 可能为「不会走到的分支」付费；用去重键 + 上限控制 | 无 | **现在就能做** |
| 4 | **草稿 → 终稿分级**：flash 1K 先出，审核后 pro 2K 重绘 | provider / 调度 | 终稿质量提升，草稿成本低 | 需要「重绘」触发点（教师审核 / 终稿标记） | 无 | **现在就能做** |
| 5 | **视觉评审按需开**：只对「含人物的场面图」开，头像 / 空镜不开 | 审核层（`VisionReviewAgent`） | 省钱且覆盖主要故障（性别 / 年龄 / 换脸） | 需要按 kind 配置 | 无 | **现在就能做** |
| 6 | **评审增加「情节关键元素」维度**：检查关键物件 / 动作是否出现 | 审核层 | 减少 AI Dungeon 式「图文不符」 | rubric 变长，VLM 成本略增 | 无 | **现在就能做** |
| 7 | **组图生成**：一次调用出同场景多镜头 / 连续画面 | provider | 分镜 / 连续场景一致性更好 | 需要新 prompt 形态与产物拆分；5.0 pro / flash 文档未列组图，需实测或换档 | 需确认 provider 能力 | **需要新 provider 能力** |
| 8 | **隐式标识补齐**：转码后写元数据 AIGC 字段 | 合规 / 转码层 | 满足《标识办法》第五条 | 需要按 GB 45438-2025 实现 | 无 | **现在就能做（合规优先）** |
| 9 | **风格参考图**：一张课本插画样张作 style reference | prompt / provider | 画风更稳 | 需要一张授权样张 | 无 | **可做** |
| 10 | **自托管 klein / StreamDiffusion** | 基础设施 | 亚秒级出图 | GPU 常驻、运维复杂 | 与单 worker / 无 GPU 冲突 | **不建议** |
| 11 | **LoRA / 角色训练** | 基础设施 | 极强一致性 | 每角色 10–30 张训练图 + 训练时间 | 与「每篇课文临时角色」冲突 | **不建议** |
| 12 | **世界模型（Genie / Mirage）** | — | 连续画面 | 无公开 API、不可控 | 与静态插画需求不匹配 | **观望** |

---

## 9. 方案对比矩阵

| 方案 | 一致性能力 | 延迟 | 单价 | 接入方式 | 自托管 | 对文境的适配 |
|------|-----------|------|------|----------|--------|--------------|
| Ark Seedream 5.0 flash（现状） | 中（10 参考图 + 文字锚点） | 十秒级 | 0.12 元/张 | 已有 HTTP adapter | 否 | **首选** |
| Ark Seedream 5.0 pro | 中高（参考图更严、2K） | 分钟级 | 0.30 元/张 | 同上 | 否 | 终稿 / 头像 |
| Gemini 3 Pro Image | 高（14 参考图 / 5 人物） | 未核实 | $0.134–0.24 | 新 provider | 否 | 多角色场景备选 |
| Gemini 3.1 Flash Image | 中高 | 未核实 | $0.067/1K | 新 provider | 否 | 草稿备选 |
| FLUX Kontext pro | 中（编辑式） | 未核实 | $0.04 | 新 provider | 否 | 编辑式续画备选 |
| FLUX.2 klein 4B | 中（多参考） | 亚秒级 | $0.014 | API / 自托管 | 是 | 不建议（GPU 常驻） |
| Qwen-Image-Edit 2511 | 高（多人） | 未核实 | 视托管方 | 自托管 / 云 | 是 | 观望 |
| Ideogram Character | 中（单参考） | 未核实 | $0.10–0.20 | 新 provider | 否 | 不推荐 |
| Midjourney Omni-Reference | 中（单参考） | 未核实 | 订阅制 | 无正式 API | 否 | 不推荐 |
| Hidden Door 式图层组装 | 极高（确定性） | 近零 | 美术人力 | 自建资产库 | — | 长期方向，短期不可行 |
| 世界模型（Genie 3 / Mirage） | 低（可控性差） | 毫秒级 | 未公开 | 无公开 API | — | 观望 |

---

## 10. 参考来源（本轮实际抓取，2026-11-15）

**本项目**
- `docs/design/image-generation-quality.md`（现行设计草案）
- `docs/research/volcengine-imagegen-integration.md`（Ark 接入调研）
- `docs/research/branch-montage-dm-plan.md`（场面图方案）
- `backend/app/domain/game/media.py`（`SceneDesigner` / prompt 构建 / 去重键）
- `backend/app/services/scene_assets.py`（运行期调度器）
- `backend/app/infrastructure/media/image_gen_ark.py`（Ark adapter）

**案例**
- Hidden Door 官方博客《How the Hidden Door Humans Make Characters》：
  https://www.hiddendoor.co/blog/art-system-characters-behind-the-scenes
- Hidden Door 地点美术流程：
  https://www.hiddendoor.co/blog/location-art-design-inspiration-process
- GamesBeat 采访（预生成 + 语义匹配、运行时组装）：
  https://gamesbeat.com/hidden-door-unveils-new-art-style-for-its-ai-based-narrative-game
- AI Dungeon 官方帮助《How do I create pictures in AI Dungeon?》：
  https://help.aidungeon.com/faq/how-do-i-create-pictures-in-ai-dungeon
- TechCrunch 2022《Latitude brings AI-generated artwork to AI Dungeon》：
  https://techcrunch.com/2022/09/15/latitude-brings-ai-generated-artwork-to-ai-dungeon
- Scenario 官方定价：https://www.scenario.com/pricing
- Scenario 模型训练说明：https://help.scenario.com/articles/5151772792-basics-of-model-training
- Rosebud AI 资产工具：https://rosebud.ai/ai-game-assets
- Google DeepMind《Genie 3: A new frontier for world models》：
  https://deepmind.google/blog/genie-3-a-new-frontier-for-world-models
- Decart MirageLSD 延迟（Wired 转述）：
  https://www.etcentric.org/decart-ais-mirage-transforms-live-stream-video-in-real-time
- Inworld 官方博客（Unreal AI Runtime）：
  https://inworld.ai/blog/introducing-unreal-ai-runtime-sdk
- NVIDIA RTX Neural Rendering：
  https://developer.nvidia.com/blog/nvidia-rtx-neural-rendering-introduces-next-era-of-ai-powered-graphics-innovation
- Roblox Cube 3D：
  https://about.roblox.com/newsroom/2025/03/introducing-roblox-cube
- Roblox Cube GitHub：https://github.com/Roblox/cube

**模型与价格**
- 火山方舟模型价格（Seedream 5.0 flash 0.12 / pro 0.30 元）：
  https://www.volcengine.com/docs/ark/model-pricing
- 火山方舟 Seedream 4.0–5.0 提示词指南（参考图 / 多图 / 组图）：
  https://www.volcengine.com/docs/ark/seedream-4-0-5-0-prompt-guide
- 火山方舟 Seedream 5.0 pro 教程（10 张参考图、尺寸档位）：
  https://www.volcengine.com/docs/ark/seedream-5-0-pro
- Google Gemini API 定价（2.5 Flash Image / 3.1 Flash Image / 3 Pro Image）：
  https://ai.google.dev/gemini-api/docs/pricing
- OpenAI GPT Image 1.5 模型页（$0.009–$0.20）：
  https://developers.openai.com/api/docs/models/gpt-image-1.5
- OpenAI 图像生成指南（价格表）：
  https://developers.openai.com/api/docs/guides/image-generation
- Black Forest Labs 定价：https://bfl.ai/pricing
- FLUX.2 [klein] 官方模型页（亚秒级、显存、$0.014 起）：
  https://bfl.ai/models/flux-2-klein
- FLUX.2 [klein] 官方博客：
  https://bfl.ai/blog/flux2-klein-towards-interactive-visual-intelligence
- BFL release notes（klein 价格）：
  https://docs.bfl.ml/release-notes
- Ideogram 定价（Character Reference $0.10–0.20）：
  https://ideogram.ai/pricing
- Ideogram Character 功能页：https://ideogram.ai/features/character
- Qwen-Image-Edit 官方博客：https://qwenlm.github.io/zh/blog/qwen-image-edit
- Qwen-Image-Edit-2511 ComfyUI 文档（多人一致性）：
  https://docs.comfy.org/zh/tutorials/image/qwen/qwen-image-edit-2511

**一致性与加速（论文）**
- PuLID（arXiv:2404.16022）：https://arxiv.org/html/2404.16022v2
- InstantID（arXiv:2401.07519）：https://arxiv.org/html/2401.07519v1
- SDXL-Lightning（arXiv:2402.13929）：https://arxiv.org/html/2402.13929v3
- StreamDiffusion（arXiv:2312.12491）：https://arxiv.org/html/2312.12491v1
- LCM（arXiv:2310.04378，经综述引用）：https://arxiv.org/abs/2310.04378

**合规**
- 《人工智能生成合成内容标识办法》原文（中国网信网）：
  https://www.cac.gov.cn/2025-03/14/c_1743654684782215.htm
- 新华网发布说明：https://www.news.cn/politics/20250314/b7a24028f2924b7681e6ed1bfbd8fade/c.html
- 《著作权法》第二十四条（国家版权局）：
  https://www.ncac.gov.cn/xxfb/flfg/flfg_532/202103/t20210309_50530.html

---

## 11. 调研局限

1. **延迟数字大多未核实**：Seedream flash / pro 的「20 秒 / 2 分钟」来自第三方
   文档，不是官方 SLA；Gemini / OpenAI / FLUX 的端到端延迟没有官方承诺。
2. **价格存在口径差异**：Ark 官方价是人民币、按像素档位；USD 价格来自各厂官方
   定价页，但第三方聚合站（LiteLLM、CostGoat）与实际账单可能不同；FLUX Kontext
   的 $0.04 / $0.08 来自第三方价目表，BFL 官方页面只给了计算器默认费率。
3. **Nano Banana Pro 的 14 张参考图 / 5 人物**来自 Google 发布说明的转述
   （Simon Willison 博客引用官方文案），未直接读到 Google 官方文档原文。
4. **Unity Muse 的现状**未核实（有二手消息称将被 Unity AI 取代），本文未采信。
5. **没有做实测**：本文没有跑过任何模型对比，结论基于官方文档与公开资料；
   「编辑优于重生成」「参考图扩到 2–3 张更稳」需要文境自己做 A/B 才能定论。
6. **合规部分不是法律意见**：合理使用的边界、AI 生成物著作权归属在司法实践中
   仍在变化，落地前应咨询法务。
