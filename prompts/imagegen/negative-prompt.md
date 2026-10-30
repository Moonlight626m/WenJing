# 反向提示词（negative-prompt）

> OpenAI Images 兼容端点**没有 negative_prompt 参数**；负面约束必须以
> **正向语义**写进主 prompt 尾部（现状 `_KIND_TAILS` 里的「无文字无 logo」
> 就是这么做的）。本文件登记两类内容：
> ① 可并入主 prompt 的正向排除段；
> ② 为将来带独立 negative 参数位的 provider（SD 系/部分国产厂商）
>     预留的清单——**不能**直接拼进现行 prompt。

## 红线安全约束（架构性提醒，非模板内容）

**「性内容/自伤/血腥」这些词本身绝不能出现在任何一段 prompt 里**——
`media_safety.inspect_prompt` 是「命中即拒」的**子串匹配**
（sexual / self_harm / gore / real_person 四类、含中文贴合匹配），
prompt 中出现「无裸露」「无血腥」这类
否定式禁词会**直接把整条 prompt 拦死**，生成永远失败。负面语义永远写成
正向：「干净画面」「构图纯净不显杂乱」。

## ① 可并段主 prompt 的正向排除段（POS_TAIL，v1）

按 kind 选用（与 `_KIND_TAILS` 同位拼接，不重复写）：

| kind | 正向排除段 |
|------|-----------|
| BACKGROUND | `环境插画，画面中不出现任何人物，无文字无 logo`（现行，保持） |
| AVATAR | `角色头像，半身正面，纯色简洁背景，无文字无 logo`（现行，保持） |
| FULLBODY | `角色全身立绘，直立全身，简洁背景，无文字无 logo`（现行，保持；**严禁**套用 BACKGROUND 的「不出现人物」） |

可扩展候选（以画面质量角度，**需真实 provider 验证后采纳**）：

- 防劣质 AI 味：`构图干净，细节真实，无夸张滤镜光晕`
- 防元素混入（教具/水印类的正向写法）：`画面保持教学插图的克制`（概念性，效果不保证）
- 防镜头术语干扰：write_script 的「不用镜头术语」是**给编剧 LLM** 的；
  生图侧同理——模板里也要避免「特写/俯拍/景深」字样，provider 对
  摄影术语的解读会把画面拉向照片质感，与画风段冲突。

## ② 独立 negative 参数位清单（预留给 SD 系 provider）

> 仅当 `ImageGenPort` 扩展出支持 negative_prompt 的第二 adapter 时启用。
> 这些是**程序级**禁词（provider 会真正排除语义），不是 prompt 文本。

```
text, watermark, logo, signature, caption,
photorealistic face, celebrity likeness,
modern clothing (era-specific subjects),
lens flare, oversaturated, 3d render, chibi,
multiple people (BACKGROUND slots), extra fingers, deformed hands
```

注意：`nsfw / gore / blood / self-harm / nude` 一类词**不得**
进入任何主 prompt 文本（会被本地安全过滤命中即拦），只允许在
支持独立 negative 参数位的 adapter 里作为程序级排除语义使用。
若 provider 能力分支后真正启用，清单随 adapter 配置维护，
不落库、不进模板文件常量。

## 使用纪律

1. 现行链路（adapter 全走 OpenAI 兼容端点）只使用 ①；
2. ① 的增删是「画面质量调整」，但**会进最终 prompt**——去重键只摘
   `description_summary` 与 `style`，不含构图尾巴，尾巴变更不会自动换键。
   同键复用会让旧尾巴的产物继续命中缓存（新尾巴生成不出来），
   故尾巴/画风段变更必须随 `provider_version` bump 走，
   或把尾巴哈希并入去重键——后者是更稳的长期解，接入时一并考虑；
3. 本文件是**登记处**，不是运行时读取源；落代码时上表两列常量化。
