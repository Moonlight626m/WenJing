# 提示词目录（prompts/）

> 本目录是**提示词工程的知识库**：课文场景划分、角色设定 agent 的提示词研究笔记，\
> 以及文生图（`ImageGenPort`，ADR-0005 §6）所需的图像 prompt 模板。
> **代码内单源不受影响**：LLM agent 提示词的事实源仍是 `backend/app/domain/prompts/`
> （经 `prompts` 表 DB 覆盖层生效），本目录的 LLM 提示词文件是**研究/版本草稿**，
> 迁回代码前不构成规格。

## 目录

| 位置 | 内容 | 状态 |
|------|------|------|
| `research/scene-division.md` | 场景划分提示词精读：判据、数据流、已知弱点 | 研究笔记 |
| `research/character-design.md` | 角色设定提示词精读：五要素、知识边界、结构性缺口 | 研究笔记 |
| `imagegen/README.md` | 文生图 prompt 体系：现状、缺口与接入方案 | 研究笔记 |
| `imagegen/background.md` | 场景背景 prompt 模板（v1）+ 真实课文样例 | 模板（待接入） |
| `imagegen/character.md` | 人物头像/立绘 prompt 模板（v1）+ 真实课文样例 | 模板（待接入） |
| `imagegen/style-guide.md` | 统一画风指南（全 kind 共用） | 模板（待接入） |
| `imagegen/negative-prompt.md` | 反向提示词（负面清单） | 模板（待接入） |

## 现状速览（2026-10-30）

- **文字提示词**：五个节点（collect_materials v3 / divide_events v2 / character_design v2 /
  doubter v2 / write_script v2）的段落常量集中在 `backend/app/domain/prompts/`，
  以 `(stage, node, version, section)` 四维键落 `prompts` 表，DB 覆盖、代码默认兜底；
  输出契约文本留在代码不落库。**改 prompt 文本必须升 `VERSION`**，已 seed 的库才会
  落到新键（见 AGENTS.md「陷阱」）。
- **文生图 prompt**：目前**没有模板文件**——`SceneDesigner.build_generation_prompt`
  用代码内规则即时拼装：`节拍文本拼接（join "；"） + "{style}画风" + 构图尾巴`
  （按 kind：BACKGROUND「环境插画，画面中不出现任何人物」/ AVATAR「角色头像，半身正面，
  纯色简洁背景」/ FULLBODY「角色全身立绘，直立全身，简洁背景」），
  ≤1200 字符（`MAX_PROMPT_CHARS`），发送前过本地安全过滤（命中即拒）+ provider 审核。
  人物 prompt 的输入只有 `public_background` 文本；**无外观字段、无 era 环境信息**，
  是接入文生图前最需要补的结构性缺口（详见 `imagegen/README.md`）。

## 与代码的对接路径（建议，未实施）

1. 文生图 prompt 模板落地为代码常量或独立模块（建议 `domain/game/media_prompts.py`），
   `build_generation_prompt` 改为消费模板 + 结构化字段（era / appearance / mood）；
2. 新增结构化来源：`character_design` 升 v3 增加 `appearance`（外貌要素），
   `divide_events` 升 v3 给 scene 增加 `visual_notes`（时代/地点/时段/氛围）；
   另见 `research/character-design.md` §4 与 `research/scene-division.md` §5；
3. 改动经 `feat-review` 双轴审查，随文生图增强 issue 走规格流程。
