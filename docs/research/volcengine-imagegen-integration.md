# 火山引擎方舟文生图接入调研与实现（2026-10-30）

> 调研任务：`doubao-seedream`（Ark /images/generations）接入文境的文生图端口。
> 结论已落地为 adapter：`backend/app/infrastructure/media/image_gen_ark.py`。
> 方案文档：`docs/research/branch-montage-dm-plan.md`（Phase 1 画师层的 provider 位）。

## 1. 已实现（代码位）

| 项 | 位置 |
|---|---|
| `ArkImageGen` adapter（OpenAI 骨架子类） | `backend/app/infrastructure/media/image_gen_ark.py` |
| provider 枚举 `openai` 旁新增 `ark` | `backend/app/infrastructure/config.py media_image_gen_provider` |
| 工厂 `ark` 分支（watermark 配置透传） | `backend/app/infrastructure/media/image_gen.py` |
| OpenAI 骨架的可复用钩子（`_build_payload`/`_post`）与 4xx error.body 解析 | `backend/app/infrastructure/media/image_gen_openai.py` |
| endpoint 配置样例 | `backend/.env.example`（provider/base_url/model/watermark/read_timeout 注记） |
| mock 测试（payload/尺寸抬档/审核映射/重试/工厂） | `backend/tests/test_media_image_gen.py` Ark 段 |

## 2. 端点与鉴权（官方文档核对）

- 数据面：`POST https://ark.cn-beijing.volces.com/api/v3/images/generations`
- 鉴权：`Authorization: Bearer $ARK_API_KEY`（控制台「API Key 管理」创建；
  主账号最多 50 个，可按 Model ID/IP 限域）。实名认证 + 控制台开通模型是前置门槛。
- 同步协议（无任务轮询）；`stream=true` 的 SSE 仅 lite/4.5/4.0 支持，本接入不用。
- `model` 可填 Model ID 或推理接入点 `ep-…`（Endpoint 有限流/监控/计费管理，
  部分账号禁止直用 Model ID：`InvalidEndpointOrModel.ModelIDAccessDisabled`）。

## 3. 模型与价格（2026-10 控制台口径）

| 模型 | 状态 | 输出单价 |
|---|---|---|
| `doubao-seedream-5-0-flash-*` | **当前推荐** | 0.12 元/张（平面价，与像素档无关）|
| `doubao-seedream-5-0-pro-*` | 当前推荐 | ≤261 万 px：0.30；>261 万 px：0.60 |
| 5.0 lite / 4.5 / 4.0 | 即将下线 | 不再新接 |

- Vintage 提示：3.0 已不在售；Seedance 是**视频**模型，别混入文生图配置。
- **审核失败不计费**（价格页原文）；免费额度只抵扣 token 计费，不含按张生图。
- IPM 限流 500 张/分钟/账号——远高于本平台每会话生图上限，不构成约束。

## 4. 协议差异（相对 OpenAI Images）与实现决策

| 差异 | Ark 行为 | 我们的实现 |
|---|---|---|
| `n` 字段 | 官方 SDK 类型**没有** | payload 不发（父类 `_build_payload` 钩子） |
| `watermark` | 默认 true（右下「AI 生成」） | 配置 `media_image_gen_watermark=true` 合规默认，显式关才无标 |
| `size=宽x高` | 总像素 ∈ [921600（1280x720）, ≈462 万]，比例 [1/16,16] | exact 直发；**低于下限按 kind 抬档**：头像→1024x1024、立绘→864x1152、16:9→1424x800（压 pro 低价档 ≤261 万 px） |
| `size=1K/2K`（档位式） | 可用但画幅由模型定 | 不采用（要精确 16:9） |
| 审核 400 | `error.code`：`*SensitiveContentDetected` / `*RiskDetection` / `*PolicyViolation`… | 父类 `_status_reason` 带上 code、`_looks_like_policy` 加 Ark 码族 → **BLOCKED**（不可重试）而非常规 FAILED |
| 429/408/5xx | 官方 SDK 重试 ≤2、尊重 Retry-After | Ark 子类退避重试（2s/4s 封顶 8s）；400/401/403/404 立即抛（400→BLOCKED） |
| 超时 | 官方 SDK read 600s | Ark 默认 read 300s（配置可调） |
| `response_format` | 支持 `url`/`b64_json`；产物 url 有效期 **24h** | 建议 `b64_json`（绕开 URL 域名/Content-Type/24h 过期） |
| negative_prompt | **无** | 与现有 OpenAI 路径一致：不依赖负向参数，本地过滤 + 正向语义 |

## 5. 快速启用（生产/开发）

```env
WENJING_MEDIA_IMAGE_GEN_PROVIDER=ark
WENJING_MEDIA_IMAGE_GEN_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
WENJING_MEDIA_IMAGE_GEN_API_KEY=<方舟 API Key>
WENJING_MEDIA_IMAGE_GEN_MODEL=doubao-seedream-5-0-flash-260915
WENJING_MEDIA_IMAGE_GEN_RESPONSE_FORMAT=b64_json
WENJING_MEDIA_IMAGE_GEN_READ_TIMEOUT=300
WENJING_MEDIA_IMAGE_GEN_SIZE_MODE=exact
WENJING_MEDIA_IMAGE_GEN_WATERMARK=true
```

验证顺序：`make seed` 不涉及；用 `scripts/` 侧真实冒烟（可加
`WENJING_TEST_IMAGE_GEN=1` + 上配置跑 `tests/test_media_image_gen.py::test_real_provider_smoke`）。

## 6. 成本口径（对我们一张剧的图量）

current design_assets：每场景 1 张场面图 + 每分支 1 张 + 每角色 1 张头像。
以 5 场 + 4 分支 + 6 角色为例 ≈ 15 张：flash ≈ **1.8 元/篇**；pro 全低价档 ≈ 4.5 元/篇。
已有 `MediaQuotaService`（org 预算）+ 每会话生图上限兜底，无需新增配额代码。

## 7. 风险登记

- **prompt 长度**：官方建议中文 ≤300 字（非硬限）；本地 1200 字符预算偏长——
  画师层转写 `max_chars` 若后续实测细节丢失，应按 provider 收分 provider 预算
  （`build_generation_prompt` 支持传 max_chars，改动集中在调用点）。
- **408 重试双计费**：官方 SDK 同样接受（响应丢失但图已生成），概率小；
  计量在成功路径，极小概率下少记一单——可接受。
- **水印关闭义务**：关闭 `watermark` 前确认平台自身的 AI 生成标识义务。
- **`seed`/`guidance_scale`**：SDK 类型有但未实测，本接入不用。

## 8. 来源

- 图片生成 API：https://www.volcengine.com/docs/82379/1541523
- Base URL 与鉴权：https://www.volcengine.com/docs/ark/base-url-and-authentication
- 模型列表/价格/教程：`.../docs/ark/model-list` `.../model-pricing` `.../seedream-4-0-5-0`
- 错误码/内容护栏：`.../docs/ark/error-codes` `.../content-safety-guardrails`
- `arkruntime` 0.17.0：https://pypi.org/project/arkruntime/ （字段/超时/重试默认值核对）
