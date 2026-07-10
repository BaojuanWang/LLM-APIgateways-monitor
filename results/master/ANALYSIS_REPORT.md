# LLM 中转站生态 · 深度特征分析

样本:**809 个站点**(发现层 764 ∪ 监测 292,按注册域归并)。快照 2026-07-10。
本报告仅用已采集数据、纯本地计算。每节标注覆盖率;低覆盖的字段结论仅供参考。

---

## 1. 存活状态

### 健康分布

_HTTPS 握手成功≈活着:675/809 (83%)。仅 292 站在持续监测,764 发现站为'发现时确认',未追踪 churn。_

| 值 | 站数 | 占比 |
|---|---:|---:|
| HTTPS 可达(未持续监测) | 454 | 56.1% |
| 在线(持续监测) | 259 | 32.0% |
| 未响应 | 63 | 7.8% |
| 疑似失效 | 18 | 2.2% |
| 被挡/CF 挑战 | 13 | 1.6% |
| 在线·需登录 | 2 | 0.2% |

> **要点**:约 5/6 站点富化时 HTTPS 可达;但 764 发现站未进监测循环,真实存活/消亡率需把它们纳入纵向监测才能测。

## 2. 技术栈

### 栈家族(统一归类)

| 值 | 站数 | 占比 |
|---|---:|---:|
| one-api-family | 631 | 78.0% |
| unlabeled | 153 | 18.9% |
| sub2api | 14 | 1.7% |
| openai-compatible-unknown | 7 | 0.9% |
| confirmed-unknown | 4 | 0.5% |

### 发现层框架细分

| 值 | 站数 | 占比 |
|---|---:|---:|
| new-api/one-api系 | 524 | 64.8% |
| (未进发现层) | 157 | 19.4% |
| one-api | 72 | 8.9% |
| new-api | 29 | 3.6% |
| sub2api | 14 | 1.7% |
| openai_compatible_unknown | 7 | 0.9% |
| unknown | 4 | 0.5% |
| voapi | 2 | 0.2% |

> **要点**:one-api 家族 631/809(78%)—— 近乎单一栈,指纹级单点脆弱(Geer 2003 monoculture)。

## 3. 生态时间线(站点出生)

### 按年份

_WHOIS 注册时间 + 证书 not_before 补 · 802/809 可查(~99%)_

| 值 | 站数 | 占比 |
|---|---:|---:|
| 2026 | 441 | 55.0% |
| 2025 | 158 | 19.7% |
| 2024 | 75 | 9.4% |
| 2023 | 69 | 8.6% |
| ≤2022 | 59 | 7.4% |

> **要点**:441/802(55%)出生于 2026;73% 在 2025–2026 —— 极年轻、爆发式增长。

### 2025–2026 按月(井喷曲线)

_仅 2025-2026_

| 值 | 站数 | 占比 |
|---|---:|---:|
| 2026-05 | 119 | 19.9% |
| 2026-06 | 102 | 17.0% |
| 2026-04 | 82 | 13.7% |
| 2026-03 | 75 | 12.5% |
| 2026-01 | 32 | 5.3% |
| 2026-02 | 23 | 3.8% |
| 2025-12 | 18 | 3.0% |
| 2025-10 | 16 | 2.7% |
| 2025-08 | 16 | 2.7% |
| 2025-09 | 15 | 2.5% |
| 2025-11 | 14 | 2.3% |
| 2025-03 | 14 | 2.3% |
| 2025-07 | 13 | 2.2% |
| 2025-01 | 13 | 2.2% |
| 2025-02 | 12 | 2.0% |
| 2025-06 | 10 | 1.7% |
| 2025-05 | 9 | 1.5% |
| 2025-04 | 8 | 1.3% |
| 2026-07 | 8 | 1.3% |

## 4. 基础设施

### 源站国家

_仅有 IP 的 709 站;CF 后为边缘位置_

| 值 | 站数 | 占比 |
|---|---:|---:|
| Canada | 299 | 42.2% |
| United States | 239 | 33.7% |
| Hong Kong | 62 | 8.7% |
| China | 41 | 5.8% |
| Singapore | 33 | 4.7% |
| Japan | 14 | 2.0% |
| South Korea | 4 | 0.6% |
| (未知) | 4 | 0.6% |
| Germany | 3 | 0.4% |
| Finland | 2 | 0.3% |

### 托管商 / ASN

_704 站有 ASN;CF 占比高=边缘非源站_

| 值 | 站数 | 占比 |
|---|---:|---:|
| Cloudflare | 296 | 42.0% |
| Amazon.com | 50 | 7.1% |
| OVH SAS | 38 | 5.4% |
| Alibaba (US) Technology Co. | 29 | 4.1% |
| NetLab Global | 23 | 3.3% |
| IT7 Networks Inc | 19 | 2.7% |
| DMIT Cloud Services | 18 | 2.6% |
| Tencent Building | 17 | 2.4% |
| ACE | 15 | 2.1% |
| Hangzhou Alibaba Advertising | 14 | 2.0% |
| FASTNET DATA INC | 13 | 1.8% |
| Shenzhen Tencent Computer Sy | 12 | 1.7% |

### 证书 CA

_675 站有证书_

| 值 | 站数 | 占比 |
|---|---:|---:|
| Let's Encrypt | 386 | 57.2% |
| Google Trust Services | 186 | 27.6% |
| TrustAsia | 23 | 3.4% |
| Amazon | 16 | 2.4% |
| DigiCert | 15 | 2.2% |
| SSL Corporation | 14 | 2.1% |
| ZeroSSL | 12 | 1.8% |
| Asseco Data Systems S.A. | 5 | 0.7% |
| Sectigo | 3 | 0.4% |
| DNSPod, Inc. | 3 | 0.4% |
| WoTrus CA Limited | 3 | 0.4% |
| Beijing Xinchacha Credit | 2 | 0.3% |
| GlobalSign nv-sa | 2 | 0.3% |
| Aliyun Computing Co, Ltd | 1 | 0.1% |
| GoDaddy.com | 1 | 0.1% |
| EnVers Group SIA | 1 | 0.1% |
| Henan Fierce Fire Networ | 1 | 0.1% |
| Leocert LLC | 1 | 0.1% |
| GoDaddy.com, Inc. | 1 | 0.1% |
| sslTrus | 1 | 0.1% |
| 广东堡塔安全技术有限公司 | 1 | 0.1% |

### 域名注册商

_741 站有 WHOIS_

| 值 | 站数 | 占比 |
|---|---:|---:|
| Spaceship, Inc. | 117 | 15.8% |
| Alibaba Cloud Computing Ltd. d | 91 | 12.3% |
| GoDaddy.com, LLC | 68 | 9.2% |
| Cloudflare, Inc. | 67 | 9.0% |
| NameSilo, LLC | 62 | 8.4% |
| DNSPod, Inc. | 53 | 7.2% |
| Cloudflare, Inc | 46 | 6.2% |
| NAMECHEAP INC | 39 | 5.3% |
| 阿里云计算有限公司（万网） | 38 | 5.1% |
| Name.com, Inc. | 15 | 2.0% |
| DYNADOT LLC | 14 | 1.9% |
| 腾讯云计算（北京）有限责任公司 | 10 | 1.3% |

> **要点**:DV 证书(Let's Encrypt/Google Trust)主导 = 免费/自动化签发,零成本起站,与'年轻+海量'一致。

## 5. 技术指纹

### 前端/服务端技术

_从响应头/HTML 粗提取_

| 值 | 站数 | 占比 |
|---|---:|---:|
| React | 423 | 52.3% |
| Cloudflare | 299 | 37.0% |
| Nginx | 227 | 28.1% |
| NewAPI | 168 | 20.8% |
| Vue | 58 | 7.2% |
| Next.js | 7 | 0.9% |
| OneAPI | 3 | 0.4% |
| Apache | 1 | 0.1% |

### Server 头

| 值 | 站数 | 占比 |
|---|---:|---:|
| cloudflare | 293 | 45.8% |
| nginx | 227 | 35.5% |
| openresty | 38 | 5.9% |
| vercel | 17 | 2.7% |
| caddy | 11 | 1.7% |
| esa | 7 | 1.1% |
| cdn | 5 | 0.8% |
| photon-edge | 5 | 0.8% |

## 6. 域名特征

### 顶级域(TLD)

| 值 | 站数 | 占比 |
|---|---:|---:|
| com | 227 | 28.1% |
| ai | 167 | 20.6% |
| cn | 75 | 9.3% |
| top | 72 | 8.9% |
| cc | 52 | 6.4% |
| xyz | 33 | 4.1% |
| org | 23 | 2.8% |
| net | 19 | 2.3% |
| vip | 19 | 2.3% |
| pro | 12 | 1.5% |
| io | 11 | 1.4% |
| dev | 10 | 1.2% |

### 域名关键词主题

_域名中包含该词的站数(可重叠)_

| 值 | 站数 | 占比 |
|---|---:|---:|
| ai | 293 | 36.2% |
| api | 136 | 16.8% |
| code | 50 | 6.2% |
| token | 33 | 4.1% |
| one | 22 | 2.7% |
| chat | 21 | 2.6% |
| claude | 15 | 1.9% |
| gpt | 14 | 1.7% |
| hub | 12 | 1.5% |
| cloud | 9 | 1.1% |
| new | 3 | 0.4% |
| proxy | 1 | 0.1% |

## 7. 运营 / 商业模式信号(覆盖有限)

- **推广/代理页**:82/260 有(32%)—— 分销返佣是主流获客(covered 260 站)。
- **隐私政策**:123/284 有(43%,仅监测子集)。
> 联系方式(TG/QQ/微信)当前抽取覆盖低,是已知的采集短板(见 AUDIT),需渲染后 DOM 才能救回。

## 8. 运营者集中度

- 809 域名 → **743 个运营者**,其中 **44 个多站运营者**,最大 6 域名。
- **诚实**:整体集中度低(HHI≈0.0015)—— 多数站独立运营;'集中'主要体现在**单一技术栈**,而非少数人控制全部。

| 运营者 | 域名数 | 归并依据 | 成员 |
|---|---:|---|---|
| ablai.top | 6 | favicon=['4214f2244b29']; ip=['64.32.23. | ablai.top, bltcy.ai, bltcy.top, geekai.pro, linkapi.org, wha |
| africarouter.ai | 5 | favicon=['c30c7d42707a'] | africarouter.ai, easy-token.com, ocoolai.com, therouter.ai,  |
| bdshmmkj3.cn | 5 | ip=['172.83.153.31']; sitename=['aicost  | bdshmmkj3.cn, daikuankm.cn, oogaming.cn, racetozero.org.cn,  |
| ai-gaochao.cn | 4 | favicon=['2aeb552a8ba7']; ip=['43.169.13 | ai-gaochao.cn, openai-hub.com, orcarouter.ai, shubiaobiao.cn |
| 147ai.cn | 3 | ip=['157.185.163.113']; sitename=['147 a | 147ai.cn, 147ai.com, 580ai.net |
| a8.hk | 3 | sitename=['便携ai聚合api'] | a8.hk, bianxie.ai, bianxieai.com |
| aigc456.top | 3 | ip=['154.21.93.129']; sitename=['钱多多 api | aigc456.top, aigcbest.top, ifopen.ai |
| ainstant.pro | 3 | ip=['154.44.9.242']; sitename=['快稳稳 api' | ainstant.pro, kuaiwenwen.top, kwwai.top |
| buzz7.top | 3 | sitename=['buzz · ai'] | buzz7.top, buzzai.cc, buzzai.top |
| ephone.ai | 3 | favicon=['67a3ef99e381']; sitename=['eph | ephone.ai, ephone.chat, innk.cc |
| hcnote.cn | 3 | ip=['163.181.214.1'] | hcnote.cn, joyzhi.com, littlesheep.cc |
| onechats.ai | 3 | sitename=['onechat api'] | onechats.ai, onechats.cn, onechats.top |

## 9. 交叉分析:栈 × 国家

| 栈家族 | Canada | United States | Hong Kong | China | Singapore |
|---|---|---|---|---|---|
| sub2api | 7 | 5 | 0 | 0 | 0 |
| unlabeled | 48 | 24 | 9 | 9 | 4 |
| one-api-family | 242 | 201 | 53 | 32 | 29 |
| openai-compatible-unknown | 0 | 7 | 0 | 0 | 0 |
| confirmed-unknown | 2 | 2 | 0 | 0 | 0 |

---
_方法与文献背书见 `docs/METHODS_element_citations.md`。低覆盖字段(隐私/联系方式/ICP)结论仅供参考。_