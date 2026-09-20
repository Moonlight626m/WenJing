# WenJing 上线京东云 — 调研报告

> 调研日期：2026-09-16
> 调研方式：纯线上调研（research only，未改动任何业务代码）。资料以京东云官方一手页面
> （`docs.jdcloud.com` 帮助文档、`www.jdcloud.com` 官网产品页、`net.jdcloud.com` 域名站）为主。
> **注意**：京东云帮助文档正文为前端 JS 渲染，本环境抓取只能得到页面标题与目录结构；
> 因此凡数字/细节未能从官方页面正文取到的，一律标注「未能验证」并在可行处用官网产品页
> （SSR 渲染，可抓）内容补齐。报告分「已从官方页面验证」与「未能验证/估算」两类。

## 0. 项目部署形态回顾（读仓库得出）

- 仓库根已内置单机生产栈：`docker-compose.yml` = `db (postgres:16-alpine)` + `backend`（FastAPI，
  uvicorn 单 worker，`backend/Dockerfile` 默认 CMD 即单进程）+ `frontend`（Next.js standalone）+
  `nginx`（`deploy/nginx.conf`：同源入口，`/api` 反代 8000、`/ws` 反代 WebSocket，
  `proxy_read_timeout 3600s`，`/health` 健康检查透传）。
- 上线操作基本就是：`.env`（改 DB 密码 / LLM key / `WENJING_AUTH_COOKIE_SECURE`）→
  `docker compose up -d --build`（backend 入口自动跑 Alembic 迁移）→
  `docker compose exec backend uv run python -m app.services.auth_seed`（幂等 seed，生产必须改默认密码）。
- 关键约束（README/design_00）：
  - **单 worker**：会话运行时与 WS outbox 在进程内存 → 单实例单进程，禁止多 worker/多副本
    （D13：单进程 asyncio，不引入 Redis）。
  - **WebSocket 长连接**：`/ws` 需要 Upgrade/Connection 头与长读超时（nginx.conf 已配好）。
  - **PostgreSQL 16+**（compose 用 `postgres:16-alpine`，Alembic 是唯一建库机制）。
  - LLM provider：`WENJING_LLM_API_KEY` 等环境变量，OpenAI-compatible（DeepSeek/Qwen 等国内可达 provider 可配 `WENJING_LLM_BASE_URL`）。

---

## 1. 计算产品选型

**已从官方页面验证：**

- 京东云提供两条适合本项目的路径：
  - **云主机 CVM**（`www.jdcloud.com/cn/products/virtual-machines`，文档
    `docs.jdcloud.com/cn/virtual-machines/product-overview`）。官方文档实例规格族目录：
    通用型、计算优化型、内存优化型、通用算力型、高频计算型、突发性能型、存储优化型、GPU 型、
    裸金属，另有突发性能型/抢占式实例、已停售规格目录。
  - **轻量云主机**（`www.jdcloud.com/cn/products/light-virtual-machines`）：套餐化购买
    （计算+系统盘+固定带宽+月流量包），官网明示「比同配云主机更优惠」「一站式融合计算、存储、网络」。
- CVM 官网宣称：单实例可用性 99.99%，云硬盘数据持久性 99.9999999%（三副本）；支持按量计费
  （秒级计费、**停机不计费**）与包年包月；购买即送免费主机安全 + DDoS/防暴力破解基础防护。
  最新代际：第 5 代云主机（网络双 100G）、京刚虚拟化引擎、ARM（Ampere Altra Max）、
  鲲鹏/海光国产化实例（官网产品动态）。
- **轻量云主机官方套餐价**（官网产品页直接标价，已验证）：

| 套餐 | CPU/内存 | 系统盘 | 带宽+月流量包 | 价格 |
|---|---|---|---|---|
| 入门型 | 2C2G | 40G | 3M、200G | 43.56 元/月 |
| 基础型 | 2C4G | 60G | 5M、500G | 68.31 元/月 |
| 进阶型 | 2C8G | 80G | 5M、500G | 92.96 元/月 |
| 企业型 | 4C8G | 180G | 5M、500G | 153.97 元/月 |
| 高流量包 | 4C16G | 100G | 16M、5184G | 345.82 元/月 |
| 全套餐区间 | 2C2G–16C64G | 40–450G | 1M/70G – 35M/8000G | 38.11–1435.5 元/月 |

**建议**：WenJing MVP = FastAPI 单进程 + Next.js + PG + nginx 四容器，典型负载很低。
- 首选 **轻量云主机 2C4G（68.31 元/月）** 起步；若教师端做 Stage1 剧本生成（LLM 调用为主，CPU 占用低）
  内存偏紧时可升 2C8G（92.96 元/月）。
- 若需快照/云硬盘/安全组完整体系或后续上多实例，改用 **CVM 通用型/通用算力型 2C4G~4C8G**。
- CVM 入门规格具体单价：官网产品页无价目表、文档正文无法抓取 → **未能验证**；
  按行业横向比较粗估 2C4G 约 50–120 元/月量级（估算，非官方数字，购买页为准）。

## 2. 操作系统与初始化

**已验证：**

- 官方镜像含多代 Ubuntu（官网产品动态：2023/12 起 **Ubuntu 22.04 全地域支持**；更早有 20.04/16.04 发布记录）；
  另有 Windows Server 2022/2019、Rocky Linux、OpenEuler、CentOS（官方有 CentOS EOL 应对文档）。
  **未验证**：Ubuntu 24.04 是否已上架。
- 公网 IP 计费（弹性公网 IP 产品页/文档）：
  - 计费类型：**按配置（固定带宽）、按使用流量、包年包月** 三种；按配置/按流量可续费后转包年包月，
    转换不可逆（官网 FAQ）。
  - 双活 vRouter 技术，EIP 最大带宽可达购买带宽的 150%（官网 FAQ）；入云方向带宽规则见官方 FAQ。
- 轻量云主机：购买时选系统镜像（如 Ubuntu）+ 手动部署软件即可（官网 FAQ 明示），**防火墙默认放行
  80/443**，其他端口需在防火墙页面开通（官网 FAQ）——对部署 nginx(:80/443) 非常友好。
- CVM：安全组绑定云主机（文档目录含「安全组规则典型配置」「配置安全组入站/出站规则」），
  初始化可用 SSH 密钥/云助手/WebTerminal（文档目录存在）。

## 3. 数据库

**已验证：**

- 京东云**有「云数据库 PostgreSQL」托管服务**（官网产品页 `jcs-for-postgresql`；文档现归入
  「云数据库 RDS」产品线 `docs.jdcloud.com/cn/rds/product-overview`，含 PostgreSQL 专属目录：
  产品规格、价格总览、大版本升级、备份恢复、SSL、白名单、插件扩展 TimescaleDB/pgAudit/pg_repack 等）。
- 托管能力（官网产品页/FAQ）：主从热备自动故障转移；每天自动全量备份保留 7 天 + 增量 7 天
  （可任意时间点恢复）；白名单（默认 VPC 内任意地址可访问）；PostGIS 插件；外网访问可开关。
- **版本（重要）**：官网 PostgreSQL FAQ 目前写明「支持 9.6、10、11、12、13 版本」。
  → **最高 13，不满足本项目 PG 16+ 要求**（此 FAQ 可能未随版本更新，但以官方页面为准）。
- OSS 兼容生态：RDS PG 支持 `s3_fdw` 等扩展（文档目录）。

**结论与建议**：
- 因项目要求 PG 16+（`postgres:16-alpine`），**默认走自建 PG**：直接用仓库现成的
  `db: postgres:16-alpine` 容器，数据落 Docker 卷，仅绑 `127.0.0.1:5432`（compose 已如此配置）。
  单机 MVP 自建完全够用，成本 = 0（复用主机）。
- 若坚持托管，**必须先向京东云确认当前是否已支持 PG 14+**（页面 FAQ 可能滞后）；
  再谈托管收益（自动备份/主备高可用）。
- **托管 PG 价格量级：未能验证**（官网价格表 JS 渲染无法抓取）；按行业横估单机版
  1C2G–2C4G 约 100–250 元/月（估算）。

## 4. 网络与安全

**已验证：**

- **安全组**：CVM 有完整安全组体系（文档目录：安全组概述/规则/规则典型配置/创建/绑定/入站出站规则）。
  放行 22（可限制源 IP）、80、443 即可满足本项目（backend/frontend 仅内网 expose）。
- **轻量云主机防火墙默认放行 80/443**，其余端口手动开通（官网 FAQ）。
- **ICP 备案**：京东云有「备案服务」产品线（`docs.jdcloud.com/cn/icp-license-service/introduction`），
  官网服务页有「**免费备案服务**（覆盖备案、部署、域名、网络与上线配置）」。文档目录包含：
  备案流程演示（图文/视频）、**备案授权码说明**（即备案需先有符合条件的服务器资源换取授权码）、
  转移备案、各省补充资料、备案后注意事项、公安局备案、APP 备案、经营性备案等。
  官网域名站建站流程亦明示：「备案的域名才能进行正常使用」。
  → **国内地域 + 自有域名对外提供 Web 服务必须 ICP 备案**（管局要求，行业通则；京东云作为接入商办理）。
- **香港/海外地域**：官网导航有「全球部署服务」等产品线，但 **京东云是否有香港 CVM 地域、
  以及海外地域免备案的具体政策未能从官方页面验证**（文档正文 JS 渲染抓不到地域列表）。
  行业通则：境外地域部署一般免 ICP 备案，但大陆访问延迟增大（30–80ms+）、且教育类应用
  若面向国内公立学校，无备案域名在合规与访问稳定性上都不占优。

## 5. HTTPS 与域名

**已验证：**

- **域名注册**：京东云域名站 `net.jdcloud.com` 提供注册（示例促销价：`.cn` 35 元/年、
  `.com.cn` 35 元/年、`.xyz` 18 元/年、`.site` 14 元/年；`.com`/`.net` 等也在列）。
  官方建站流程：注册域名 → 备案 → DNS 解析 → 部署 SSL → 上线。
- **云解析 DNS**：有独立产品（文档 `docs.jdcloud.com/cn/jd-cloud-dns/product-overview`），
  支持域名添加/记录增删改、负载均衡/动态解析/轮询、IPv6 等（文档目录）。
  解析套餐具体价格：**未能验证**（基础解析通常免费或极低价，估算）。
- **SSL 证书**：京东云 SSL 产品（官网 `ssl-certificate` 页）售卖 GeoTrust/GlobalSign/DigiCert/CFCA
  证书，促销价示例：GeoTrust DV 单域名 **313.74 元/年**、GeoTrust DV 泛域名 4399 元/年；
  DV 最快 20 分钟签发、支持 DNS 自动验证。
  文档另有「**免费证书及证书管理服务**」专页（`docs.jdcloud.com/cn/ssl-certificate/free`）
  及「免费证书服务策略调整通知」→ **京东云确实提供免费证书**，但其规格（单域名/DV/有效期
  是否为 90 天等）未能抓取正文验证。
- **自建 Let's Encrypt 完全可行**：拿到主机后用 certbot/Caddy 签发即可，与京东云无绑定关系
  （nginx 443 配置需自行加入，见 §8）。

## 6. 对象存储 / 静态资源

**已验证**（官网 OSS 产品页）：

- 产品名：**对象存储 OSS**（Object Storage Service），`www.jdcloud.com/cn/products/object-storage-service`。
- 官方标价（元/GB/天）：标准存储 **0.00427**（≈0.13 元/GB/月）、低频 0.00263、归档 0.001；
  标准存储可用性 99.995% / 12 个 9 持久性。
- 能力：S3 兼容生态（官方文档含 **S3cmd / S3FS 参考**）、预签名 URL、防盗链、静态网站托管、
  生命周期分层、多区域存储/同步、CDN 加速（可搭配京东云 CDN）。
- 对 WenJing：MVP 阶段前端静态资源由 Next.js standalone 自带，课文素材体积小，**暂不必接 OSS**；
  若后续加入课文音频/图片素材库，可开 OSS 标准存储 + 预签名 URL 上传下载，成本几元/月。

## 7. 备案流程

**已验证（结构性信息）：**

- 京东云备案服务文档站（`docs.jdcloud.com/cn/icp-license-service/introduction`）覆盖：
  备案简介 → 备案指引（**备案流程演示-图文/视频**、**备案授权码说明**、转移备案）→
  各省管局补充资料 → 工信部短信验证说明 → 备案后注意事项（含**公安局备案**、备案号超链接设置）。
- 官网宣传「免费备案服务」；控制台入口 `record-console.jdcloud.com`（需登录）。
- 前置条件：需在京东云购买符合条件的计算资源并获取**备案授权码**（文档目录明示该机制），
  域名需完成实名认证。

**未能验证（官方正文 JS 渲染抓不到）**：具体审核时长（行业经验通常 1–4 周，各省差异大——
此为二手经验，仅作参考）、授权码与具体套餐的绑定关系细节。

**要点提示**：备案期间域名不能在国内地域对外服务；可在备案期间先用 IP + 端口自测，
或先在香港/海外（若可用，未验证）临时验证环境，备案通过后再切国内地域。

## 8. 部署架构建议（针对 WenJing）

**推荐架构（文字版，单实例同源）：**

```
用户浏览器
   │ HTTPS (443)
   ▼
京东云主机（Ubuntu 22.04，轻量 2C4G 起 / CVM 通用型）
 ├── Docker Compose（复用仓库现有编排，无需改造）
 │    ├─ nginx        :80→443(改造)    ← 唯一对外入口（同源 /api /ws /health /）
 │    ├─ frontend     :3000 (expose 内网)  Next.js standalone
 │    ├─ backend      :8000 (expose 内网)  FastAPI 单 worker + WS
 │    │     └─ 入口自动 alembic upgrade head（WENJING_RUN_MIGRATIONS=1）
 │    └─ db           :127.0.0.1:5432  postgres:16-alpine（自建，卷持久化）
 └─ 进程守护：restart: unless-stopped（compose 已配）+ 云监控告警
```

**落地要点：**

1. **WS 反代**：`deploy/nginx.conf` 已含 `Upgrade/Connection` 头与 `proxy_read_timeout 3600s`
   （`/ws/`），直接沿用；切勿在 backend 前再加会轮询/会断长连接的组件。
2. **HTTPS**：现 nginx.conf 只有 80；上线时新增 443 `server` 块（证书路径 + `ssl_protocols TLSv1.2/1.3`），
   80 跳转 443。证书两条路：
   - 京东云**免费证书**（已确认存在该产品页）或 Let's Encrypt（certbot 自动续期）；
   - 证书下发到主机后以只读卷挂进 nginx 容器。
   同步在 `.env` 置 `WENJING_AUTH_COOKIE_SECURE=1`（登录 Cookie 加 Secure）。
3. **进程守护**：保持 Docker Compose + `restart: unless-stopped`，并让 Docker 随系统自启
   （`systemctl enable docker`）。不推荐 systemd 裸跑 uvicorn/next（与仓库编排不一致）。
4. **单 worker 铁律**：backend 容器默认 CMD 即单 worker，不要加 `--workers`。
   未来要扩容时，必须先实现共享运行时 + 粘性会话（README 已注明），否则禁止多副本。
5. **环境变量/密钥**：根目录 `.env`（compose 自动读取），含 `POSTGRES_PASSWORD`（强密码）、
   `WENJING_LLM_API_KEY`、`WENJING_SEED_PASSWORD`。`.env` 已被 gitignore，
   **严禁提交**；服务器上权限设 600。LLM 用国内可达 provider 时设
   `WENJING_LLM_PROVIDER/WENJING_LLM_MODEL/WENJING_LLM_BASE_URL`（OpenAI 兼容接口）。
6. **首启初始化**：`docker compose exec backend uv run python -m app.services.auth_seed`（幂等），
   随后**立即改掉默认密码**（README 明示生产必须）。
7. **数据库**：自建 PG 仅绑回环；为防误删卷，定期 `docker exec` 做 `pg_dump` 到云盘/OSS
   （或购买快照策略）。
8. **监控/日志**：京东云控制台提供云监控（文档目录存在）可对主机做 CPU/内存/带宽告警；
   应用日志用 `docker compose logs`（或接入官方日志服务）。

## 9. 成本估算（MVP 最低可用配置）

**已验证单价 + 估算组合**（估算项已标注）：

| 项 | 规格 | 月成本 | 性质 |
|---|---|---|---|
| 轻量云主机 | 2C4G / 60G 盘 / 5M 带宽 + 500G 流量包 | 68.31 元 | 官网标价（已验证） |
| （升级备选） | 2C8G | 92.96 元 | 官网标价（已验证） |
| 数据库 | 自建 PG16（Docker，复用主机） | 0 元 | 方案（无需另购） |
| （托管备选） | 云数据库 PostgreSQL 单机版 | ~100–250 元 | **估算**（价格表未能验证） |
| 域名 | `.cn` / `.com` | 35 元/年（≈3 元/月） | 官网促销价（已验证） |
| SSL | 京东云免费证书 或 Let's Encrypt | 0 元 | 免费证书存在已验证；规则未验证 |
| 备案 | 京东云免费备案服务 | 0 元 | 官网宣称（已验证） |

**合计：约 ¥70–100/月（自建 PG 路线）**；若选择托管 PG 约 ¥170–350/月（估算）。
流量超出套餐部分按天后付费（轻量 FAQ，已验证）。

## 10. 上线 checklist（从零到可访问）

1. **购买主机**：轻量云主机 2C4G（或 CVM 通用型同配），选 Ubuntu 22.04 系统镜像；
   国内地域。CVM 需另配 EIP（按固定带宽或按流量）+ 安全组放行 22/80/443；
   轻量套餐自带公网带宽，防火墙默认已放行 80/443。
2. **注册域名**：`net.jdcloud.com` 注册 `.cn`/`.com`，完成实名认证。
3. **ICP 备案**：京东云备案控制台提交（需服务器备案授权码），管局审核（时长未能官方验证，
   行业经验 1–4 周），通过后做**公安局备案**（备案号挂网站页脚）。
4. **装 Docker**：`curl -fsSL https://get.docker.com | bash`（或 Ubuntu 仓库 docker.io +
   compose 插件），`systemctl enable --now docker`。
5. **拉代码**：`git clone` 仓库（或 scp 打包上传）到服务器。
6. **配置环境**：`cp .env.example .env`，改 `POSTGRES_PASSWORD`（强密码）、
   `WENJING_LLM_PROVIDER/MODEL/API_KEY/BASE_URL`（国内可达 provider）、
   `WENJING_SEED_PASSWORD`；HTTPS 就绪后置 `WENJING_AUTH_COOKIE_SECURE=1`。
7. **启动**：`docker compose up -d --build`（backend 入口自动 Alembic 迁移）。
8. **Seed**：`docker compose exec backend uv run python -m app.services.auth_seed`，然后立刻改默认密码。
9. **反代与 HTTPS**：扩展 `deploy/nginx.conf` 增加 443 server 块（京东云免费证书或 certbot），
   80→443 跳转；`docker compose up -d nginx` 重载。
10. **解析与验证**：云解析 DNS 添加 A 记录指向主机 IP；浏览器访问 `https://<域名>/`，
    健康检查 `https://<域名>/health/ready`；登录测试账号验证 WS（会话页需 WS 长连接正常）。
11. **监控与日志**：控制台开云监控告警（CPU/内存/带宽）；设置每日 `pg_dump` 备份；
    `docker compose logs`/`make logs` 巡检；必要时购买快照。
12. **安全收尾**：SSH 改密钥登录、限制 22 源 IP；确认 db 只绑 127.0.0.1；.env 权限 600。

---

## 未能从官方文档验证的事项汇总

1. **CVM 入门/通用型实例具体价格**（官网产品页与文档正文均无价目表；仅轻量云主机套餐价可验证）。
2. **云数据库 PostgreSQL 当前支持的版本上限**：官网 FAQ 写 9.6–13（疑似未更新），
   是否已支持 14+/16+ 需向京东云确认；PG 托管价格量级亦未能验证（估算）。
3. **备案流程细节与时限**：文档正文 JS 渲染抓不到；已验证的只有流程结构（授权码、图文演示、
   各省资料、公安部备案等目录级信息）与「免费备案服务」的存在。
4. **免费 SSL 证书的具体规格**（单域名/泛域名、有效期、数量限制）：仅验证「免费证书及证书管理服务」
   页面与策略调整通知的存在。
5. **香港/海外地域是否可用、是否免备案**：地域及可用区文档正文无法抓取，未能验证。
6. **Ubuntu 24.04 镜像是否上架**（仅验证到 22.04 全地域可用）。
7. **云解析 DNS 套餐价格**（基础解析可能免费，未验证）。

## 主要来源（京东云官方）

- 云主机 CVM：https://www.jdcloud.com/cn/products/virtual-machines ；https://docs.jdcloud.com/cn/virtual-machines/product-overview
- 轻量云主机：https://www.jdcloud.com/cn/products/light-virtual-machines
- 云数据库 RDS（含 PostgreSQL）：https://www.jdcloud.com/cn/products/jcs-for-postgresql ；https://docs.jdcloud.com/cn/rds/product-overview
- 对象存储 OSS：https://www.jdcloud.com/cn/products/object-storage-service
- 弹性公网 IP：https://www.jdcloud.com/cn/products/elastic-ip
- SSL 数字证书：https://www.jdcloud.com/cn/products/ssl-certificate ；https://docs.jdcloud.com/cn/ssl-certificate/free
- 域名服务：https://net.jdcloud.com/ ；https://docs.jdcloud.com/cn/domain-name-service/product-overview
- 云解析 DNS：https://www.jdcloud.com/cn/products/jd-cloud-dns
- 备案服务：https://docs.jdcloud.com/cn/icp-license-service/introduction ；https://record-console.jdcloud.com
- 文档支持中心：https://docs.jdcloud.com/
