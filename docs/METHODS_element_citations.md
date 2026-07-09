# 元素级方法 → 文献对照表 — 2026-07-08

代码里用到的**每一个**具体信号 / 判据 / 算法,对应到**真实用过它的文献**。多数文献不是研究 LLM 中转站的——它们研究钓鱼、恶意基础设施、托管集中度等——但**用了同一个技术**,所以我们"直接拿来用"是有先例、可辩护的。

**证据等级**(写作时分量不同,务必区分):
- ⭐ 同行评审顶会/顶刊(USENIX Security / NDSS / RAID / EuroS&P / IEEE 等)——可作方法权威引用
- ◆ 期刊 / arXiv 预印本 / 较低选择性会议——可引,但注明预印本
- ○ 业界 / OSINT / 厂商文档——只能作"实践佐证",**不能**当学术权威
- △ 标准算法 / 规范——引经典出处即可,无需实证论文

> ⚠️ 引文标题/会议来自检索,**写进论文前每篇再核作者全名+年份+卷期**(未逐篇下载 PDF)。

---

## A. 站点归一化与主表(`build_master.py` / `domain_utils.py`)

| # | 我们做的 | 文献 / 出处 | 等级 |
|---|---------|-----------|------|
| A1 | **eTLD+1 / registrable domain** 归一化,把 `api.x`、`www.x`、`x` 折叠成一行 | Public Suffix List(Mozilla 规范,eTLD 计算的事实标准);DomainsProject *Internet Concentration Index* 明确"reduce every name to its registrable apex (eTLD+1) under ICANN public-suffix rules, count each apex once" | △ 规范 + ○ 实践 |
| A2 | 去协议/www/路径/小写的 host 归一化 | 同上(PSL 规范);web 测量普遍前置步骤 | △ |
| A3 | 多源按 domain 外连接成"每站一行"主表 | 标准数据工程,无需专引;测量论文的常规 preprocessing | △ |

**可写的话术**:域名归并到 eTLD+1 是 web/DNS 测量的标准做法(PSL 规范;集中度测量按 registrable apex 计数)。

---

## B. 技术栈指纹(`tech_stack_fingerprint_probe.py`)

| # | 我们做的 | 文献 / 出处 | 等级 |
|---|---------|-----------|------|
| B1 | **HTTP `Server` 头 / banner grabbing** 识别服务端软件 | OWASP WSTG *Fingerprint Web Server*;*Fingerprinting web servers through Transformer-encoded HTTP response headers*(arXiv 2404.00056) | ◆ + ○ 标准 |
| B2 | **Web 应用指纹**(body 关键词 / 端点 / 版本)识别 new-api/one-api 等实现 | Kondracki & Nikiforakis, *Smudged Fingerprints / WASABO*, **USENIX Security 2024**;OWASP WSTG *Fingerprint Web Application Framework* | ⭐ |
| B3 | **独有响应头**(`X-New-Api-Version`)+ **未认证状态端点 JSON**(`/api/status` 的 `system_name`/`version`)作强信号 + **版本抽取** | WASABO(USENIX Sec 2024,含版本识别);OWASP WSTG(header/endpoint/error-page banner) | ⭐ |
| B4 | **三层置信度**(fork / family / domain),family 信号不升 fork | OWASP WSTG 的 "evidence strength"(strong/weak 分级)概念;WASABO 实证指出指纹工具会**过度声称**——我们分层正是防过度声称 | ⭐ + ○ |
| B5 | **自建实例做 ground-truth 差分** | WASABO 容器 testbed(USENIX Sec 2024,起上千版本评准确率);Noroozian et al. ground-truth(USENIX Sec 2019) | ⭐ |
| B6 | unknown 拆 `blocked`/`spa_shell`/`unreachable`/`unidentified`(不把活站当死站) | 测量卫生;*Detecting Bot Detection: ... Implications for Web Measurement Research*(arXiv 2606.14525)——测量里区分"被挡"与"不存在"的必要性 | ◆ |

**可写的话术**:栈识别用 banner + 应用指纹(OWASP WSTG;WASABO USENIX Sec'24),并用自建实例做 ground-truth 校准——WASABO 正是这套评测范式;分层置信度回应 WASABO 关于指纹工具过度声称的发现。

---

## C. 基础设施富化信号(`enrich.py`)

| # | 信号 | 文献 / 出处 | 等级 |
|---|------|-----------|------|
| C1 | **favicon 哈希** | Solomos, Kristoff, Kanich, Polakis, *Tales of Favicons and Caches*, **NDSS 2021**(favicon 作稳定指纹);Shodan mmh3 favicon(归并/穿透 CDN 找源站) | ⭐ + ○ |
| C2 | **TLS 证书指纹**(同证书=同源) | **Durumeric et al., *Analysis of the HTTPS Certificate Ecosystem*, IMC 2013**(Internet-wide 扫证书,按 issuer/SAN 分析);**VanderSloot et al., *Towards a Complete View of the Certificate Ecosystem*, IMC 2016**;*Unsupervised Detection and Clustering of Malicious TLS Flows*(SCN 2023);Vidar 22 台服务器靠相同 issuer DN 归并 | ⭐(IMC)+ ◆ |
| C3 | **证书 SAN**(一张证书覆盖的所有域名) | **Durumeric et al., IMC 2013**(证书 SAN/subject 大规模分析);**VanderSloot et al., IMC 2016**;*TLS Certificate and Domain Feature Analysis of Phishing Domains in the .dk Namespace*(arXiv,显式用 **SAN overlaps + certificate reuse + graph clustering**) | ⭐(IMC)+ ◆ |
| C4 | **ASN / 托管商**;并把 **ASN 作粗信号、CDN 后不可信** | ASN 是托管归属的标准信号但对 CDN 失效——Cloudflare 匿播共享 IP(Cloudflare 官方文档);实测 Cloudflare 占 AS-matched A records 的 40%;bot-detection 测量论文(arXiv 2606.14525) | ○ + ◆(**这条是我们 CDN 排除护栏的依据**) |
| C5 | **WHOIS 注册日期(域龄)/ 注册商** | **Hao et al., *Understanding the Domain Registration Behavior of Spammers*, IMC 2013**;**Hao et al., *PREDATOR: ... Domain Abuse at Time-Of-Registration*, CCS 2016**(显式用 WHOIS 创建日期 + 注册商 + 注册时特征);registrant clustering 是 coordinated-abuse 可靠指标 | ⭐(IMC/CCS) |
| C6 | IP GeoIP 国家/城市 | 标准 GeoIP,无需专引 | △ |

**可写的话术**:favicon 作指纹信号见 NDSS'21;证书指纹 + SAN 作同源信号见恶意 TLS 聚类与 .dk 钓鱼证书分析(SAN overlaps + certificate reuse);ASN 我们**明确标注对 CDN 无效**(Cloudflare 共享匿播 IP),这是已知测量局限。

---

## D. 运营者归并 / 聚类(`operator_matching.py`)

| # | 我们做的 | 文献 / 出处 | 等级 |
|---|---------|-----------|------|
| D1 | **连通分量 / 并查集**把共享信号的域名归并成运营者簇 | **Konte, Perdisci, Feamster, *ASwatch: An AS Reputation System to Expose Bulletproof Hosting ASes*, SIGCOMM 2015**;**Chen et al. (Nadji, Perdisci, Antonakakis), *Practical Attacks Against Graph-based Clustering*, CCS 2017**(确认图聚类是恶意基础设施归并的标准手段);*Co-Clustering Host-Domain Graphs*;ShadowSyndicate 靠共享指纹+复用托管归并 | ⭐(SIGCOMM/CCS)+ ○ |
| D2 | 归并边:**同证书指纹 / SAN 互含 / 同 favicon / 同 IP / 同联系方式** | 证书复用(C2/C3);favicon(C1);registrant/contact clustering(C5);同 IP 连接同一 campaign(D1 来源) | 见各信号行 |
| D3 | **CDN 证书 / CDN IP 排除护栏**(CF Universal SSL 共享证书 + 匿播共享 IP 不参与归并) | Cloudflare 共享匿播 IP + 一张 Universal SSL 挂多客户域名(Cloudflare 文档;C3 的 "high SAN = reuse" 警示)——**不排除就会像共享 IP 一样错并** | ○ + ◆(我们的关键正确性护栏) |
| D4 | **剔除默认 favicon**(one-api 图标 103 站共用) | favicon 是 "indicator, not proof",默认/共用图标会造成假聚类(Shodan/OSINT 实践共识) | ○ |
| D5 | **高频通用信号频率过滤**(如误报 wechat 值) | 类比 IDF / 相似度聚类中下调通用特征权重 | △ |
| D6 | **HHI 集中度指数** | Zembruzki et al., *Hosting Industry Centralization and Consolidation*(IEEE/TMA 2022,直接用 HHI,>2500=高度集中);DomainsProject ICI | ⭐/◆ |
| D7 | **Jaccard / 集合重叠相似度**(拆 unknown、结构相似度聚类,规划中) | Jaccard 聚类网站结构 / 钓鱼 kit 同源;大规模暗网研究用 Jaccard distance 聚 HTML 得 33,217 重复→1,021 簇;*Phishing Site Detection Using Similarity of Website Structure* | ◆/○ |

**可写的话术**:把共享信号(证书/favicon/IP/联系方式)建图取连通分量归并运营者,是恶意基础设施归并的标准范式(host-domain 图聚类;共享指纹/IP 归并 campaign);集中度用 HHI(Zembruzki'22);CDN 信号排除是基于 Cloudflare 共享匿播/共享证书的已知局限。

---

## E. 证书 SAN → 兄弟域名发现(`cert_siblings.py`)

| # | 我们做的 | 文献 / 出处 | 等级 |
|---|---------|-----------|------|
| E1 | 从证书 SAN 抽运营者**兄弟域名**当发现种子 | *Content-Agnostic Detection of Phishing Domains using Certificate Transparency and Passive DNS*(**RAID 2022**);*Using Certificate Transparency Logs for Target Reconnaissance*(**EuroS&P 2023**,UCSB);**Scheitle et al., *The Rise of Certificate Transparency and Its Implications on the Internet Ecosystem*, IMC 2018**(CT 暴露证书 DNS 名的含义);*Finding Phish in a Haystack*(arXiv 2106.12343)——CT/证书 SAN 记录全部签发主机名 → **域名/子域枚举**标准手段 | ⭐(RAID/EuroS&P/IMC)+ ◆ |
| E2 | 排除 CDN / 共享证书的 SAN(apenft 那串) | 同 C4/D3(CF 共享证书 SAN 挂无关客户域名) | ○ + ◆ |
| E3 | 证据链(来源站 + 证书指纹 + 原始 SAN) | 可复现/可审计原则;同 C2 的 issuer-DN 追踪范式 | △ |

**可写的话术**:用证书 SAN 揭示同一运营者拥有的兄弟域名、作为种子扩展,与用 Certificate Transparency 日志做域名/子域枚举同源(RAID'22;EuroS&P'23)——我们读的是活证书的 SAN,信号等价。

---

## F. 总体框架 / 种子 / 伦理(见 `METHODS_literature_grounding_2026-07-08.md`)

| # | 元素 | 文献 | 等级 |
|---|------|------|------|
| F1 | 灰产基础设施生态实证刻画 | Noroozian et al., *Platforms in Everything*(BPH),**USENIX Sec 2019**;Antonakakis et al., *Understanding the Mirai Botnet*,**USENIX Sec 2017** | ⭐ |
| F2 | 种子偏差(榜单/论坛来源有偏,须写 limitations) | Santanna et al., *Stress Testing the Booters*(2015,样本=论坛有口碑的 15 家) | ⭐ |
| F3 | 只读探测伦理(公共端点 GET、低速率、不登录、不发攻击 payload) | BPH/booter 测量论文的 ethics 段落可参照 | ⭐ |

---

## 一句话给写作用

**没有一个元素是我们凭空发明的**:eTLD+1 归一化(PSL)、banner+应用指纹(OWASP/WASADO)、favicon(NDSS'21)、证书指纹+SAN(恶意 TLS 聚类 / .dk 钓鱼)、连通分量归并(host-domain 图聚类)、HHI(Zembruzki'22)、CT/SAN 域名发现(RAID'22/EuroS&P'23)——每个都有用过它的文献。我们的原创只在**组合方式**和**针对 CDN 的正确性护栏**;后者本身也基于 Cloudflare 共享匿播/共享证书的公开事实。

## Sources(核对用)

- Public Suffix List — https://publicsuffix.org/ · Mozilla PSL 规范
- DomainsProject Internet Concentration Index — https://domainsproject.org/blog/who-controls-the-internet-2026
- OWASP WSTG, Fingerprint Web Server — https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/01-Information_Gathering/02-Fingerprint_Web_Server
- Fingerprinting web servers through Transformer-encoded HTTP headers — https://arxiv.org/pdf/2404.00056
- Kondracki & Nikiforakis, WASABO / Smudged Fingerprints, USENIX Sec 2024 — https://www.usenix.org/system/files/usenixsecurity24-kondracki.pdf
- Solomos et al., Tales of Favicons and Caches, NDSS 2021 — https://www.ndss-symposium.org/ndss-paper/tales-of-favicons-and-caches-persistent-tracking-in-modern-browsers/
- Unsupervised Detection and Clustering of Malicious TLS Flows — https://arxiv.org/pdf/2109.03878
- TLS Certificate and Domain Feature Analysis of Phishing Domains (.dk) — https://arxiv.org/html/2603.21652v1
- Content-Agnostic Detection of Phishing Domains using CT and Passive DNS, RAID 2022 — https://dl.acm.org/doi/10.1145/3545948.3545958 · https://alleychoo.github.io/papers/raid_phicious.pdf
- Using Certificate Transparency Logs for Target Reconnaissance, EuroS&P 2023 — https://sites.cs.ucsb.edu/~chris/research/doc/eurosnp23_certvuln.pdf
- Finding Phish in a Haystack (CT logs) — https://arxiv.org/pdf/2106.12343
- Co-Clustering Host-Domain Graphs to Discover Malware Infection — https://www.researchgate.net/publication/337015780
- Zembruzki et al., Hosting Industry Centralization and Consolidation, 2022 — https://arxiv.org/abs/2109.01187
- Detecting Bot Detection: Implications for Web Measurement Research — https://arxiv.org/pdf/2606.14525
- Phishing Site Detection Using Similarity of Website Structure — https://www.researchgate.net/publication/350825005
- Cloudflare shared anycast IP ranges (attribution limitation) — https://developers.cloudflare.com/fundamentals/concepts/cloudflare-ip-addresses/
- Noroozian et al., Platforms in Everything (BPH), USENIX Sec 2019 — https://www.usenix.org/conference/usenixsecurity19/presentation/noroozian
- Antonakakis et al., Understanding the Mirai Botnet, USENIX Sec 2017 — https://www.usenix.org/system/files/conference/usenixsecurity17/sec17-antonakakis.pdf
- Santanna et al., Stress Testing the Booters, 2015 — https://arxiv.org/pdf/1508.03410
- Durumeric, Kasten, Bailey, Halderman, Analysis of the HTTPS Certificate Ecosystem, IMC 2013 — https://conferences.sigcomm.org/imc/2013/papers/imc257-durumericAemb.pdf
- VanderSloot, Amann, Bernhard, Durumeric, Bailey, Halderman, Towards a Complete View of the Certificate Ecosystem, IMC 2016 — https://experts.illinois.edu/en/publications/towards-a-complete-view-of-the-certificate-ecosystem/
- Scheitle et al., The Rise of Certificate Transparency and Its Implications on the Internet Ecosystem, IMC 2018 — https://dl.acm.org/doi/10.1145/3278532.3278562
- Hao, Thomas, Paxson, Feamster, Kreibich, Grier, Hollenbeck, Understanding the Domain Registration Behavior of Spammers, IMC 2013 — (ACM IMC 2013)
- Hao, Kantchelian, Miller, Paxson, Feamster, PREDATOR: Proactive Recognition and Elimination of Domain Abuse at Time-Of-Registration, CCS 2016 — https://www.icir.org/vern/papers/predator-ccs16.pdf
- Konte, Perdisci, Feamster, ASwatch: An AS Reputation System to Expose Bulletproof Hosting ASes, SIGCOMM 2015 — (ACM SIGCOMM 2015)
- Chen, Nadji, Kountouras, Monrose, Perdisci, Antonakakis, Vasiloglou, Practical Attacks Against Graph-based Clustering, CCS 2017 — (ACM CCS 2017)
