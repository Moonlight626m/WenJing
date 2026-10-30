# 场景划分提示词精读（divide_events）

> 研究对象：`backend/app/domain/prompts/divide_events.py`（VERSION v2）。
> 该节点在剧本生成 workflow（ADR-0003）中位于 `verify_materials` 之后、
> `design_characters` 之前，输入是 `TextAnalysis`（人物列表 + 关键事件）与
> `dossier`（素材集结论），输出场景/节拍草稿供 `write_script` 遵守。

## 1. 节点在链路中的位置

```
collect_materials → verify_materials(doubter) → [materials_gate]
  → divide_events（本节点）→ design_characters ⇉ 扇出 N → merge_characters
  → [pre_write_gate] → write_script → final_audit(doubter 复用) → …
```

`write_script.v2` 的 BEAT_RULES 明确写着「若输入包含事件划分草稿，其场景/节拍结构
与介入点必须遵守」——即 divide_events 是**结构的设计者**，write_script 只是填血肉。
divide_events 的判据质量直接决定下游剧本的骨架。

## 2. 提示词结构与段落构成（五段制）

| section | 内容 | 落库 |
|---------|------|------|
| `system` | 角色定位（剧本结构设计师）+ 忠实性总纲 | ✓ |
| `scene_rules` | 场景划分判据 | ✓ |
| `beat_rules` | 节拍粒度判据 | ✓ |
| `interaction_rules` | 介入点写法（玩家参与空间） | ✓ |
| `checklist` | 输出前自检 | ✓ |
| `_OUTPUT_CONTRACT` | JSON 字段类型契约 | ✗ 留在代码 |

## 3. 核心判据精读

### 3.1 场景（scene）判据——三条硬标准 + 一条软引导

1. **价值转折**：每个场景必须承载一次人物处境/关系/认知的 A→B 变化；
   没有独立转折的段落**并入上一场景**，「不要为凑场次拆分」。
2. **切换点** = 原文中的时空跳转或人物进出（新地点、新人物组合、时间推移）。
3. **戏剧性问题**：每场聚焦一个能用「是/否」回答检验的悬念。
4. 软引导：全剧 **3-5 场**、篇幅均衡（防巨型场景）。
5. 完整性：覆盖全部关键事件，相对顺序与原文一致。

分析：判据 1 与 2 是「必要不充分」关系——有切换点未必有转折（如单纯换场），
提示词用判据 1 的并场规则吸收这种冲突；判据 3 是剧作理论（罗伯特·麦基式）的
「就是要提出的问题」口语化表达，中学生对这种表述的可执行性依赖 LLM 自身训练
语料，实际有效的是 1+2+5。

### 3.2 节拍（beat）判据

- **beat = 一次完整的行为/反应交换**：谁做了什么、引出谁的什么反应；
  「纯氛围描写不足以独立成拍」——这是防把静态描写切成多少拍的负面规则。
- 每场 3-6 拍，一拍不得跨场景。
- 关键 beat 的维系靠**机械可校验**的结构：`is_key_event` + `key_event_order`
  严格递增、必须指向【关键事件】里真实的序号——下游节点（nodes.py 的机器校验
  与 validators.py）按契约拒绝字符串序号，prompt 里的「严禁写成 "e1"」对应真实
  LLM 的常见错误。

### 3.3 介入点（interaction_point）——本提示词最独特的设计

`interaction_rules` 让结构设计师戴上 drama manager 心智：

- 给出玩家可扮演角色 + 此刻可做的事（有话可说/有事可做）；
- **介入不得改变关键事件**：`must_not_change` 显式列出受保护的关键事件序号；
- 旁白过场可置 null；「只描述参与空间，不预设玩家台词」。

这是「课文情景演绎」区别于普通剧本生成的关键：划分阶段就为**运行时玩家参与**
留白，把「学生能不能自然入场」作为结构设计的一等约束。运行期引擎
（`game_runtime.py`）依据这些介入点判定玩家互动窗口。

## 4. user message 的拼装顺序

```
prompt_version 标注 → system → scene_rules → beat_rules → interaction_rules
→ 字段类型契约（含硬性约束清单）→ checklist → 人物列表 → 关键事件列表
→ 素材集结论（dossier_json，标注「事实以原文为准」）
→ （可选）教师指导 directives
```

要点：judgment 规则放在最前（LLM 长文本的两端注意力）、自检放在契约之后
（输出前的最后一个「想法」）、真实数据放最后（不污染前面的规则段落），
顺序是对 attention 位置敏感性的合理利用。人物列表只给 `role / personality`
的 traits 合并，**没有外貌信息**（对文生图是缺口，见 imagegen/README.md §2）。

## 5. 已知弱点与改进方向

| # | 问题 | 证据 | 改进思路 |
|---|------|------|---------|
| 1 | 3-5 场对长课文可能过紧：《离骚》《鸿门宴》类课文关键事件多，判据 4 与判据 5（全覆盖关键事件）矛盾时 LLM 倾向压场，导致单场 beat 超出 3-6 上限，又违反 beat_rules | 判据间未给出冲突消解规则 | 在 scene_rules 补一句「关键事件超过 8 个时场景数上限放宽到 7」 |
| 2 | 「价值转折」对纯叙事课文（说明性/日记体）可执行性弱 | 无调整余地 | 允许「认知转折 = 全景→聚焦」等更弱形态，给一行降级判据 |
| 3 | interaction_point 未把玩家年龄/语言难度纳入 | PLAYABILITY 的语言难度约束在 character_design，划分侧无对应 | 介入点补「玩家在此可以说×年级学生说得出口的话」提示（弱约束即可） |
| 4 | 无配图意识：场景划分没有为文生图准备视觉锚点（时间/地点/氛围的字段） | 输出契约只有 title/participants/beats/interaction_point | 见 prompts/imagegen/README.md §2，建议 scene 增加 `visual_notes` 字段（可留到升 v3 时一起做） |
| 5 | checklist 用「是否」问句，LLM 自检率低 | 与 write_script、doubter 的 checklist 同一问题 | 保持现状可接受；更强的自检应由 doubter 终审承担 |

改判据前先升 `VERSION`（v2 → v3），已 seed 库才会回退到代码新默认——这是 AGENTS.md
的硬约束。visual_notes 若被采纳，必须随 v3 一起走（契约四处单源同步 + fixtures）。
