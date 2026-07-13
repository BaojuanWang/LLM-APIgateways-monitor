# 分析层全景说明书 (ANALYSIS_LAYER_FULL_SPEC)

> 面向不熟悉本项目技术细节的合作者 / 审稿人。逐分层讲透「做了什么、怎么做的、
> 结果是什么、哪些还不确定」。每层四段式:**【怎么做的】/【文献背书】/【已知结果】/【未知·漏洞】**。
> 样本 **N = 1089** 站;每个分类维度逐类列举、加总回到 1089。快照 2026-07-13。

## 口径声明(务必先读)

- **sub2api 全程保留原名**,与 `one-api-family` 并列于技术栈维度,**不用「转换层 / conversion_layer」代称**。
  原因:sub2api 的要害**不是**「它做协议转换」,而是**它的上游货源性质可能就有问题**
  (把个人订阅 / 网页会话硬转成 API,来路存疑)。这与「用什么开源框架搭建」(one-api/new-api)是
  **完全不同的维度**——一个是**货源维度**,一个是**框架维度**。用功能词「转换层」会淡化「货源存疑」这个要点。
- 现有代码 `classify_sites.py:site_role()` 把 sub2api 映射成了角色 `conversion_layer`。
  **本说明书判定:该功能词应弃用,回归 sub2api 原始技术栈标签**(见 B、C 节)。

---

## A. 站点发现与去重(分析层的输入从哪来)

**【怎么做的】** 分析层不自己发现站点,它的输入是「发现层 + 监测 + 人工种子」三类来源,按
**eTLD+1(registrable domain)归并**成「每站一行」的主表(`build_master.py`,归一化在
`domain_utils.py:registrable_domain()`:把 `api.x.com`、`www.x.com`、`x.com` 折叠成 `x.com`)。
两个**独立发现方法**:①**GitHub 代码搜索**(靠 one-api 等开源框架的代码指纹找)②**FOFA 网络空间测绘**
(不靠框架、靠网络特征找)。合并去重后 **N=1089**。

**【文献背书】** eTLD+1 归一化 = Public Suffix List 规范(△ 规范)+ DomainsProject 集中度测量
「按 registrable apex 计数」(○ 实践)。两种发现方法的**系统性偏差对比**本身是核心方法贡献,
见 §4.1(`docs/FINDING_discovery_bias.md`)。种子偏差需写 limitations(Santanna *Stress Testing
the Booters* 2015,⭐)。

**【已知结果】** 来源覆盖(有重叠,不互斥,故不加总到 1089):
- 发现层 `in_disc` = 932(其中 **GitHub 发现 652 · FOFA 发现 280**)
- 监测 `in_monitor` = 292 · 人工种子 `in_manual` = 41 · 第三方榜单 `in_hvoy` = 246
- 富化 `in_enrich` = 1089(全覆盖)· 隐私爬取 `in_privacy` = 1085
- **并集去重 = 1089**(发现层 932 ∪ 仅监测/种子 157)

**【未知·漏洞】** 种子有偏(榜单/论坛/codesearch 来源都非随机);§4.1 已量化 GitHub 代码搜索
高估集中度(96% vs FOFA 71%)。1089 不是「全体中转站」,是「这两种方法能触及的」。

---

## B. 站点角色分类(site_role)

**【怎么做的】** `classify_sites.py:38-48 site_role()`。大白话规则(按序):
技术栈 ∈ {sub2api, auth2api} → `conversion_layer`;含 all-api-hub/metapi 或 aggregator → `aggregator`;
one-api-family → `relay`;{openai-compatible-unknown, confirmed-unknown, unlabeled} → `unidentified`。
即角色**几乎完全派生自技术栈**(见 C),不是独立判定。

**【文献背书】** 无直接文献背书,为本项目工程判断(角色标签是技术栈的功能性重命名)。

**【已知结果】**(合计 1089 ✓):
| 角色 | 计数 |
|---|---|
| relay | 838 |
| unidentified | 221 |
| **conversion_layer(实为 sub2api 直接映射)** | 30 |
| **合计** | **1089** |

**【未知·漏洞】** ⚠️ **按口径要求 1**:`conversion_layer` 这个功能词是 sub2api 的直接映射
(30 = 技术栈 sub2api 的 30,一一对应)。**建议弃用该角色词,回归 sub2api 原始技术栈标签**——
因为「货源存疑」(sub2api 要害)≠「协议转换」(功能描述),功能词会淡化货源维度。
`unidentified`(221)= relay 之外「没抓到框架指纹」的合集,**不是「确认非中转站」**,只是未识别。

---

## C. 技术栈识别(stack_family)★ 重点

**【怎么做的】** 给数据集打标签的是 `site_characterization.py:39-57 stack_family()`,读
**`disc__framework`(发现层)+ `enrich__tech_stack`(富化)做子串匹配**(按序):
含 `sub2api` → **sub2api**;含 one-api/new-api/oneapi/newapi/veloera/voapi/one-hub/done-hub 任一 →
**one-api-family**;framework==`openai_compatible` → **openai-compatible-unknown**;
framework==`unknown` → **confirmed-unknown**;啥都没有 → **unlabeled**。
另有一个**更严格的四层指纹现场探针** `tech_stack_fingerprint_probe.py:57-100`(见 D 节),
**只在子集(FOFA 的 66 个异构尾)上跑过,未全量**——留作尾巴复核工具。

**【文献背书】** Web 应用指纹 = Kondracki & Nikiforakis *WASABO*, **USENIX Security 2024**(⭐);
banner/端点识别 = OWASP WSTG(○ 标准);统一栈 taxonomy 驱动的生态刻画 = video-piracy Telegram
生态论文(arXiv 2605.08418,◆)。「单一栈=单点脆弱」= **Geer *CyberInsecurity: The Cost of
Monopoly* 2003**(⭐ 经典)+ Zembruzki'22 集中度量化。

**【已知结果】**(合计 1089 ✓):
| 技术栈 | 计数 | 说明 |
|---|---|---|
| one-api-family | 838 | 开源中转框架家族,生态主体(近乎单一栈) |
| unlabeled | 144 | 发现层与富化都无栈信号 |
| openai-compatible-unknown | 73 | 仅知「OpenAI 兼容接口」,不知具体实现 |
| **sub2api** | 30 | **货源维度存疑(订阅/会话转 API),非框架维度** |
| confirmed-unknown | 4 | 发现层明确标 unknown |
| **合计** | **1089** | |

**【未知·漏洞】** ⚠️ **关键区分(口径要求)**:`unlabeled`(144)+ `openai-compatible-unknown`(73)
**只代表「没抓到指纹」,不等于「确认是异构自研」**。§4.1 论证「真异构尾巴」时,**只能依据
逐站探针复核过的那批**(报告 §14.1:FOFA 尾 66 站深探后 **59 个 genuine_unknown**),
**不能拿 144+73 泛泛代表异构**。可靠性:one-api-family = **高**(多重硬信号 + 96/71 交叉验证);
unlabeled / openai-unknown = **中低**(子串匹配 + 发现时点,非现场重探)。

---

## D. 指纹方法本身(「指纹」到底指什么)

**【怎么做的】** 两套指纹:

**① 发现层的「是不是中转站」指纹(signal_tier,A/B/C 分层)**,记录在 `disc__signal_tier`:
- **A_api_status**:命中未认证状态端点(`/api/status` 返回 one-api 家族的 JSON 信封)—— 最强
- **B_v1_models**:命中 `/v1/models` OpenAI 兼容模型列表端点
- **C_framework+content**:框架特征 + 页面内容双命中 —— 较弱

**② 技术栈四层置信度指纹探针**(`tech_stack_fingerprint_probe.py`):
- Tier1 **FORK_HEADER**(:57)独有响应头 `X-New-Api-Version` / `x-oneapi-*` —— 最强,骗不了
- Tier1 **FORK_BODY**(:65)独有项目名/作者 handle(QuantumNous、songquanpeng、veloera…)
- Tier2 **FAMILY_BODY**(:85)家族级泛特征(`new-api`/`one-api` 残留品牌)—— 只证家族不证具体 fork
- Tier2 **/api/status JSON**(:244 `_parse_status_json`)`system_name`/`version` 信封 + 版本抽取
- Tier3 **DOMAIN**(:92)域名含 newapi/sub2api 等 —— 最弱(域名可乱起)
- 另有 **SPA_SHELL_RE**(:102)识别 JS 空壳,避免把「活站没渲染」当「死站/未识别」

**【文献背书】** 独有响应头 + 未认证状态端点 JSON + 版本抽取 = WASABO(USENIX Sec'24,含版本识别,⭐);
三层置信度防「过度声称」= OWASP WSTG evidence-strength + WASABO 关于指纹工具过度声称的实证(⭐);
自建实例做 ground-truth 差分 = WASABO 容器 testbed(⭐);unknown 拆 blocked/spa_shell/unreachable
= 测量卫生「区分被挡与不存在」(arXiv 2606.14525,◆);favicon 指纹 = *Tales of Favicons and
Caches* NDSS 2021(⭐)。

**【已知结果】** signal_tier 分布(合计 1089,含 157 个非发现层站为空 ✓):
| signal_tier | 计数 |
|---|---|
| A_api_status | 664 |
| C_framework+content | 261 |
| (空,非发现层来源) | 157 |
| B_v1_models | 7 |
| **合计** | **1089** |

**【未知·漏洞】** 四层探针**未全量跑**(仅 66 站尾巴子集),故全量 stack_family 靠的是较弱的
发现层子串匹配,而非现场四层指纹。指纹强度递减:响应头/status-JSON(强)> 独有 body 名(强)>
家族泛词(中,会家族内混淆)> 域名(弱)。SPA 空壳仍可能藏未渲染的指纹(静态探针够不到)。

---

## E. 托管类型(hosting_type)⚠️ 已知云主机混淆

**【怎么做的】** `classify_sites.py:51-56 hosting_type()` + 名单 `:25-26 CLOUD`。规则:IP 的 **ASN
名称字符串**含 CLOUD 名单(cloudflare/amazon/google/akamai/fastly/alibaba/tencent/ovh/microsoft/
linode/digitalocean/netlab)任一 → **cdn_fronted**;否则有 IP → **direct_origin**;无 IP → **unknown**。

**【文献背书】** ASN 作托管归属信号但**对 CDN 失效**(Cloudflare 共享匿播 IP)= Cloudflare 官方文档
+ bot-detection 测量(arXiv 2606.14525,◆)。这条正是我们「CDN 后不可反查」的依据。

**【已知结果】**(合计 1089 ✓):
| 托管类型 | 计数 |
|---|---|
| cdn_fronted | 760 |
| direct_origin | 313 |
| unknown | 16 |
| **合计** | **1089** |

**【未知·漏洞】** ⚠️ **两个已知漏洞(口径要求)**:①小众 CDN 不在名单 → 误判成 direct_origin
(假裸露);②**更严重**:CLOUD 名单混入 amazon/google/alibaba/tencent/ovh/linode/digitalocean
等**云主机商**(不只是 CDN),导致**跑在裸云主机上、其实可反查的真实源站被误判成 cdn_fronted**。
→ **结论:313 个 direct_origin 是保守下界,真实可反查的站更多**;「70% 藏 CDN」严格应表述为
**「70% 的 IP 归属于 CDN 或云厂商」,不完全等于「源站不可见」**。可靠性:**中**(Cloudflare 判定准,
云/CDN 混淆使分割模糊,但对追踪任务是安全方向误差——宁可少追不误报)。

---

## F. 运营者归并(operator clustering)★ 高推断

**【怎么做的】** `operator_matching.py`,并查集/连通分量:把**共享强信号**的域名归并成一个运营者簇。
归并边信号(强弱不同):**证书指纹 cert_fp / 证书 SAN cert_san**(同一张证书,最强)>
**同 IP**(独享 IP 强、共享主机弱)> **favicon / site_name**(偏弱,one-api 默认图标/默认站名会误连)
> discord/telegram。代码内含**护栏**:CDN 证书 / CDN 匿播 IP 不参与归并;**默认 favicon / 通用站名
黑名单**(稀有性过滤)防假聚类;高频通用信号频率过滤。

**【文献背书】** 连通分量归并恶意基础设施 = ASwatch(SIGCOMM 2015,⭐)+ Chen/Nadji/Perdisci
图聚类(CCS 2017,⭐);证书复用/SAN 归并 = 恶意 TLS 聚类 + .dk 钓鱼证书(⭐/◆);favicon =
NDSS'21(⭐);**HHI 集中度 = Zembruzki et al. TMA 2022**(⭐/◆,>2500 为高度集中);CDN 排除护栏 =
Cloudflare 共享匿播/共享证书(○+◆,本项目关键正确性护栏)。

**【已知结果】** 1089 站 → **1000 个运营者**,**HHI≈0.0011**(极分散)。运营者按控制站数分布(合计 1000 ✓):
| 控制站数 | 运营者个数 |
|---|---|
| 1 站 | 938 |
| 2 站 | 44 |
| 3 站 | 12 |
| 4 站 | 4 |
| 5 站 | 1 |
| 6 站 | 1 |
| **合计运营者** | **1000**(其中多站运营者 **62** 个,最大 6 站) |

**两个易混口径(务必区分)**:
- **多站站点数 = 151**:属于「控制 ≥2 站的运营者」的**站点**总数(62 个多站运营者名下共 151 站:2×44+3×12+4×4+5+6)。
- **多品牌 multi_brand_operator=Y = 55**:运营者名下**品牌显示名 >1** 的站(`classify_sites.py`)。
- 二者不等:有些多站运营者旗下多域名共用**同一品牌名**(算多站、不算多品牌),故 55 < 151。

**【未知·漏洞】** ⚠️ **关键不确定性**:**1000 是上界**——反侦察好的马甲(每站换证书/IP/图标/名字)
连不上,会被算作独立运营者,故**真实运营者更少、真实集中度更高**。reverse-IP 抽样已实证坍缩
(21/287 IP 就发现 12 个跨品牌同 IP 马甲,`vigilante_candidates.md`,但需 liveness 验证)。
信号可靠性:cert_fp/cert_san **最强**;IP **看情况**;favicon/site_name **最弱**(靠稀有性过滤兜底)。
「集中在技术栈不在人」这个结论成立,但「人的分散度」是**被高估的上界**。

---

## G. 模板家族(template_family)

**【怎么做的】** `site_similarity.py`,Jaccard/集合重叠聚类:靠**更粗的共享稀有特征**(同 ASN /
同注册商 / 同 Server 头 / 同前端)把站聚成「模板家族」。**比运营者归并粗一层**——揭示「同一搭建方 /
共享部署模板」,**未必同一人**。

**【文献背书】** Jaccard 聚类网站结构/钓鱼 kit 同源(◆/○,*Phishing Site Detection Using
Similarity of Website Structure*;大规模 HTML Jaccard 去重聚类)。定性:探索性、比运营者归并更不确定。

**【已知结果】** **26 个模板家族,覆盖 83 站**(其余站未落入任何家族)。最大家族如 `52ccl.cn`(10 站,
共享 `server:esa` 阿里云边缘)、`guardentry.ai`(4 站,Vercel + Name.com)。

**【未知·漏洞】** 这是**探索性**层,不确定性高于运营者归并:共享搭建特征 ≠ 同一运营者(可能只是都用
了同一家搭建服务/云)。覆盖率低(83/1089),不宜作全局推断,仅作「搭建商层」定性证据。无直接
「LLM 中转站模板聚类」文献,借用钓鱼 kit 同源方法。

---

## H. 时间线 / 成熟度(birth_year, maturity_tier)

**【怎么做的】** `birth_year` = WHOIS 注册日(`enrich__whois_reg_date`),缺失退化到证书
`ssl_not_before`(`classify_sites.py:92`)。`maturity_tier` = birth_year 的**分桶**
(`:59-69`:≤2024=established / 2025=growing_2025 / ≥2026=new_2026)。**两列是派生关系,非独立维度**。

**【文献背书】** WHOIS 创建日期/注册商作滥用信号 = Hao et al. IMC 2013 + PREDATOR CCS 2016(⭐,
显式用注册时特征)。

**【已知结果】** maturity_tier(合计 1089 ✓):
| 成熟度 | 计数 |
|---|---|
| new_2026 | 663 |
| established (≤2024) | 233 |
| growing_2025 | 192 |
| unknown | 1 |
| **合计** | **1089** |

birth_year(合计 1089,1 缺失):2026=663 / 2025=192 / 2024=84 / 2023=74 / ≤2022=75 / 缺失=1。

**【未知·漏洞】** ⚠️ ①birth_year 是**域名首次注册年**,非**该业务上线年**——老域名重用会失真;
②**≤2015 的约 29 站**(mongodb.org / rapidapi.com / xfyun.cn 等)**疑似发现层假阳性**(正经老网站
被误抓),待人工清理后从数据集剔除。maturity_tier 完全继承 birth_year 的误差。

---

## I. 存活 / 监测(health / online_status)

**【怎么做的】** 监测脚本 `pipeline.py:69-88 classify_status()`,由 `.github/workflows/monitor.yml`
定时触发(GitHub Actions 计划任务)。单次静态 GET 的响应分类:报错含 dns/nodename→DNS_FAIL;
timeout→TIMEOUT;CF 人机验证/521/522→CLOUDFLARE_OR_BLOCKED;含「域名出售」→PARKED;200/429→ONLINE;
301/302→REDIRECTED;401/403→ONLINE_LOGIN_REQUIRED(算活)。`classify_sites.py:102` 兜底:无监测
状态但**有证书 → 推断 https_alive**。

**【文献背书】** 无直接文献背书,为标准 HTTP 存活探测工程实现(测量卫生「区分被挡与不存在」思路
见 arXiv 2606.14525,◆)。

**【已知结果】**(合计 1089 ✓):
| health | 计数 |
|---|---|
| https_alive(证书推断) | 773 |
| ONLINE(真探活) | 259 |
| unknown | 24 |
| CLOUDFLARE_OR_BLOCKED | 13 |
| DNS_FAIL | 10 |
| TIMEOUT | 4 |
| HTTP_ERROR | 3 |
| ONLINE_LOGIN_REQUIRED | 2 |
| SERVICE_STOPPED | 1 |
| **合计** | **1089** |

**【未知·漏洞】** ⚠️ ①`CLOUDFLARE_OR_BLOCKED` 把「活着但被 CF 挡」与「真挂」混在一起;
②**773 个 https_alive 是「有证书即推断存活」的兜底,非真探活**,可靠性打折;③**只有 292 站进
持续监测,764 个发现站未追踪 → 真实 churn(流失率)测不了**,需写 limitations。可靠性:DNS_FAIL /
PARKED **高**(定义清晰);CF-blocked / 证书推断存活 **中低**(偏软)。

---

## J. 基础设施富化(enrichment,上面多项的数据来源)

**【怎么做的】** `enrich.py`:证书(CA/指纹/SAN/not_before,TLS 握手直采)、WHOIS(注册商/注册日/
2026-07 新增注册人 org/name/country)、IP(国家/城市/ASN,ip-api)、favicon 哈希。是 C(技术栈)、
E(托管)、F(运营者归并)、H(时间线)的底层数据源。

**【文献背书】** favicon = NDSS'21(⭐);TLS 证书指纹/SAN = Durumeric IMC 2013 + VanderSloot IMC 2016
(⭐);WHOIS 注册日/注册商 = Hao IMC'13 + PREDATOR CCS'16(⭐);ASN 对 CDN 失效 = Cloudflare 文档(○+◆)。

**【已知结果】** 富化覆盖(N=1089):证书 not_before 95% · 证书指纹 95% · WHOIS 注册日 93% ·
WHOIS 注册人机构 34% · IP/ASN ~98% · favicon 83% · **证书 Org(公司名)仅 7 站**。

**【未知·漏洞】** ⚠️ ①**WHOIS 存的历史字段是「注册商(代理商)」非「注册人」**——注册人 org 字段
2026-07 才补采,且 34% 里过滤隐私代理后只剩 38 个真实体;②**免费 DV 证书无公司名**(仅 7 站有
`ssl_org`);③**IP 国家在 CDN/云后是边缘节点位置,≠ 运营者所在国**。这三条共同导致「可追溯率仅
4.0%」(见 `TRACEABILITY.md`),是「结构性反追溯」结论的数据基础。

---

## 附:可靠性总览(哪些标签能放心用)

| 维度 | 可靠性 | 一句话 |
|---|---|---|
| one-api-family(C) | 高 | 多重硬信号 + 96/71 交叉验证 |
| unlabeled / openai-unknown(C) | 中低 | 只是「没指纹」,非「确认异构」;异构论证只用探针复核过的 59 |
| site_role / conversion_layer(B) | 中 | 派生自技术栈;conversion_layer 建议弃用、回归 sub2api |
| signal_tier(D) | A/status 强,C 弱 | 四层探针未全量 |
| hosting_type(E) | 中 | 云主机≈CDN 混淆,direct_origin 偏保守 |
| operator(F) | cert 强 / favicon 弱 | 1000 是上界,真实更集中 |
| template_family(G) | 中低 | 探索性,覆盖 83/1089 |
| birth_year / maturity(H) | 中 | 注册年≠上线年;≤2015 的 29 站疑似假阳性 |
| health(I) | DNS/parked 强,其余软 | 773 为证书推断存活;churn 测不了 |

## 附:数字自检脚本

```bash
python3 - <<'PY'
import csv, collections
cls=list(csv.DictReader(open("results/master/site_classification.csv",encoding="utf-8-sig")))
for dim in ("stack_family","site_role","hosting_type","maturity_tier","health","has_faka","multi_brand_operator"):
    c=collections.Counter((r.get(dim) or "?") for r in cls)
    print(dim, sum(c.values()), dict(c.most_common()))
PY
```

_数字快照 2026-07-13,N=1089;结构不变,计数随数据刷新。文献等级:⭐同行评审顶会/◆期刊或预印本/○业界实践/△标准规范。_
