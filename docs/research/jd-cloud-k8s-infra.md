# 调研：京东云服务器上是否上 K8s + APISIX/DB 等 infra

> 调研日期：2026-09-16。前置背景见 [`jd-cloud-deployment.md`](jd-cloud-deployment.md)（京东云基础选型调研）。
> 场景：≤10 人小团队，租用京东云主机；除 WenJing 外，同机/同账号还部署
> [cyber-stray](https://github.com/Zewang0217/cyber-stray)（共 2 个服务）。

## 结论（TL;DR）

**不建议现在上 K8s；建议 docker compose +（可选）APISIX standalone 单容器网关；数据库继续自建 PG 容器。**
触发条件满足时再引入 K8s（见 §5）。

## 1. cyber-stray 项目概况与接入方式（已验证，来自仓库 README / CI-CD / docs）

- 自主游荡 Agent：状态机（饥饿/无聊）驱动后台搜索、爬取互联网内容，经 Telegram/飞书推送；
  含 Next.js Web Dashboard 与 Casdoor OIDC 登录；Bun + pnpm monorepo；存储为 SQLite + JSON。
- 部署：GitHub Actions CD —— 质量门 → build/push 镜像到 GHCR → **SSH 进生产机** →
  scp 同步 compose.yaml → 远程执行 `container-update.sh`（拉镜像、起容器、healthcheck 门、清镜像）。
  回滚 = 改 compose 里 `IMAGE_TAG` 为旧 sha 重发。
- **与京东云的接入是纯「SSH + Docker」**，未用任何京东云特有 API/产品。
  生产机 Ubuntu 24.04，装有京东云平台自带 agent（`jdcloudservice`、`jcs-agent-core` 等）。
- 两个对本项目有用的经验：
  1. 京东云 VPS 直连部分境外站点失败，需要本地代理（mihomo `127.0.0.1:7890`）——
     WenJing 的 LLM provider 若用 OpenAI 类境外 API，同样可能需要出网代理配置。
  2. 京东云 VPS 到部分云厂商地址池有 BGP 路径不通的情况（该仓库曾 mtr 取证向京东云报障）。

## 2. 京东云 K8s 方案盘点

### 2.1 托管 K8s（「Kubernetes 集群」，京东云称 JCS for Kubernetes）✅ 官网已验证

- 官网明确「控制面全托管架构，无需关注 API Server、ControllerManager、Etcd 等」，兼容标准 K8s API，
  支持节点池、CSI 存储、LoadBalancer Service。
- 计费：「Kubernetes 集群服务本身暂时免费，只需为集群中创建的云主机、公网 IP、云硬盘等云资源按需付费」。
- ⚠️ 未能验证：最低节点数、节点规格下限、具体标价（docs 正文 JS 渲染抓不到）。

**评估**：控制面虽免费，但工作节点必须是云主机。对 2 个小服务，仍需 ≥1 台像样的节点
（建议 2C8G），加上 LoadBalancer/云盘等配套，**成本比单机 compose 明显高**，而收益为 0——
WenJing 后端是单实例约束（会话运行时与 WS outbox 在进程内存），K8s 的多副本调度、
自愈、滚动发布在这个负载上没有用武之地。

### 2.2 自建 k3s / kubeadm 单节点 ✅ 官方文档已验证

- kubeadm 要求每台 ≥2GB RAM、2 CPU；k3s 官方最低 1 核/512MB，推荐 2 核/1GB。
- k3s 官方实测（1.26.5，含打包组件 + Prometheus 监控栈 + 示例负载）：单节点 server
  稳态内存约 **1596MB（SQLite）/1606MB（内嵌 etcd）**；纯 agent 仅 275MB。
  来源：https://kubernetes.io/zh-cn/docs/setup/production-environment/tools/kubeadm/install-kubeadm/ 、
  https://docs.k3s.io/zh/installation/requirements 、https://docs.k3s.io/zh/reference/resource-profiling

**评估**：单节点 k3s 技术上放得下，但**单节点 K8s 只保留 K8s 的复杂度、拿不到 K8s 的核心收益**
（调度、多节点容错、多副本）。10 人团队还要额外维护：节点升级、kine/etcd、证书轮换、
ingress/controller 生命周期。为 2 个服务不值。

## 3. APISIX 网关 ✅ 官方文档已验证

- 三种部署模式（https://apisix.apache.org/docs/apisix/deployment-modes/ ）：
  traditional（需 etcd）/ decoupled / **standalone**。
- **standalone file-driven 模式从本地 `apisix.yaml` 加载全部路由，免 etcd**，单容器即可跑，
  官方推荐给声明式配置的中小规模场景。
- APISIX vs NGINX：基于 NGINX 构建，增加动态配置、100+ 插件、Admin API（官方对比页）；
  vs Traefik：APISIX 重吞吐与插件生态，Traefik 重容器原生发现与 TLS。
- ⚠️ 官方未给最小内存数字；社区经验 APISIX 容器 ~100–300MB，etcd ~200–500MB（估算）。
- 京东云自有的「API 网关」托管产品是面向**开放 API 的管控面**（AK/SK、限流、Mock、SDK 生成），
  **不是反向代理型流量网关**，不适用于本场景（https://www.jdcloud.com/cn/products/api-gateway ✅）。

**评估**：若想让两个服务共享统一入口（按域名分流 443、统一 TLS 证书、限流），在现有机上
加一个 **APISIX standalone 单容器**是低成本做法；但就当前规模，nginx（仓库已有
`deploy/nginx.conf`，含 WS Upgrade 头与 3600s 读超时）已够用。APISIX 属于
「想要插件（限流/熔断/WAF/API 元数据）时再换」，迁移成本不高。

## 4. 数据库 infra

- 京东云托管「云数据库 PostgreSQL」存在，但官网 FAQ 仍写最高支持 **PG 13**，不满足
  本项目 PG16+ 要求 → 继续推荐**自建 `postgres:16-alpine` 容器**（见前置调研报告 §3）。
  ⚠️ 托管 PG 版本与价格未能从官方正文验证，后续可在京东云控制台确认是否已升级版本支持。
- cyber-stray 用 SQLite，不占用 PG 资源。

## 5. 内存预算与决策矩阵（⚠️ 估算，k3s 数字为官方实测）

单机组件内存（2C4G / 2C8G 对比）：

| 组件 | 4G 机器 | 8G 机器 |
|---|---|---|
| 系统 + OS 开销 | ~300MB | ~300MB |
| k3s server 全栈（含 containerd） | ~1600MB | ~1600MB |
| APISIX（standalone 免 etcd） | ~150MB | ~200MB |
| PostgreSQL | ~400MB | ~500MB |
| WenJing backend（FastAPI 单 worker） | ~150MB | ~200MB |
| WenJing frontend（Next.js SSR） | ~300MB | ~400MB |
| cyber-stray（app + web + casdoor） | ~400MB | ~500MB |
| **合计** | **~3.3GB（贴顶）** | **~3.7GB** |

- 2C4G + k3s：不可行（k3s 一项吃掉 40%，叠加两个服务必 OOM）。
- 2C8G + k3s：可行但紧；**纯 compose 可省 ~1.6GB**，余量健康。
- 决策矩阵：

| 方案 | 成本 | 运维复杂度 | 收益 | 结论 |
|---|---|---|---|---|
| docker compose + nginx（现状） | 最低 | 最低 | 够用 | ✅ **推荐基线** |
| compose + APISIX standalone | +~150MB | 低（配置文件式） | 统一网关/限流/插件 | ✅ 需要网关能力时加 |
| 自建 k3s 单节点 | +~1.6GB | 高 | 2 服务场景≈0 | ❌ 暂不 |
| 京东云托管 K8s（JKE） | 需独立工作节点，成本明显上升 | 中（托管控制面）+ 仍要懂 K8s | 多节点/多副本时才有 | ❌ 暂不 |

## 6. 引入 K8s 的触发条件（defer 触发点）

满足任意一条再评估（届时优先考虑京东云托管 JKE 而非自建）：

1. 服务数 >3 且分布在多台主机，需要统一调度/跨机发布；
2. 出现真正的多副本需求（WenJing 引入共享运行时 + 粘性会话改造后）；
3. 需要蓝绿/金丝雀发布、HPA 自动扩缩；
4. 团队有专人愿意承担 K8s 运维（升级、证书、存储类）。

## 7. 针对当前两服务共存的推荐落地

1. 两服务同机（或同账号两台）继续走 **SSH + docker compose**，与 cyber-stray 的 CD 模式一致，
   可共用一套部署习惯（GHCR 镜像 + compose `IMAGE_TAG` 回滚）。
2. 统一入口：现有 nginx 增加按域名 server 块分流两个服务；若需要限流/插件，
   换 APISIX standalone（免 etcd）单容器，迁移成本低。
3. WenJing 补 443 TLS（免费证书或 Let's Encrypt）+ `WENJING_AUTH_COOKIE_SECURE=1`。
4. LLM provider 若为境外 API，参考 cyber-stray 经验预置出网代理环境变量。
5. 备案按前置调研报告 §7 流程执行（国内地域 + 自有域名必须 ICP 备案）。

## 来源索引

- 京东云 K8s 产品页（控制面全托管、集群服务免费）：https://www.jdcloud.com/cn/products/jcs-for-kubernetes ✅
- kubeadm 最低要求：https://kubernetes.io/zh-cn/docs/setup/production-environment/tools/kubeadm/install-kubeadm/ ✅
- k3s 要求与资源实测：https://docs.k3s.io/zh/installation/requirements 、https://docs.k3s.io/zh/reference/resource-profiling ✅
- APISIX 部署模式（standalone 免 etcd）：https://apisix.apache.org/docs/apisix/deployment-modes/ ✅
- APISIX vs NGINX/Traefik：https://apisix.apache.org/learning-center/apisix-vs-nginx/ 、https://apisix.apache.org/learning-center/apisix-vs-traefik/ ✅
- 京东云 API 网关：https://www.jdcloud.com/cn/products/api-gateway ✅
- cyber-stray 仓库（README、.github/workflows、docs/research）：https://github.com/Zewang0217/cyber-stray ✅

> ⚠️ 未能验证项汇总：JKE 最低节点数与标价、APISIX/各业务容器精确内存、京东云托管 PG
> 当前版本上限与价格、轻量云主机是否支持 K8s 网络插件所需内核特性。
