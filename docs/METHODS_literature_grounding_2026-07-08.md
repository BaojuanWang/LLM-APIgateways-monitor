# 方法论 → 文献支撑对照 — 2026-07-08

目的:在把新的分类/识别/归并逻辑合进采集器**之前**,先确认这套方法有没有文献撑腰、边界在哪。
每个方法给出:**结论(站得住/有条件/站不住)+ 可引文献 + 论文里该怎么写这条局限**。

> 说明:下列文献的标题/会议均来自检索,**最终引用前请各自核一遍作者全名与年份/卷期**(本 memo 未逐篇下载 PDF 核对)。标 ⭐ 的是同行评审(NDSS/USENIX/IEEE 等),其余为业界/OSINT 实践材料,只能当"实践佐证",不能当学术引用。

---

## 总判断

你现在这套"web 指纹 + favicon/证书归并 + 结构集中度"的组合,**在安全测量文献里是成熟范式,不是裸奔**。三条主线各有同行评审的先例:
1. **地下服务生态的实证刻画**(你的整体 framing)→ 有直接模板(BPH、booter)。
2. **web 应用指纹 + 自建实例做 ground-truth**(你的分类层)→ 有直接方法论(WASABO)。
3. **共享基础设施归并 + HHI 结构集中度**(你的招牌图)→ 有直接方法(证书归并 + 托管集中度)。

风险不在"方法没人用过",而在**边界要写清楚**——每个信号都有已知的失效模式,文献里也都讨论过,你主动写进 limitations 就能扛住 rebuttal。

---

## 1. 整体 framing:地下服务生态的实证刻画

**你要做的**:对一个新兴灰产基础设施生态(LLM 中转)做"组成 + 部署 + 运营"的系统测绘。

**站得住。** 这是安全测量圈一条成熟的线,有可直接对标的模板:

- ⭐ **Noroozian et al., "Platforms in Everything: Analyzing Ground-Truth Data on the Anatomy and Economics of Bullet-Proof Hosting", USENIX Security 2019.** 防弹主机生态的实证刻画——商业模式、供应链、客户、财务。**你的"货源层 sub2api 躲在交付层 new-api 后"这个两层结构,正好对应它"从敏捷 reseller 转向 marketplace 平台、上游来自数百家正规主机商"的供应链发现。**这是你 framing 最硬的对标。
  https://www.usenix.org/conference/usenixsecurity19/presentation/noroozian
- ⭐ **Antonakakis et al., "Understanding the Mirai Botnet", USENIX Security 2017.** 大规模外部探测刻画一类新基础设施的范式(探测 + 归并 + 纵向)。
  https://www.usenix.org/system/files/conference/usenixsecurity17/sec17-antonakakis.pdf
- **Santanna et al., "Booters — DDoS-as-a-Service" / "Stress Testing the Booters" (IM/WWW 2015, arXiv:1508.03410).** 灰产**服务**生态(而非纯恶意软件)的刻画,种子来自论坛/搜索——和你从榜单/GitHub/小红书滚种子同构。**它也是你"种子偏差"局限的引用来源**(它明说样本 = 论坛上有口碑的 15 家,天然有偏)。
  https://arxiv.org/pdf/1508.03410

**论文里怎么写**:把 LLM 中转定位成"一类此前未被系统测绘的 AI 流量中介基础设施",方法论继承 BPH/booter 那条实证刻画线。

---

## 2. 技术栈指纹(你的分类层)

**你要做的**:靠 header / body / 端点识别站点跑的是 new-api / one-api / sub2api 等。

**有条件站得住——但必须配 ground-truth 评测,否则准确率是空口。**

- ⭐ **Kondracki & Nikiforakis, "Smudged Fingerprints: ... Web Application Fingerprinting" / WASABO, USENIX Security 2024.** 这篇对你**极其重要**:它用容器起了上千个软件版本(如 558 个 WordPress 版本)做 testbed,评测 Wappalyzer/WhatWeb/BlindElephant 等六个指纹工具的准确率,并指出它们在混淆/改版下准确率显著下降。**这既是"自建实例做 ground-truth 差分"的方法论出处,也是你诚实标注指纹准确率上限的引用。**
  https://www.usenix.org/system/files/usenixsecurity24-kondracki.pdf
- **OWASP WSTG — Fingerprint Web Application Framework.** 指纹方法(header/cookie/路径/错误页)的标准化实践清单,可当方法描述的工程依据。
  https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/01-Information_Gathering/08-Fingerprint_Web_Application_Framework
- 实践佐证:一项 100 站已知栈的对照测出 Wappalyzer ~94% 准确率,漏的多是冷门/自研栈——**印证"46% 未识别里有相当部分是改壳/SPA 的已知栈,不是真未知"。**

**论文里怎么写**:
- 采 WASABO 式做法——把采集器指向自建 new-api/sub2api + `docker run` 起的 one-api/one-hub 做**差分**,自动生成"信号→栈"标注库,报出每层信号的准确率/漏检率。**这一步没做,分类层就没有可写的准确率数字。**
- 明写指纹分**三层置信度**(独有端点定 fork / 家族级共享文案只能到 family / header 只缩范围),对应审计报告里那三个误判(`new-api|one-api` 双标、`xxx2api` catch-all、SPA→unknown)的形式化修复。

---

## 3. favicon 哈希识别/归并

**你要做的**:用 favicon 哈希识别栈 / 归并同源站点。

**有条件站得住——单独用弱,必须和其它信号叠、且滤掉默认图标。**

- ⭐ **Solomos, Kristoff, Kanich, Polakis, "Tales of Favicons and Caches: Persistent Tracking in Modern Browsers", NDSS 2021.** 学术上确立 **favicon 是稳定、可作指纹的信号**(它做的是持久追踪,但正是靠 favicon 的唯一性/缓存性)。可引来支撑"favicon 哈希作为识别特征"的合法性。
  https://www.ndss-symposium.org/ndss-paper/tales-of-favicons-and-caches-persistent-tracking-in-modern-browsers/
- 实践佐证(Shodan mmh3 favicon 哈希):业界标准做法,用于把共享同一 favicon 的资产归并、并穿透 CDN 找源站。多篇 OSINT 材料一致,但**均声明 favicon 是"indicator, not proof"——易替换、会碰撞、默认图标会造成假聚类**。

**你的数据是活教材**:`0d919cd7c5fa` 占 103/292(35%,one-api 默认图标)——**正是文献警告的"共享默认图标→假聚类"**。你的 `operator_grouping.py` 已经用"频率过滤 + favicon 只算弱信号"两层护栏挡住了,这本身就是可写的 methods 细节。

**论文里怎么写**:favicon 哈希仅作**弱信号**,需与强信号(证书/联系方式)叠加才归并;高频哈希(默认图标)先剔除。引 NDSS'21 立合法性,引默认图标问题写局限。

---

## 4. 证书 SAN / 指纹归并运营者

**你要做的**:同一张证书覆盖多域名 → 归并成同一运营者。

**站得住,是归并里最硬的信号。**

- ⭐ **Hosting Industry Centralization and Consolidation (Zembruzki et al., IEEE/TMA 2022, arXiv:2109.01187)** 及 **Measuring the Consolidation of DNS and Web Hosting Providers (arXiv:2110.15345)**——用证书/托管归并度量集中度,方法与你一致。
  https://arxiv.org/abs/2109.01187 · https://arxiv.org/html/2110.15345
- 实践佐证:钓鱼/恶意基础设施测量普遍用**证书 SAN 重叠 + issuer/subject DN 复用**做图聚类归并(如按相同 issuer DN 追踪 22 台 Vidar 服务器)。TLS 证书作 attribution 信号的材料很多。

**你的现状**:`enrich.py` 已经调了 `getpeercert()`,证书在手,只差抽 SAN + 指纹两行(见审计报告 §2a)。补上后归并从"靠联系方式"升到"靠铁证同源"。

**论文里怎么写**:证书 SAN/指纹为**强信号**;注意 DV 证书(Let's Encrypt)的 subject 常无 organizationName(你数据里 `ssl_org` 100% 空正好印证)——所以归并靠 SAN 与指纹,不靠 subject O。

---

## 5. 结构集中度 / "表面多样、结构集中"(你的招牌 headline)

**你要做的**:几百域名归并后其实是少数运营者;用 HHI 量化集中度。

**站得住,而且你已经在用对的指标。**

- ⭐ **Hosting Industry Centralization and Consolidation (Zembruzki et al., 2022).** 直接用 **HHI(Herfindahl-Hirschman Index)** 度量托管市场集中度——HHI>2500 记为"高度集中",与你 `operator_grouping.py` 里算的 HHI 是同一指标同一解读。**你那句"apparent diversity vs structural concentration"可以直接挂在这条线上。**
- 佐证数据点:该线发现 1/3 域名由仅 5 家托管商承载、3 家第三方服务平均覆盖 91.2% 站点——正是"少数实体控制表面繁荣"的同类结论。

**论文里怎么写**:归并后报 (i) 域名数→运营者数 的压缩比、(ii) 最大运营者占比、(iii) HHI。这三个数就是 headline 的可计算形态,且指标有文献先例(不是你自造)。

---

## 6. 相似度聚类拆 unknown

**你要做的**:特征向量(端点存在性矩阵 + 头集 + favicon + 证书)+ Jaccard + 层次/DBSCAN 聚类,给 unknown 传播标签 / 发现新栈。

**站得住(标准无监督基础设施聚类),但要防两件事**:(a) 共享 CDN/默认图标造成的假聚类(同 §3 护栏);(b) 聚类结果与规则标签冲突时,那是指纹有 bug 的信号(可当自检)。方法本身属常规实践,可在 methods 里作为工程描述,不必强找单篇引用;若要引,可归到上面 §2/§4 的基础设施相似度聚类范式下。

---

## 7. 伦理足迹(审稿人/IRB 必问,顺带记下)

只读探测的合规写法有先例可循:公共端点 GET、低速率、不登录、不发攻击性 payload、不碰改状态接口、UA 标注身份、尊重 robots、端点存在性探测只探存在不触发副作用。BPH/booter 那批测量论文都有对应的 ethics 段落可参照措辞。

---

## 给决策的一句话

**这套方法可以合进去——但合的时候每个信号都要带上它的置信层级和已知失效模式**(favicon/CDN 弱信号、证书强信号、家族级文案不能升 fork 级)。真正还欠的是**第 2 节那步自建实例 ground-truth 评测**:没有它,分类层就只有方法、没有准确率数字。建议顺序:先补证书 SAN(§4,拉满归并)→ 重做指纹分类器(§2,带三层置信)→ 指向自建实例出准确率基线。

---

## Sources(核对用)

- Noroozian et al., Platforms in Everything (BPH), USENIX Sec 2019 — https://www.usenix.org/conference/usenixsecurity19/presentation/noroozian
- Antonakakis et al., Understanding the Mirai Botnet, USENIX Sec 2017 — https://www.usenix.org/system/files/conference/usenixsecurity17/sec17-antonakakis.pdf
- Santanna et al., Stress Testing the Booters, 2015 — https://arxiv.org/pdf/1508.03410
- Kondracki & Nikiforakis, Smudged Fingerprints / WASABO, USENIX Sec 2024 — https://www.usenix.org/system/files/usenixsecurity24-kondracki.pdf
- OWASP WSTG, Fingerprint Web Application Framework — https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/01-Information_Gathering/08-Fingerprint_Web_Application_Framework
- Solomos et al., Tales of Favicons and Caches, NDSS 2021 — https://www.ndss-symposium.org/ndss-paper/tales-of-favicons-and-caches-persistent-tracking-in-modern-browsers/
- Zembruzki et al., Hosting Industry Centralization and Consolidation, 2022 — https://arxiv.org/abs/2109.01187
- Measuring the Consolidation of DNS and Web Hosting Providers — https://arxiv.org/html/2110.15345
