# 角色设定提示词精读（character_design）

> 研究对象：`backend/app/domain/prompts/character_design.py`（VERSION v2）。
> 该节点经 Send 扇出对**每个人物并发调用一次**（`design_one_character×N`），
> 输入是单人物的姓名/原文线索/地位 + 全量 dossier，输出一张「角色设定卡」；
> 产物直接成为运行期角色 Agent 的 identity（`CharacterIdentity.to_system_prompt`）。

## 1. 一次调用的输入输出

```
输入：name + original_traits（原文 role/personality 合并）+ role_hint（在原文中的地位）
      + dossier_json（素材集结论，含 collect_materials 的 character_notes 应试式分析）
输出（脚本设定卡，契约侧结构见 contracts/script.py::CharacterProfile）：
  public_background / personality_traits{label, evidence, behavior} /
  speech_style{五要素 + sample_lines} / knowledge_boundary{knows, not_knows} /
  is_player_playable{value, reason}
```

扇出并发意味着：**每次调用只看一个人**，跨人物的一致性（如称谓互指、同一
事件中谁先谁后）由 merge_characters 节点兜底，本节点不必管。

## 2. 段落构成（六段制）

| section | 内容 | 落库 |
|---------|------|------|
| `system` | 人物设定师定位 + 忠实性总纲（性格/背景只能来自原文可推断） | ✓ |
| `trait_rules` | 性格标签写作法 | ✓ |
| `speech_rules` | 说话风格五要素 + 示例台词 | ✓ |
| `boundary_rules` | 知识边界与禁编造 | ✓ |
| `playability_rules` | is_player_playable 判断准则 | ✓ |
| `checklist` | 输出前自检 | ✓ |
| `_OUTPUT_CONTRACT` | JSON 契约 + JSON 纪律（中文引号） | ✗ 留代码 |

## 3. 四大设计抓手精读

### 3.1 性格标签：标签 + 原文证据 + 行为化描述（show, don't tell）

三字段缺一不可的设计意图：

- `evidence` 锚定**忠实性**——每个标签必须能在原文里找到例证，杜绝凭空贴标签；
- `behavior` 锚定**可演性**——写「可观测的动作/习惯」，运行时角色 Agent 直接
  据此演绎；明确禁止「抽象形容词的重复」（即 behavior 不能只是把 label 换个说法）。
- 标签质量排序示例给出基准：「隐忍自尊」优于「内向」；负面清单禁空泛标签
  （"好人""普通人"）与矛盾标签堆叠。

### 3.2 说话风格五要素——运行时 persona 的全部来源

```
era_layer（语言时代层：纯白话/浅文白夹杂/引用原文语汇）
sentence_rhythm（句长节奏）address_terms（称谓习惯）
catchphrases（口头禅语气词）emotion_expression（情绪表达方式）
+ sample_lines（2-3 句示例台词，运行时校准语气）
```

这五要素被 `script_adapter` 压平成一段文本注入 `CharacterSetting.speech_style`
（`types.py`），最终并入角色 Agent 的 system prompt（`character.py::to_system_prompt`）。
设计上对应 jubensha-ai 调研参考点 #3 的「persona 必须可执行」：不是形容词
（「说话风趣」），而是可操作的生成参数（「爱用反问、常以'罢了'收尾」）。

古文课文「注意标定 era_layer」一句，是对《木兰诗》《论语》类课文防现代口语
出戏的关键约束。

### 3.3 知识边界——防出戏与防 OOC 的禁出清单

`knows / not_knows` 双清单，运行期被显式渲染成：

> 你不知道的事（**绝不能说出、也不能据此行动**；被问及就以符合身份的方式回应：
> 困惑、岔开或按你的立场表态）

运行期还做结构校验（`types.py` 注释：判定按结构判不按文本模糊判）。这层
「设定卡片 → agent 禁出清单」的显式通道是防 hallucination 的承重结构——学生
问超纲问题时角色必须合规地「装不知道」。

配套约束：「背景只写原文可推断内容；原文未交代处写'原文未交代'」——
把「承认不知道」本身定为合法输出，比「编一段背景」更利于教学场景。

### 3.4 is_player_playable——选角的教学判断

四条适合标准（戏份适中贯穿全剧 / 动机清晰可共情 / 主动选择空间 / 语言难度
中学生能自然模仿）+ 三条 NPC 条件（碎片化功能性 / 语言风格极端 / 出场极少）。
基础是教与学的判断而非安全判断（spec 裁决「不带安全考量」）。

## 4. 与「文生图」的结构性缺口（接入图像生成的核心阻塞）

| 缺口 | 现状 | 对文生图的影响 |
|------|------|---------------|
| **无外观字段** | `CharacterProfile` 没有 appearance/visual 字段；现行人物 prompt 的文生图输入只有 `public_background` | 「闰土紫色的圆脸，头戴一顶小毡帽……」这类**原文明示的外貌**无处落——现状用背景文本生成头像时，模型只能从身份描述猜外观，导致头像可能与课文插图/学生记忆形象冲突 |
| **无时代环境投影** | `era_setting` 在 dossier 是非结构化字符串，不进 `CharacterProfile` | 头像/立绘背景无时代线索，模型默认「现代中国人」，古文课文（汉服、甲胄、科举相关服饰）直接穿帮 |
| **无画面情绪基调** | 无 | 立绘的表情/姿态没有依据，只能靠「行为描述」里偶然出现的动作词 |

**结论**：文生图接入前应升 `character_design` v3，在输出契约增加
`appearance`（结构化的外貌要素，仅从原文/插图可推断，未写明处填
「原文未交代」）——这是运行期 persona 无关但图像生成**必需**的字段。
模板方案见 `prompts/imagegen/character.md`。

## 5. 已知弱点与改进方向

| # | 问题 | 改进思路 |
|---|------|---------|
| 1 | appearance 缺失（上表） | 升 v3 加 `appearance` 契约字段 |
| 2 | 五要素全部必填但「未提及处写'原文未体现'」——LLM 在「未体现」时倾向编造具体的填满字段 | 把「允许整条 speech_style 为 null」写得更醒目（现状契约已允许 `或 null`，但没有引导语鼓励用它） |
| 3 | 扇出并发下不同人物的 era_layer/称谓互相不知，merge 后可能风格漂移不一致 | 写「若原文中有直接引语，优先从引语归纳口吻」提高单点锚定；跨人一致性交给 merge |
| 4 | sample_lines 2-3 句过少，运行期校准语气偏薄 | 可考虑 4-6 句（成本可忽略，价值是多轮对戏中语气稳定性更高） |
| 5 | knowledge_boundary 没有说出「当被问及超纲问题时**怎么办**」的教学口径 | 目前的降级句在 boundary_rules 已写（困惑、岔开、表态）；运行期 system prompt 的渲染质量高于它，提示词层面可不动 |
