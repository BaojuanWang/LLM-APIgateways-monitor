# 数据词典 · 面板与底表逐项释义

本文件解释仪表盘(`ecosystem_dashboard.html`)每一个数字，以及底表
（`results/master/master_table.csv`）每一组字段的含义、取值语义、数据来源与口径坑。
配合 `docs/METHODS_element_citations.md`（方法文献背书）阅读。

---

## 第一部分 · 仪表盘 stat 卡(顶部 6 个大数字)

| 卡 | 值的含义 | 怎么算 | 坑 |
|---|---|---|---|
| **分析站点总数** | 参与分析的去重站点数(按 eTLD+1 归并) | `master_table` 行数 | = 发现层 ∪ 监测；不等于发现的原始 URL 数 |
| **one-api 家族占比** | 合并后 `stack_family` 为 one-api 家族的比例 | one-api 家族站数 / 总站数 | **77%**，是 809→1089 合并口径；**≠** §4.1 的 96/71（那是按发现来源分组的 `framework`）。别混用 |
| **归并后运营者数** | 域名经共享信号归并后的独立运营者簇数 | `operator_clusters` 去重 operator_id | 簇数接近站数=大多数站独立；集中在技术栈而非人 |
| **托管于 Cloudflare** | 已富化站中 IP/ASN 命中 Cloudflare 的比例 | CF 站 / 已富化站 | 仅覆盖已富化站；反映 CDN 遮蔽普遍性 |
| **站点出生于 2026** | 有时间数据的站里注册/证书年份为 2026 的比例 | 2026 站 / 有日期站 | 生态极年轻的证据；用 WHOIS 注册日→缺失时退化到证书 not_before |
| **one-api 占比:GitHub→FOFA** | §4.1 发现偏差核心：两种发现法下 one-api 份额 | 见 §4.1 | `96→71%`；71% 为集中度**保守下界**（深探收紧至 73%） |

---

## 第二部分 · 21 张分布图逐张释义

每张图是「类别 → 计数」的横向柱状。**蓝条=已识别/主体**，**灰条=未识别/待分类/CDN**（图例已标）。

### 技术栈 / 框架层

1. **技术栈家族** — 合并所有框架信号后的统一家族标签(`stack_family`)。值=该家族的站数。`one-api-family` 压倒性主导 = 生态近乎单一栈（软件单一化风险，Geer 2003）。
2. **发现层原始框架标注** — 仅发现层 codesearch 直接采到的 `framework` 原值(未经合并)。用来对照合并前后的差异。
3. **技术栈 · GitHub 发现(框架指纹→有偏)** — 只统计 GitHub codesearch 找到的站的 `framework`。96% one-api。**这是有偏的一侧**：靠框架指纹找，自然偏 one-api。
4. **技术栈 · FOFA 发现(框架无关→无偏)** — 只统计 FOFA 网络空间测绘找到的站。71% one-api + 24% 异构尾。**这是无偏的一侧**，是 §4.1 关键 figure。

### 网络 / 基础设施层

5. **顶级域(TLD)** — 按 eTLD+1 取最后一段。值=该 TLD 站数。看 `.com/.ai/.xyz/.cn` 等的分布，反映注册偏好与成本。
6. **托管商 / ASN** — 源站 IP 的自治系统(ASN)归属机构。值=站数。Cloudflare/Amazon 等 CDN 居前 = 真实源站被遮蔽。
7. **源站 IP 国家** — IP 地理定位国家(仅已富化站)。**注意**：CDN 后的国家是 CDN 边缘节点位置，**不等于运营者所在国**，仅供参考。
8. **验证信号强度分层** — 发现层判定该站是中转站的证据强度(`signal_tier`)：强/中/弱。值=站数。强=多重独立信号命中。

### 运营者 / 集中度层

9. **运营者簇规模分布** — 每个运营者控制的域名数分桶(1 站/2-3 站/…)。绝大多数是「1 站」= 集中度低（HHI≈0.0015），印证「集中在技术栈不在人」。
10. **相似模板家族 Top(搭建商层)** — 用共享稀有特征(favicon/非CDN ASN/注册商/Server/前端)做 Jaccard 聚类得到的模板家族。值=家族成员数。比运营者归并**粗一层**，揭示共享搭建模板/搭建商（未必同一人）。

### 时间线层

11. **站点出生年份** — WHOIS 注册年（缺失退化到证书 not_before）。值=站数。生态时间线，2024/2025/2026 逐年放大。
12. **2026 按月出生(井喷曲线)** — 2026 年内按注册月细分。值=站数。看井喷是否加速。

### 存活 / 证书层

13. **存活状态** — 监测层最近一次探测的在线状态(online/dead/…)。值=站数。用于流失率(churn)。
14. **证书 CA(签发机构)** — TLS 证书的签发机构(`ssl_issuer`)。值=站数。Let's Encrypt/Google 免费 CA 主导 = 低成本、无 OV/EV 企业验证 → 拿不到公司名。
15. **域名注册商** — 域名的注册商(`whois_registrar`，如 Namecheap/阿里云/Spaceship)。值=站数。**注意**：这是**代理商**，不是注册人本人。

### 前端 / 语义层

16. **前端 / 服务端技术** — 从响应头/HTML 推断的前端框架与 Server（Vue/Nginx 等）。值=站数。
17. **域名关键词主题** — 域名字符串里的主题词(api/ai/gpt/chat/hub…)。值=命中站数。反映命名习惯与定位。
18. **域名含上游厂商名** — 域名里直接含 openai/claude/gpt/gemini 等上游品牌名的站。值=站数。反映「傍品牌」倾向（也是商标风险信号）。

### 分类学层(capstone)

19. **站点角色分类** — `site_role`：relay(纯转售) / conversion_layer(协议转换 sub2api) / aggregator(聚合) / unidentified。值=站数。
20. **托管类型(不透明性)** — `hosting_type`：cdn_fronted(藏 CDN 后) / direct_origin(直连源站) / unknown。值=站数。cdn_fronted 高 = 生态不透明。
21. **站点成熟度分层** — `maturity_tier`：established(≤2024) / growing_2025 / new_2026 / unknown。值=站数。

---

## 第三部分 · 底表字段组(master_table.csv 列前缀释义)

底表每行一个站(site_key = eTLD+1)。列按**数据来源前缀**命名，`in_<源>` 是布尔标记该站是否被该源覆盖。

| 前缀 | 来源 | 关键字段 | 含义 |
|---|---|---|---|
| `disc__` | 发现层(codesearch/FOFA) | `origin`(轮次/fofa_g1)、`framework`、`signal_tier`、`verdict`、`content_hits` | 怎么发现的、判定为中转站的证据 |
| `hvoy__` | 第三方榜单(hvoy) | `overallScore`、`avgOnlineRate`、`avgLatencyS`、`modelCount`、`reviewCount`、`averageRating` | 榜单上的评分/在线率/模型数/口碑 |
| `manual__` | 手工种子标注 | `icp_filing`、`has_privacy_policy`、`contact_telegram`、`contact_qq`、`tech_stack` | 人工核过的高质量字段（仅 16 种子站） |
| `monitor__` | 存活监测 | `online_status`、`http_status`、`final_url`、`page_title`、`html_hash`、`redirect_chain` | 定期探测的存活/重定向/页面指纹 |
| `enrich__` | 静态富化 | `whois_reg_date`、`whois_registrar`、`ssl_issuer`、`ssl_org`、`ssl_san`、`ssl_fingerprint`、`ssl_not_before`、`ip`、`ip_country`、`ip_asn`、`favicon_hash` | 证书/WHOIS/IP/favicon（用于归并与时间线） |
| `privacy__` | 隐私政策爬取 | `has_privacy`、`privacy_url`、`collect_data`、`applicable_law`、`third_party_sharing`、`has_contact` | 有无隐私政策、声称收集什么、适用法律、是否第三方共享 |
| `contacts__` | 联系方式 | `telegram`、`qq_group`、`wechat`、`discord`、`has_affiliate`、`affiliate_url` | 运营者触达渠道、是否有分销/返利 |
| `ops__` | 商业化探针 | `payment_methods`、`has_faka`(发卡)、`trust_claims`、`email` | 支付方式、是否发卡站、信任话术 |
| `price__` | 价格探针 | `model_rows`、`usable_price_rows`、`access_status`、`quality_flags` | 抓到多少可用价格行、可访问性 |
| `blocked__` | 封禁记录 | `first_confirmed_at`、`status` | 何时确认失效/被封 |

### 身份识别相关字段的现实(回答「背后公司真做这个吗」)

| 想要的信号 | 现有字段 | 现状 | 能不能定位运营者 |
|---|---|---|---|
| 企业实名 | `enrich__ssl_org` | 仅 7 站有(免费证书无 Org) | ❌ 覆盖太低 |
| 注册人/机构 | `enrich__whois_registrar` | 存的是**注册商**不是**注册人** | ❌ 拿错字段了 |
| ICP 备案主体 | `manual__icp_filing` | 仅 ~25 站(种子手工填)，FOFA=0 | ⚠️ 最有价值但覆盖极低 |
| 触达身份 | `contacts__telegram/qq` | 有 | △ 是马甲身份，非法人 |

> **结论**：目前底表**基本无法回答「哪家公司在运营」**——WHOIS 存的是代理商、证书没公司名、ICP 覆盖太低。要挖运营者真实身份，需要补三样：①WHOIS 注册人字段(org/name/country/email，很多未脱敏) ②ICP 备案主体查询 ③关于我们/服务条款页里的公司名。见下一步计划。

---
_快照随数据刷新，字段结构不变。生成脚本见 `scripts/make_dashboard.py`（图）与 `scripts/build_master.py`（底表）。_
