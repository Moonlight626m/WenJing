# 文生图 prompt 体系（imagegen/）

> 目标：为 `ImageGenPort`（ADR-0005 §6）准备结构化、可版本化的图像 prompt 模板，
> 替代现行「代码内即时拼装」的裸规则。本目录文件目前是**草稿**，接入即把模板
> 转为代码常量并让 `build_generation_prompt` 消费结构化字段。

## 1. 现状（代码内拼装，无模板）

现行 prompt 由 `domain/game/media.py::build_generation_prompt` 即时拼出：

```
{场景/人物描述}，{style}画风，{构图尾巴（按 kind）}
```

- **描述来源**（`scene_visual_description`）：Stage2 场景 = 各 beat 的
  `description` 用「；」拼接；人物 = `public_background` 全文。
  Stage3 运行期新场景与 Stage2 用**同一函数**——这是刻意设计：
  两处必须产出相同 prompt，去重键才命中、不重复付费。
- **构图尾巴**（`_KIND_TAILS`）：
  BACKGROUND「环境插画，画面中不出现任何人物，无文字无 logo」；
  AVATAR「角色头像，半身正面，纯色简洁背景，无文字无 logo」；
  FULLBODY「角色全身立绘，直立全身，简洁背景，无文字无 logo」。
- **预算**：≤1200 字符（`MAX_PROMPT_CHARS`），超长从描述尾部截断、
  保画风与尾巴；adapter 侧再过一道同预算校验。
- **安全**：本地过滤命中即拒（性/自伤/血腥/真人肖像四类 + 中文贴合匹配），
  provider 侧审核是主闸门。**注意**：模板里的负面词必须在安全过滤允许范围内
  ——过滤是「命中即拒」，不是「剔除」，所以 prompt 模板**不能**包含
  「无血腥」「无裸露」这类否定式禁词（会误命中关键词匹配）。
- **去重键**含 `style`：改画风 = 全部缓存失效 = 重新付费，风格文字要稳定。
- **provider**：OpenAI Images 兼容形状（gpt-image-1 / 百炼 / 智谱 / 硅基流动），
  prompt 为中英均可的纯文本，无 negative-prompt 参数位——
  负面约束必须**正向语义**写进主 prompt（如「干净画面」而非「不要脏」）。

## 2. 结构性缺口（接入前需补）

文生图质量的决定因素是**输入信息**，不是模板修辞。按信息缺失排优先级：

| 缺口 | 现状来源 | 需要的供给 |
|------|---------|-----------|
| P0 外貌 | 人物只有 `public_background`，无 appearance 字段 | `character_design` v3 增 `appearance`（见 research/character-design.md §4） |
| P0 时代环境 | 场景 beats 只有事件文本，无 era/地点行 | `divide_events` v3 给 scene 增 `visual_notes`（时间/地点/氛围一行）；或从 dossier `era_setting` 提取投影 |
| P1 色彩/光线基调 | 无 | visual_notes 带 mood 词 |
| P2 跨主体画风一致性 | 单靠「{style}画风」一个词 | style-guide.md 的固定画风段落（全 kind 共用字符串）——prompt 与去重键都稳定 |

## 3. 模板的形状（v1 设计）

四个文件按「固定段落 + 插槽」组织，插槽只允许来自结构化字段，不做自由拼接：

- `style-guide.md`：画风段（`STYLE_SEG`），全 kind 共用，参与去重键的 `style` 实参；
- `background.md`：场景背景模板（`BG_TEMPLATE`），插槽
  `{era} {location} {time} {weather} {action_summary} {mood}`；
- `character.md`：头像/立绘模板（`AVATAR_TEMPLATE` / `FULLBODY_TEMPLATE`），
  插槽 `{era} {role_label} {face} {hair} {clothing} {accessories} {build} {pose} {expression}`；
- `negative-prompt.md`：**正向语义**的「排除面」段（部分内容写进主 prompt 尾部），
  供支持 negative prompt 参数的 provider 扩展时使用。

每个文件附**真实课文样例**，样例同时是未来单测的 fixture 候选。

## 4. 接入路径（落代码时）

1. 新增 `domain/game/media_prompts.py`：模板字符串 + `render_*` 函数；
   `build_generation_prompt` 的改造保持两个不变量——
   **与 Stage2/Stage3 同 prompt**、**预算截断仍保尾巴**；
2. 契约侧补 `appearance` / `visual_notes`（走四处单源流程，升 schema version）；
3. prompt 文案若不落 `prompts` 表（图像 prompt 不是 LLM agent 提示词，
   无 DB 覆盖需求），以代码常量进 defaults 无表键亦可；
4. 工作流为 `feat-review` 双轴审查 + 真实 provider 冒烟（`WENJING_IMAGE_*` key）。

## 5. 风险与约束记录

- **安全过滤的否定词陷阱**（§1 最后一条）：历史上 #47 评审已发现 FULLBODY
  不能套「画面中不出现任何人物」，同类错误在本目录模板中必须再做一次
  「逐 tail 过安全过滤」的测试（样例 fixture 应覆盖 BACKGROUND/AVATAR/FULLBODY
  三个 kind 的完整渲染结果）。
- **改 style 文字 = 全量缓存失效**：style-guide.md 定稿前冻结用词，
  上线后改动按「provider_version」维度 bump，避免隐性重烧配额。
- gpt-image-1 只认三个尺寸档位，模板不承诺具体像素；尺寸由 adapter 决定。
