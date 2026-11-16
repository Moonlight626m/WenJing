# 配图质量与画师 Agent 设计（2026-11-10 草案）

> 状态：设计草案。本文针对三个实测问题提出管线改造，P0–P3 均已落地（2026-11-10）。
> 业界调研（2026-11-10）结论见 §7；Ark 参考图参数已实测 + 官方文档核验。

## 0. 决策摘要

1. **外貌契约升级为七要素**：`Appearance` 新增 `gender` / `age` 两个硬锚点
   （P0 已落地）。性别与年龄段是生图模型的人物先验，只靠服饰/五官推断会出
   「男画成女、中年画成青年」的事故。
2. **头像去证件照化**（P0 已落地）：构图从「单人正面半身」改为「四分之三侧身、
   姿态自然、背景可带环境暗示」。
3. **画师层升级为「画师编排器」（ArtDirector）**：角色卡 → 候选生成 → 视觉
   评审 → 带反馈重绘。现有 `LLMPromptWriter` 只是其中的 prompt 转写环节。
4. **参考图一致性**（P1 已落地）：每个角色先生成头像，作为该角色所有场面图/
   分支图的参考图输入（image-to-image）。Ark Seedream 5.0 的 `image` 参数
   已实测通过（base64 data URL，HTTP 200），官方文档核验：string/string[]、
   URL 或 base64、5.0 pro/flash 最多 10 张。
5. **多轮生成只在有视觉评审时启用**：纯文本 LLM 无法判断生成图质量，
   「多生成几张随机挑」等于烧钱抽奖；没有视觉评审就不开候选轮次。
6. **教师逐场景审核**：复用既有 `asset_ops`（重生成/检索替换/上传/删除），
   补「按场景/角色分组的章节视图」，不新造审核链路。

## 1. 现状与根因（代码实证）

链路：

```
nodes.design_assets
  → SceneDesigner.design_scene            (app/domain/game/media.py)
    → LLMPromptWriter.write               (app/domain/game/prompt_writer.py)
    → build_generation_prompt             (风格段 + 构图尾巴)
    → ImageGenPort.generate               (ark / openai adapter)
    → 转码 → 上传 → assets 行 READY
```

根因逐条对应实测现象：

| 现象 | 根因 |
|------|------|
| 性别/年龄错 | `Appearance` 无 gender/age；画师只能从背景文字推断，模型按服饰先验猜 |
| 同一角色跨场景不一致 | 每个 subject 独立生成；无参考图、无固定 seed、无角色卡；只有文字锚点 |
| 头像死板 | `_KIND_TAILS[AVATAR]` 与画师 prompt 写死「半身正面」，等价于证件照指令 |
| 多轮滚动缺失 | `_generate` 只生成 1 张；`ImageReviewerPort` 只用于检索候选，且仅看元数据 |

另：画风一致性其实已有基础——`DEFAULT_STYLE` 固定（课本插画/水墨/淡彩），
风格段每张原样追加；不一致主要来自**人物**而非**画风**。

## 2. P0（已落地）

- `contracts/script.py::Appearance` 增加 `gender` / `age`；
- `domain/prompts/character_design.py` 升 v5：外貌七要素、gender/age 硬锚点、
  输出契约与自检同步；
- `domain/game/prompt_writer.py` 升 `scene_prompt.v3`：
  - `APPEARANCE_FIELDS` 七字段，渲染顺序 gender/age 先于五官（先定人物先验）；
  - `ANCHOR_RULES` 增加「性别年龄不得按服饰/情节改换」「同一角色跨图同一张脸、
    同一年龄段、同一套服装」；
  - 头像构图改为四分之三侧身、姿态自然、背景可带环境暗示；
- `media.py::_KIND_TAILS[AVATAR]` 同步去证件照化；
- 契约导出、前端 `types.ts` 手工镜像同步；prompt v5 覆盖行已 seed；
- 测试：`test_contracts` / `test_prompt_bundles` / `test_prompt_writer` /
  `test_media_*` / `test_scene_designer` / `test_workflow_assets` 全绿。

**效果边界**：P0 能显著降低性别/年龄错误、改善头像观感；但跨图一致性仍只靠
文字锚点，属于「同一个人设」而非「同一张脸」。

## 2.1 P1（已落地）：角色参考图一致性

- `ImageGenPort.generate(..., reference_images=())`：可选参考图字节；
- Ark adapter：`image` 字段 = base64 data URL 数组（最多 10 张），
  基类（OpenAI 形状）忽略该参数；
- `ObjectStoragePort.get`：服务端内部读取（只给参考图复用，不经对外契约）；
  S3/Null 适配器同步实现；
- `SceneDesigner.design_scene(..., reference_images=())`：
  - prompt 末尾追加「人物外观须与参考图一致」约束段（计入长度预算）；
  - 去重键追加 `+ref` 后缀——带参考图是不同产出，不命中纯文生图缓存；
- `design_assets` **先生成人物头像**，再用 `SceneDesigner.asset_bytes`
  取回头像字节，作为该角色所在场景/分支的参考图；
- **运行期 Stage3 配图同样带参考图**：引擎从剧本包的 `avatar_asset` 取在场角色
  头像 id（`SceneAssetIntent.reference_asset_ids`），`SceneAssetScheduler`
  读字节后作为 `design_scene(reference_images=…)` 下发；参考图 id 不落
  `asset_jobs`，崩溃恢复重排时退化为纯文生图（可接受降级）；
- 测试：Ark payload、SceneDesigner 透传与缓存失效、调度器参考图解析/降级、
  端口形状。

**效果边界**：参考图能锁住「同一张脸/同一套服装」，但仍是概率性对齐；
极端构图（背影、遮挡）仍需 P2 的视觉评审兜底。

## 3. 目标架构：画师编排器（ArtDirector）

```
ArtDirector（新增，编排层）
├─ PromptWriter        已有：节拍+锚点 → 画面描述
├─ CharacterSheet      新增：角色卡（头像先行，产出参考图 + 固定描述）
├─ CandidateGenerator  新增：同一 subject 生成 N 张候选
├─ VisionReviewer      新增：VLM 视觉评审（一致性/性别年龄/构图/画质）
└─ RetryPolicy         新增：不合格 → 带评审意见重绘，预算上限
```

### 3.1 角色卡（CharacterSheet）

1. 剧本定稿后**先生成角色头像**（每个 playable/NPC 一张）；
2. 头像产物同时作为该角色的**参考图**，后续所有场面图/分支图调用生图时附带；
3. 头像的画面描述（画师转写结果）固化为角色卡文本，与 `Appearance` 锚点一起
   逐字进入每张图的 prompt——文本 + 图像双通道保证一致。

依赖：`ImageGenPort` 增加可选 `reference_images`；Ark adapter 增加 `image`
字段（base64 data URL）。**已实测通过**（2026-11-10，一次探测请求 HTTP 200）；
官方文档核验 5.0 pro/flash 最多 10 张、单图 ≤30MB。provider 不支持时基类忽略
该参数，退化为纯文本锚点（P0 现状）。

### 3.2 候选与视觉评审

- 每个 subject 生成 N 张（建议 2–3，按配额可调）；
- `VisionReviewer` 输入：候选图 + 角色卡锚点 + 情节描述 + 构图要求；
  输出结构化评分：`{character_match, gender_age_ok, composition_ok, quality, reason}`；
- 取最高分且过阈值者；全不合格则带评审意见重绘一次（预算上限 1–2 轮）；
- **前提**：需要视觉模型。当前 `LLMService` 的 `Message` 是 `dict[str, str]`，
  只支持文本；需扩展多模态通道（图片 base64 进 content 数组），并确认 provider
  有可用的视觉档。没有视觉模型时，本阶段**不启用**。

### 3.3 教师逐场景审核

- 现有：`final_gate` 的 `GateEdits.asset_ops` 已支持按 `subject_key`
  重新生成 / 检索替换 / 上传 / 删除（#49），生效于 approve；
- 补齐：前端审阅面板按「场景 / 分支 / 角色」分组展示配图，逐槽位重绘；
  不需要新的后端审核链路；
- 可选：把「重绘」从终审闸扩展到运行期（教师结束课堂前），复用同一 `design_scene`
  的 `exclude_asset_ids` 语义。

## 4. 分阶段与成本

| 阶段 | 内容 | 成本/风险 |
|------|------|-----------|
| P0（已完成） | 七要素锚点 + 头像构图 | 仅 prompt/契约变更，无新增付费调用 |
| P1（已完成） | 参考图一致性（角色卡 → image-to-image） | `image` 参数已实测；每张图 payload 变大；provider 不支持时自动退化 |
| P2（已完成） | 候选 N 轮 + 视觉评审 + 重绘回路 | 配置 `WENJING_MEDIA_IMAGE_VISION_REVIEW=on`（默认 off）；生图成本 ×candidates |
| P3（已完成） | 教师逐场景审核 UI | 审批面板改章节式分组：人物头像（一致性源头）→ 各场景场面/分支，带「有改动」标 |

建议顺序：P1 先做（一致性收益最大、只多参考图传输成本）→ P3（教师兜底，
不依赖模型能力）→ P2（等视觉模型与预算明确后再开）。

## 5. 待验证（实施前必须核对）

1. ~~Ark Seedream `image` 参考图参数~~ **已验证**（2026-11-10 实测 HTTP 200；
   官方文档：string/string[]、URL 或 base64、5.0 pro/flash 最多 10 张、
   单图 ≤30MB、宽高比 1/16–16）；
2. 当前 provider（opencodego / Ark）是否有可用的视觉理解模型，
   `LLMService` 能否透传多模态 content；
3. 版权：网络检索的角色参考图用于课堂生图存在授权风险；建议**只使用平台
   自有生成的图像**做参考图，不引入外部角色图；
4. 参考图可能带来构图抄袭/风格趋同，需在评审维度中约束。

## 6. 不做的事

- 不在没有视觉评审的情况下开多轮生成（纯烧钱）；
- 不把网络图片直接作为角色参考图（版权）；
- 不引入 LoRA/微调（训练成本与运维复杂度不匹配当前规模）。

## 7. 业界参考（2026-11-10 调研）

- **角色一致性**：主流方案是「角色设定表（character sheet）+ 参考图
  image-to-image」——一次产出正面/侧面/全身/表情，之后每次场景调用带 1–2 张
  自有参考图。IP-Adapter/InstantID 效果更强但要自托管推理；LoRA 需要每角色
  10–30 张训练图，与「每篇课文临时生成角色」冲突，不划算。固定 seed 只能稳定
  构图、锁不住身份（Ark 文档也未列出 seed）。
- **画师 / art director agent**：性价比最高的两个环节是「设定表先过教师闸门，
  再批量出场景图」和「全局 style block 逐字前置」；候选 2 张 + 轻量校验次之；
  多 agent 全自动闭环与 LoRA 不建议。
- **视觉审核**：纯文本 LLM 看不见性别/年龄错，正是当前故障。低成本替代：
  CLIP/SigLIP 与设定表相似度（粗筛）、人脸检测 + 性别/年龄分类
  （InsightFace/DeepFace）、便宜 VLM 按 rubric 打分（只在校验失败或终稿时调）。
  课堂场景下「教师从 2–4 张里挑」往往比全自动更可靠，边际成本为零。
- **版权**：网络抓取的角色图喂生图模型涉及复制/改编权与平台条款；建议只用
  平台自有生成图做参考，教师上传需确认授权并记录来源。

## 8. P2/P3 实现注记（2026-11-10）

- **视觉模型实测**：`glm-5.3-flash`（当前 LLM 本身）接受 OpenAI 多模态
  content（`image_url` + data URL），能准确读性别/年龄/衣着；Ark 侧的
  doubao 视觉端点未开通（404）。评审走 `UsagePurpose.IMAGE_REVIEW` 计量。
- **冒烟验证**：真实生成 + 真实评审一次，评审真抓出「黑布小帽缺失、
  外搭黑马甲与深青布棉袍锚点不符」，score 0.5 拒绝——rubric 有效。
- **`VisionReviewAgent`**（`domain/game/vision_review.py`）：不抛异常、
  评审失败降级为放行原图（白生成不白花）；data URL 编码由组合根注入
  （domain 不 import infra）。
- **`SceneDesigner` 候选循环**：评审开启时每 subject 生成 `candidates`
  张（逐张扣配额），评分最高者兜底；全灭后带评审意见重绘
  `max_regen_rounds` 轮。评审关闭时行为与 P1 完全一致（1 张直出）。
- **配置**（`WENJING_*` 前缀）：`media_image_vision_review`（off/on，默认
  off）、`media_image_candidates`（默认 2）、`media_image_regen_rounds`
  （默认 1）。`.env` 现已 on + 2 候选 + 0 轮重绘（省钱试点）。
- **P3**：教师审批面板改章节式布局——先人物头像（一致性的源头，提示
  「头像换脸后场景应重绘」），再按场景分组场面图与分支图，章节带
  「有改动」标记。逐槽四操作（重生成/检索/上传/删除）复用 #49 原链路。
