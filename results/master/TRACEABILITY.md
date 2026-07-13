# 可追溯性 / 结构性反追溯  (N=1089 站)

一个转售商业 AI API 的灰色生态,在网络层/身份层/注册层能否被追到真实运营者?

## 1. 身份信号可得性(可追溯率)

| 信号 | 命中真实实体 | 占比 |
|---|---:|---:|
| WHOIS 注册人机构(非代理) | 38 | 3.5% |
| 证书 Organization(OV/EV) | 6 | 0.6% |
| **合并可追溯(任一硬信号)** | **44** | **4.0%** |

> **核心数字**:1089 个站里,只有 **44 个(4.0%)** 能通过硬信号追到一个疑似真实运营实体。其余 **96%** 结构性地无法归因。

## 2. 追不到的机制(三层反追溯)

| 层 | 遮蔽手段 | 覆盖 |
|---|---|---:|
| 网络层 | 藏 Cloudflare 等 CDN 后,源站 IP 不可见 | 760/1089 (69%) |
| 注册层 | WHOIS 用隐私代理占位(Domains By Proxy 等) | 339/1089 (31%) |
| 证书层 | 免费 DV 证书,无企业实名字段 | 1035/1089 (95%) |

## 3. 漏出真实实体的站(44 个,高价值线索)

| 域名 | 疑似运营实体 |
|---|---|
| 123nhh.com | Dynadot, LLC |
| 1publish.me | hai nan si tuo zhi neng ke ji you xian gong si |
| 91router.ai | ZHENBOYUAN INDUSTRIAL CO., LIMITED |
| aabao.vip | jiang ren bao |
| ai-leapx.com | Domains By Proxy, LLC |
| aiok.club | wangpeng |
| airoute.vip | beijingsucifangwangluokejiyouxiangongsi |
| albagubra.art | zhu yu xuan |
| anpin.ai | Registrant Street: ling shan lu wu zhen |
| ant-ling.com | Alipay Payment Technology Co., Ltd |
| arkvision.ai | Private by Design, LLC |
| catapi.ai | luoxiaojiang |
| cctq.ai | Registrant Street: 4001 Woodridge Lane |
| chatopens.vip | fo shan shi chan cheng qu hai man long xin xi ji shu zi xun buge ti gong shang hu |
| cheapai.ai | Private by Design, LLC |
| chiangma.com | co. |
| corenode.best | Private by Design, LLC |
| cuberouter.ai | Domains By Proxy, LLC |
| eurouter.ai | Bitz &amp; Snoek |
| fastrouter.ai | Registrant Street: 107/108 DIC Bldg 5 Dubai Internet City |
| fishxcode.com | mangoxai |
| flowbarai.com | Dynadot, LLC |
| fuhuacloud.ai | Registrant Street: 天翔大道289号 |
| getunikey.ai | Nxdex Technologies |
| gogogotoken.ai | AUTHENTICAI LIMITED |
| indotoken.ai | "PT.INDO MAJU LISTRIK PT.INDO MAJU LISTRIK" |
| kingflow.ai | STARFLOW DIGITAL PTE. LTD |
| krizai.ai | Hilmy Shiwam |
| maton.ai | Private by Design, LLC |
| mixroute.ai | Elite Cloud Pte Ltd |
| neonartai.com | N/A |
| onecheckout.ai | OneText Inc. |
| ppchat.vip | Private by Design, LLC |
| rcouyi.com | 重庆欧亿互联网科技有限公司 |
| subtoken.vip | Rowan University |
| tencentcloudmaas.com | Tencent Technology (Shenzhen) Company Limited |
| timesniper.club | Li QinSheng |
| tokenonly.ai | zhiqianda |
| vllm.ai | Registrant Street: 548 Market St, PMB 57274 |
| wkapi.club | su song xian wu kong shang wu fu wu zhong xin |
| wlai.vip | chongqingyunzhiwuwangluokejiyouxiangongsi |
| xaix.me | bei jing shu ju tiao dong ke ji you xian gong si |
| xfyun.cn | 科大讯飞股份有限公司 |
| xpoz.ai | Registrant Street: 2500 el camino real |

## 4. 隐私政策实质(有政策的 182 站;16% 覆盖 = 静态下界)

> ⚠️ 静态爬虫下界:JS 渲染站会漏抓,Playwright 重抓后此数上升。


**适用法律**
- 未明确说明: 161 (88%)
- 中国法律: 8 (4%)
- 新加坡法律: 6 (3%)
- 欧盟/GDPR: 5 (2%)
- 美国法律: 2 (1%)

**第三方共享**
- 未提及: 113 (62%)
- 提及: 69 (37%)

**数据收集声明**
- 未明确说明: 136 (74%)
- 会收集数据: 26 (14%)
- 声称不收集: 20 (10%)

> 即便有隐私政策,**88% 连适用法律都不声明** —— 政策多为形式化空文。
