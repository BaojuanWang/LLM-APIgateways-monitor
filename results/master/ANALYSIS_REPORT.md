# LLM 中转站生态 · 深度特征分析

样本:**1089 个站点**(发现层 764 ∪ 监测 292,按注册域归并)。快照 2026-07-10。
本报告仅用已采集数据、纯本地计算。每节标注覆盖率;低覆盖的字段结论仅供参考。

---

## 1. 存活状态

### 健康分布

_HTTPS 握手成功≈活着:1038/1089 (95%)。仅 292 站在持续监测,764 发现站为'发现时确认',未追踪 churn。_

| 值 | 站数 | 占比 |
|---|---:|---:|
| HTTPS 可达(未持续监测) | 774 | 71.1% |
| 在线(持续监测) | 259 | 23.8% |
| 未响应 | 23 | 2.1% |
| 疑似失效 | 18 | 1.7% |
| 被挡/CF 挑战 | 13 | 1.2% |
| 在线·需登录 | 2 | 0.2% |

> **要点**:约 5/6 站点富化时 HTTPS 可达;但 764 发现站未进监测循环,真实存活/消亡率需把它们纳入纵向监测才能测。

## 2. 技术栈

### 栈家族(统一归类)

| 值 | 站数 | 占比 |
|---|---:|---:|
| one-api-family | 838 | 77.0% |
| unlabeled | 144 | 13.2% |
| openai-compatible-unknown | 73 | 6.7% |
| sub2api | 30 | 2.8% |
| confirmed-unknown | 4 | 0.4% |

### 发现层框架细分

| 值 | 站数 | 占比 |
|---|---:|---:|
| new-api/one-api系 | 659 | 60.5% |
| (未进发现层) | 157 | 14.4% |
| one-api | 113 | 10.4% |
| openai_compatible_unknown | 73 | 6.7% |
| new-api | 50 | 4.6% |
| sub2api | 30 | 2.8% |
| unknown | 4 | 0.4% |
| voapi | 3 | 0.3% |

> **要点**:one-api 家族 838/1089(77%)—— 近乎单一栈,指纹级单点脆弱(Geer 2003 monoculture)。

## 3. 生态时间线(站点出生)

### 按年份

_WHOIS 注册时间 + 证书 not_before 补 · 1088/1089 可查(~100%)_

| 值 | 站数 | 占比 |
|---|---:|---:|
| 2026 | 663 | 60.9% |
| 2025 | 192 | 17.6% |
| 2024 | 84 | 7.7% |
| ≤2022 | 75 | 6.9% |
| 2023 | 74 | 6.8% |

> **要点**:663/1088(61%)出生于 2026;73% 在 2025–2026 —— 极年轻、爆发式增长。

### 2025–2026 按月(井喷曲线)

_仅 2025-2026_

| 值 | 站数 | 占比 |
|---|---:|---:|
| 2026-05 | 181 | 21.2% |
| 2026-06 | 158 | 18.5% |
| 2026-04 | 126 | 14.7% |
| 2026-03 | 108 | 12.6% |
| 2026-01 | 42 | 4.9% |
| 2026-02 | 31 | 3.6% |
| 2025-12 | 26 | 3.0% |
| 2025-09 | 21 | 2.5% |
| 2025-10 | 21 | 2.5% |
| 2025-11 | 20 | 2.3% |
| 2025-08 | 18 | 2.1% |
| 2026-07 | 17 | 2.0% |
| 2025-03 | 15 | 1.8% |
| 2025-01 | 15 | 1.8% |
| 2025-07 | 14 | 1.6% |
| 2025-06 | 13 | 1.5% |
| 2025-02 | 12 | 1.4% |
| 2025-05 | 9 | 1.1% |
| 2025-04 | 8 | 0.9% |

## 4. 基础设施

### 源站国家

_仅有 IP 的 1073 站;CF 后为边缘位置_

| 值 | 站数 | 占比 |
|---|---:|---:|
| Canada | 413 | 38.5% |
| United States | 334 | 31.1% |
| Hong Kong | 125 | 11.6% |
| China | 81 | 7.5% |
| Singapore | 57 | 5.3% |
| Japan | 31 | 2.9% |
| South Korea | 9 | 0.8% |
| Germany | 5 | 0.5% |
| Brazil | 4 | 0.4% |
| South Africa | 3 | 0.3% |

### 托管商 / ASN

_1066 站有 ASN;CF 占比高=边缘非源站_

| 值 | 站数 | 占比 |
|---|---:|---:|
| Cloudflare | 410 | 38.5% |
| Amazon.com | 66 | 6.2% |
| Alibaba (US) Technology Co. | 61 | 5.7% |
| Tencent Building | 49 | 4.6% |
| NetLab Global | 48 | 4.5% |
| OVH SAS | 45 | 4.2% |
| Hangzhou Alibaba Advertising | 37 | 3.5% |
| DMIT Cloud Services | 21 | 2.0% |
| Shenzhen Tencent Computer Sy | 21 | 2.0% |
| IT7 Networks Inc | 20 | 1.9% |
| cognetcloud INC | 17 | 1.6% |
| ACE | 16 | 1.5% |

### 证书 CA

_1038 站有证书_

| 值 | 站数 | 占比 |
|---|---:|---:|
| Let's Encrypt | 636 | 61.3% |
| Google Trust Services | 251 | 24.2% |
| TrustAsia | 37 | 3.6% |
| DigiCert | 23 | 2.2% |
| Amazon | 21 | 2.0% |
| ZeroSSL | 20 | 1.9% |
| SSL Corporation | 15 | 1.4% |
| Asseco Data Systems S.A. | 10 | 1.0% |
| WoTrus CA Limited | 5 | 0.5% |
| DNSPod, Inc. | 4 | 0.4% |
| Sectigo | 3 | 0.3% |
| 广东堡塔安全技术有限公司 | 3 | 0.3% |
| Beijing Xinchacha Credit | 2 | 0.2% |
| GlobalSign nv-sa | 2 | 0.2% |
| 泰尔认证中心有限公司 | 2 | 0.2% |
| Aliyun Computing Co, Ltd | 1 | 0.1% |
| GoDaddy.com | 1 | 0.1% |
| EnVers Group SIA | 1 | 0.1% |
| Henan Fierce Fire Networ | 1 | 0.1% |
| Leocert LLC | 1 | 0.1% |
| GoDaddy.com, Inc. | 1 | 0.1% |
| sslTrus | 1 | 0.1% |

### 域名注册商

_1015 站有 WHOIS_

| 值 | 站数 | 占比 |
|---|---:|---:|
| Alibaba Cloud Computing Ltd. d | 145 | 14.3% |
| Spaceship, Inc. | 137 | 13.5% |
| GoDaddy.com, LLC | 93 | 9.2% |
| Cloudflare, Inc. | 92 | 9.1% |
| DNSPod, Inc. | 79 | 7.8% |
| NameSilo, LLC | 78 | 7.7% |
| Cloudflare, Inc | 56 | 5.5% |
| 阿里云计算有限公司（万网） | 51 | 5.0% |
| NAMECHEAP INC | 49 | 4.8% |
| Name.com, Inc. | 21 | 2.1% |
| Gname.com Pte. Ltd. | 14 | 1.4% |
| DYNADOT LLC | 14 | 1.4% |

> **要点**:DV 证书(Let's Encrypt/Google Trust)主导 = 免费/自动化签发,零成本起站,与'年轻+海量'一致。

## 5. 技术指纹

### 前端/服务端技术

_从响应头/HTML 粗提取_

| 值 | 站数 | 占比 |
|---|---:|---:|
| React | 552 | 50.7% |
| Cloudflare | 418 | 38.4% |
| Nginx | 413 | 37.9% |
| NewAPI | 224 | 20.6% |
| Vue | 86 | 7.9% |
| Next.js | 13 | 1.2% |
| OneAPI | 5 | 0.5% |
| Apache | 3 | 0.3% |

### Server 头

| 值 | 站数 | 占比 |
|---|---:|---:|
| nginx | 413 | 42.2% |
| cloudflare | 404 | 41.3% |
| openresty | 48 | 4.9% |
| vercel | 22 | 2.2% |
| caddy | 15 | 1.5% |
| esa | 11 | 1.1% |
| cdn | 8 | 0.8% |
| photon-edge | 7 | 0.7% |

## 6. 域名特征

### 顶级域(TLD)

| 值 | 站数 | 占比 |
|---|---:|---:|
| com | 317 | 29.1% |
| ai | 189 | 17.4% |
| cn | 100 | 9.2% |
| top | 97 | 8.9% |
| cc | 69 | 6.3% |
| xyz | 49 | 4.5% |
| org | 26 | 2.4% |
| net | 25 | 2.3% |
| vip | 25 | 2.3% |
| io | 17 | 1.6% |
| chat | 14 | 1.3% |
| pro | 13 | 1.2% |

### 域名关键词主题

_域名中包含该词的站数(可重叠)_

| 值 | 站数 | 占比 |
|---|---:|---:|
| ai | 377 | 34.6% |
| api | 188 | 17.3% |
| token | 59 | 5.4% |
| code | 56 | 5.1% |
| one | 30 | 2.8% |
| chat | 27 | 2.5% |
| hub | 20 | 1.8% |
| claude | 16 | 1.5% |
| gpt | 15 | 1.4% |
| cloud | 13 | 1.2% |
| new | 3 | 0.3% |
| proxy | 2 | 0.2% |

## 7. 域名命名深挖

### 域名含厂商名

_直接把上游模型商写进域名(可重叠)_

| 值 | 站数 | 占比 |
|---|---:|---:|
| claude | 16 | 1.5% |
| gpt | 15 | 1.4% |
| openai | 5 | 0.5% |
| gemini | 2 | 0.2% |
| deepseek | 1 | 0.1% |
| grok | 1 | 0.1% |
| llama | 1 | 0.1% |

- 域名带 `*2api` 转换层命名:2/1089(0%)
- 域名含数字:120/1089(11%,常见于批量/马甲域名)

## 8. 价格 / 模型可见性(仅监测子集)

### 定价页可达性

_284 站有探测记录_

| 值 | 站数 | 占比 |
|---|---:|---:|
| PUBLIC_JSON | 119 | 41.9% |
| PARSE_FAILED | 88 | 31.0% |
| LOGIN_REQUIRED | 29 | 10.2% |
| NO_MODEL_PAGE_FOUND | 16 | 5.6% |
| SITE_NOT_REACHABLE | 15 | 5.3% |
| CLOUDFLARE_OR_BLOCKED | 13 | 4.6% |
| FETCH_FAILED | 2 | 0.7% |
| PUBLIC_PAGE | 1 | 0.4% |
| SERVICE_STOPPED | 1 | 0.4% |

### 暴露模型数分级

_284 站取到模型列表_

| 值 | 站数 | 占比 |
|---|---:|---:|
| 0(未取到) | 164 | 57.7% |
| 1–20 | 42 | 14.8% |
| 21–50 | 34 | 12.0% |
| 100+ | 27 | 9.5% |
| 51–100 | 17 | 6.0% |

> **要点**:119/284(42%)开放 JSON 定价端点(one-api 家族 `/api/pricing` 默认公开),透明度参差;本项目只统计可见性,不做模型身份核验(不在范围)。

## 9. 运营 / 商业模式信号(覆盖有限)

_operations_probe 覆盖 1085 站_

### 支付 / 变现方式

_站点页面出现的支付/发卡渠道(可重叠)_

| 值 | 站数 | 占比 |
|---|---:|---:|
| alipay | 84 | 7.7% |
| stripe | 66 | 6.1% |
| wechat_pay | 53 | 4.9% |
| usdt_crypto | 46 | 4.2% |
| epay | 45 | 4.1% |
| paypal | 23 | 2.1% |

### 信任话术宣称

_营销宣称,非核实_

| 值 | 站数 | 占比 |
|---|---:|---:|
| stability | 271 | 25.0% |
| no_dilution | 115 | 10.6% |
| no_log | 84 | 7.7% |
| refund | 82 | 7.6% |
| privacy_first | 40 | 3.7% |

- **发卡/卡密系统**:22/1085(2%)

- **推广/代理页**:82/260 有(32%)—— 分销返佣是主流获客(covered 260 站)。
- **隐私政策**:182/1085 有(17%,仅监测子集)。
> 联系方式(TG/QQ/微信)当前抽取覆盖低,是已知的采集短板(见 AUDIT),需渲染后 DOM 才能救回。

## 10. 运营者集中度

- 1089 域名 → **1000 个运营者**,其中 **62 个多站运营者**,最大 6 域名。
- **诚实**:整体集中度低(HHI≈0.0015)—— 多数站独立运营;'集中'主要体现在**单一技术栈**,而非少数人控制全部。

| 运营者 | 域名数 | 归并依据 | 成员 |
|---|---:|---|---|
| ablai.top | 6 | favicon=['4214f2244b29']; ip=['64.32.23. | ablai.top, bltcy.ai, bltcy.top, geekai.pro, linkapi.org, wha |
| bdshmmkj3.cn | 5 | ip=['172.83.153.3']; sitename=['aicost a | bdshmmkj3.cn, daikuankm.cn, oogaming.cn, racetozero.org.cn,  |
| ai-gaochao.cn | 4 | favicon=['2aeb552a8ba7']; ip=['43.169.13 | ai-gaochao.cn, openai-hub.com, orcarouter.ai, shubiaobiao.cn |
| aishuch.com | 4 | discord=['discord.gg/MGtn59qQx']; favico | aishuch.com, aiuxu.com, apib.ai, apimart.ai |
| buzz7.top | 4 | cert_fp=['fc6867fa46358cda7d1cd25696c02b | buzz7.top, buzzai.cc, buzzai.top, wasdxx.xyz |
| codesuc.top | 4 | ip=['163.181.214.1'] | codesuc.top, hcnote.cn, joyzhi.com, littlesheep.cc |
| 147ai.cn | 3 | ip=['138.113.241.54']; sitename=['147 ai | 147ai.cn, 147ai.com, 580ai.net |
| a8.hk | 3 | sitename=['便携ai聚合api'] | a8.hk, bianxie.ai, bianxieai.com |
| aigc456.top | 3 | ip=['154.21.93.129']; sitename=['钱多多 api | aigc456.top, aigcbest.top, ifopen.ai |
| ainstant.pro | 3 | ip=['154.44.9.242']; sitename=['快稳稳 api' | ainstant.pro, kuaiwenwen.top, kwwai.top |
| anyroute.io | 3 | ip=['192.238.249.142'] | anyroute.io, clauqe.ai, dragoncode.codes |
| ephone.ai | 3 | favicon=['67a3ef99e381']; sitename=['eph | ephone.ai, ephone.chat, innk.cc |

## 11. 交叉分析:栈 × 国家

| 栈家族 | Canada | United States | Hong Kong | China | Singapore |
|---|---|---|---|---|---|
| sub2api | 12 | 14 | 0 | 0 | 3 |
| one-api-family | 323 | 264 | 96 | 61 | 42 |
| openai-compatible-unknown | 12 | 20 | 18 | 11 | 7 |
| unlabeled | 64 | 34 | 11 | 9 | 5 |
| confirmed-unknown | 2 | 2 | 0 | 0 | 0 |

## 12. 相似模板家族(特征相似度聚类)

用共享稀有特征(favicon/非CDN ASN/IP/注册商/Server/前端)做 Jaccard 式聚类,得 **26 个模板家族**,覆盖 83 站。这比运营者归并**粗一层**——揭示共享部署模板/搭建商基础设施(未必同一人)。方法依据:网站结构相似度聚类(见 §D7)。

| 家族 | 站数 | 共享特征 | 成员 |
|---|---:|---|---|
| 52ccl.cn | 10 | server:esa | 52ccl.cn;bobdong.cn;codesuc.top;hcnote.cn;iamhc.cn;joyzh |
| aiyahmm.com | 8 | asn:Peekabo Networks | aiyahmm.com;axis.fan;ccode.dev;cdn.ad;monking.ai;shitang |
| ablai.top | 5 | asn:Sharktech;favicon:4214f2244b29 | ablai.top;bltcy.ai;geekai.pro;linkapi.org;whatai.cc |
| ai-gaochao.cn | 5 | asn:ACE | ai-gaochao.cn;api520.pro;openai-hub.com;orcarouter.ai;sh |
| bdshmmkj3.cn | 5 | asn:Spartan Host Ltd;registrar:上海福虎信息科 | bdshmmkj3.cn;daikuankm.cn;oogaming.cn;racetozero.org.cn; |
| guardentry.ai | 4 | registrar:Name.com, Inc.;server:vercel | guardentry.ai;hypereal.cloud;voyageage.com;zernio.com |
| 147ai.cn | 3 | asn:Meteverse Limited. | 147ai.cn;147ai.com;580ai.net |
| anyroute.io | 3 | asn:Antbox Networks Li;ip:192.238.249. | anyroute.io;clauqe.ai;dragoncode.codes |
| callgpt.co.uk | 3 | server:apache;tech:apache | callgpt.co.uk;moyuu.cc;starstartai.com |
| chintao.cn | 3 | asn:CHINA UNICOM China | chintao.cn;code-cli.cn;satuo66.online |
| cognilead.ai | 3 | asn:Fly.io, Inc.;server:fly | cognilead.ai;kunavo.com;teai.io |
| fastgpt.cn | 3 | favicon:2340bd772b87;tech:next.js | fastgpt.cn;fastgpt.io;weisoft.chat |

## 13. 站点多维分类总览

每站的最终分类(`site_classification.csv`,1089 站)。

### 角色(relay/转换层/聚合器/未识别)

| 值 | 站数 | 占比 |
|---|---:|---:|
| relay | 838 | 77.0% |
| unidentified | 221 | 20.3% |
| conversion_layer | 30 | 2.8% |

### 托管类型(CDN后/直连源站)

| 值 | 站数 | 占比 |
|---|---:|---:|
| cdn_fronted | 760 | 69.8% |
| direct_origin | 313 | 28.7% |
| unknown | 16 | 1.5% |

### 成熟度(出生年份+证书)

| 值 | 站数 | 占比 |
|---|---:|---:|
| new_2026 | 663 | 60.9% |
| established | 233 | 21.4% |
| growing_2025 | 192 | 17.6% |
| unknown | 1 | 0.1% |

> **要点**:760/1089(70%)藏在 CDN 后 —— 源站基础设施对外不可见,是不透明性的量化证据。

## 14. 发现方法偏差 × 结构集中(§4.1 核心)

对比两个独立发现方法的技术栈分布,量化 GitHub 代码搜索的偏差。完整论证见 `docs/FINDING_discovery_bias.md`。

> **口径注**:GitHub 计数为发现层原始条目(去重前 764);按 eTLD+1 去重后为唯一站,one-api 占比两口径一致(去重不改变结论)。FOFA 280 本就唯一。分析层其余表 N=1089 为去重口径。

### 技术栈 · GitHub codesearch(框架指纹→有偏)

| 值 | 站数 | 占比 |
|---|---:|---:|
| one-api家族 | 736 | 96.3% |
| sub2api(转换层) | 14 | 1.8% |
| openai兼容·框架未识别 | 8 | 1.0% |
| unknown/空 | 6 | 0.8% |

### 技术栈 · FOFA G1(框架无关→无偏)

| 值 | 站数 | 占比 |
|---|---:|---:|
| one-api家族 | 198 | 70.7% |
| openai兼容·框架未识别 | 66 | 23.6% |
| sub2api(转换层) | 16 | 5.7% |

> **核心对比**:one-api 家族 GitHub 96% vs FOFA 71%(差量化了发现偏差);异构尾 GitHub 2% vs FOFA 24%(GitHub 系统性漏掉)。
> **保守下界表述**:one-api 家族在框架无关发现下占 ~71%,构成集中度的**保守下界**;代码搜索高估集中度(96% vs 71%)并系统性遗漏约 24% 的异构/无法指纹化尾部。该尾部一部分可能是白标 one-api,真实集中度可能更高——无论如何,结论都落在'集中'与'代码搜索有偏'之间。
> **口径**:此对比用按发现来源分组的 `framework` 字段(confirmed);勿与面板的 809-合并 `stack_family`(78%)混用。

### 14.1 拆解那 24% 异构尾(深度指纹复探)

对 FOFA 的 66 个 `openai_compatible_unknown` 尾站跑深度技术栈探针(`scripts/probe_tail.sh`),逐站裁定:

### 尾部裁定

| 值 | 站数 | 占比 |
|---|---:|---:|
| genuine_unknown | 59 | 89.4% |
| hidden_one_api | 5 | 7.6% |
| dead | 2 | 3.0% |

> **收紧下界**:探针在尾部认出 5 个 FOFA 漏检的 one-api(响应头 `x-oneapi-request-id`/`x-new-api-version`,high 置信);剔除 2 个死站后,FOFA one-api 份额由 71% 收紧至 **73%**——集中度是**紧的下界**,并未被大幅低估。
> **尾巴的真实成分**:59 站(21% of FOFA)是**真异构/自研**——可达且无任何 one-api 信号(其中 50 个有真内容、仅 9 个 SPA 空壳为残留模糊项)。即改壳 one-api 只占尾部 8%,尾巴**主体是 GitHub codesearch 结构性失明的真异构生态**。结论方向由此从『两头皆可能』收敛为『代码搜索有偏更硬』。

---
_方法与文献背书见 `docs/METHODS_element_citations.md`。低覆盖字段(隐私/联系方式/ICP)结论仅供参考。_