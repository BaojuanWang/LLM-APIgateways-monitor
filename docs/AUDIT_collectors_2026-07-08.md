# 采集层审计报告 — 2026-07-08

对 `scripts/` 下六个采集脚本做的一次完整审计。方法:**读真实代码 + 对照真实数据 + 复现具体 bug**,不依赖任何口头结论。

- 数据快照:`data/enrichment.csv` (292 行)、`data/contacts.csv` (284)、`data/privacy.csv` (284)、`results/monitor_results.csv` (37,441 行 / 292 域名)。
- 每条结论要么**用真实 `classify()` 调用复现**,要么**用真实数据量化**,证据附在条目里。

## TL;DR

采集层的问题**不在"采得少",而在三处系统性效度隐患**,按严重度排:

1. 🔴 **技术栈分类器从没跑过并提交**,且分类逻辑有三个可复现的误判 → 整条技术栈分析线目前是"有代码、零可信数据"。
2. 🔴 **contacts / privacy 的抽取严重漏检**,真实数据显示 Telegram 只抓到 14/284、隐私政策字段 ~90% 落到"未明确说明" → 这两块的输出目前**不能直接作为发现**。
3. 🟠 **贯穿全局的"静默失败 = 空值"** → 每个采集器 `except: pass`,CSV 里的空分不清是"真没有"还是"这次没抓到";没有任何 `*_status` 字段。对测量论文这是致命的(空 ≠ 否)。

**相对健康的部分**:存活监测流水线 `pipeline.py`(多变体重试 + 超时人工复核)、隐私原始快照留存 + `quality_audit.py` 文本质量分级 —— 这两块设计是对的,可以放心用。

---

## 1. `tech_stack_fingerprint_probe.py` — 🔴 严重(下游全靠它)

### 1a. 输出从未落地
`results/tech_stack_fingerprints.csv` **不在仓库里**(已用 `git ls-files` 确认),`.github/workflows/tech-stack.yml` 只能手动触发。整个技术栈分类层现在是**有代码、零数据**。你之前担心的"够不够全"——它目前是**零覆盖**。

### 1b. 三个可复现的分类误判
以下均用真实 `classify()` 调用复现(见报告末尾复现脚本):

| # | 输入 | 输出 | 问题 |
|---|------|------|------|
| 1 | 无关文案含 `any2api` | `xxx2api / medium` | `xxx2api` 的 catch-all 正则 `\b[a-z0-9_-]+2api\b` 会把**任意** `*2api` 字符串标成 xxx2api。纯噪声标签。 |
| 2 | 真 sub2api 站 | `sub2api\|xxx2api / high` | 同一条 catch-all 给每个真 sub2api 站硬加一个多余的 `xxx2api` 标签。 |
| 3 | new-api fork 残留 `one-api` 字样 | `new-api\|one-api / high` | new-api 和 one-api 的 body 正则**都是 high**,fork 页面残留母体字符串就被双标,且都 high → fork 与母体分不开(这正是"118 个 new-api\|one-api"的成因)。 |

**根因**:`APP_PATTERNS` 里(`tech_stack_fingerprint_probe.py:44-68`)把"能定到具体 fork 的独有信号"和"家族级共享文案"混在同一优先级,且末尾那条 `xxx2api` catch-all 污染一切。

### 1c. SPA 空壳 → unknown(46% 未识别的主要制造机)
React/Vue 空壳站首页 HTML 是 `<div id="root">`,关键字全在 JS bundle 里。脚本不执行 JS、只正则扫 HTML/JSON body → 判 `unknown`。
- **已复现**:空壳 body → `unknown / low`。
- **部分缓解**:脚本确实探测了 `/v1/models`、`/api/status`、`/api/models`,SPA 后端这些端点可能返回 JSON。但——

### 1d. `/api/status` 的 JSON 没被结构化解析
one-api 家族的 `/api/status` 会返回含 `system_name` / `version` 的 JSON。当前只把它当**普通 body 文本**正则扫,**没有解析 JSON 字段** → 拿不到版本号(版本分布这个额外发现做不了),也没把 `system_name` 当作强结构化信号。

### 1e. blocked / dead / SPA 都塌进 `unknown`
Cloudflare challenge 页(**站活着、只是被挡**)判 `unknown / low`,和"真·未识别"无法区分(已复现)。应该拆成独立桶:`spa_shell` / `blocked` / `unidentified`。

### ✅ 已经对的部分(比别窗口审的旧版新)
- `x-new-api-version` 响应头已作为 high 信号(`:45`)—— new-api 独有,有效。
- `/api/status` 已在默认探测路径里(`:31`)。
- 家族/置信度分层的骨架已经在(`family` + `confidence` 字段)。

---

## 2. `enrich.py` — 🟠 高(直接喂运营者归并)

真实数据(N=292)量化:

| 字段 | 缺失率 | 说明 |
|------|--------|------|
| `ssl_org` | **100%** (292/292) | DV 证书 subject 里没有 organizationName → 该字段**完全无用**,应删或换成 SAN。 |
| `favicon_hash` | 12.3% | —— |
| `server_header` | 13.4% | —— |
| `whois_reg_date` | 9.2% | —— |
| `ip_asn` | 5.1% | —— |

### 2a. 没采证书 SAN / 证书指纹 —— 归并最硬的信号缺失
`get_ssl()`(`:109`)已经调了 `getpeercert()`,证书就在手里,但只取了 issuer/org。**同一张证书覆盖多个域名 ≈ 铁证同源**,比联系方式还准。加两行(`cert['subjectAltName']` + 证书指纹)就有。这是归并质量从"及格"到"强"的关键补丁。

### 2b. ASN 被 Cloudflare 污染 43.5%
真实数据:**127/292 (43.5%)** 的 `ip_asn = AS13335 Cloudflare`。近一半站点的 ASN 反映的是 CF 边缘、不是真实源站。任何"托管分布"或"按 ASN 归并"对这 44% 无效 → **必须写进 limitations**。

### 2c. favicon 采集有两个坑
- 真实数据:单一哈希 `0d919cd7c5fa` 占 **103/292 (35%)**,几乎肯定是 one-api 全家桶默认图标 → 归并时若不滤掉,这 103 站会被并成一个假运营者。**本身也是发现**(35% 站共用默认图标 = 栈单一化的硬数据)。
- `get_http_headers()`(`:177`)抓 `/favicon.ico` **不校验 content-type**。SPA 常对该路径返回 `index.html`,会被 md5 成"假唯一图标"。应加"content-type 是 image/*"判断。

### 2d. 静态字段首次失败被永久缓存成空
WHOIS / SSL issuer 只在"新域名"时查一次(`:217` `is_new` 分支),首次抖动失败 → 永久缓存为空、再不重试 → 一次网络抖动毒化该站一辈子。

---

## 3. `contacts.py` — 🟠 高(抽取效度存疑)

### 3a. Telegram 严重漏检
真实数据:`telegram` 只抓到 **14/284**,而 `wechat` 抓到 65、`affiliate` 82。对这个以 Telegram 为主渠道的生态,14 是**不可信的低值**。根因:联系方式常在 JS 渲染的页脚 / 图标链接 / 图片里,而脚本只对 `GET /` 的**原始 HTML** 正则。假阴性主导。

### 3b. `t.me/+invite` 邀请码被截断
正则 `t.me/([a-zA-Z0-9_+]+)` 的字符类遇到其它字符即停,私有邀请链接(`t.me/+XXXX` 含非字母数字)会被截断(真实数据里可见 `t.me/+OjE`、`t.me/+_QKy` 这类被砍短的值)。

### 3c. 同样的静默失败
`fetch_html` 失败时只打印"无法访问",CSV 里 contacts 字段留空 → 与"真的没有联系方式"无法区分。

---

## 4. `privacy.py` — 🟠 高(抽取效度弱)

### 4a. `has_privacy=无` 是三种情况的混合
真实数据:**161/284 (57%)** 判"无隐私政策"。但这混了 (i) 真没有、(ii) fetch 失败、(iii) SPA 把政策渲染在非固定路径。`PRIVACY_PATHS` 是固定 8 条路径,漏掉路由式 SPA。

### 4b. 规则式 `analyze()` 几乎抽不出东西
在 **确实有隐私政策的 123 个站**里:
- `applicable_law` = "未明确说明" 占 **111/123 (90%)**
- `collect_data` = "未明确说明" 占 **107/123 (87%)**

即结构化字段对 ~90% 的政策页**没提取到有效信息** → 目前**不能作为分析变量**。需要上 LLM 编码(`quality_audit.py` 已经在为这一步做文本质量预筛,但真正的编码步骤还没接上)。

### ✅ 已经对的部分
- **原始快照留存**(`save_snapshot`)→ 政策原文都在 `data/privacy_snapshots/`,后续重新编码不用重爬。
- `content_changed` 哈希追踪政策变更。
- `quality_audit.py`(435 行)把 SPA 噪声 / 空页 / 可用政策文本分级 —— 只审文本质量,不审抽取正确性,但这是对的第一步。

**结论**:privacy 的原料是好的、可恢复的,坏的只是 `analyze()` 这层薄规则。修复 = 接 LLM 编码,不用重爬。

---

## 5. `pipeline.py`(存活监测)— 🟢 相对健康

这是最成熟的一块,真实数据佐证(292 域名最新快照):`ONLINE 259 / CLOUDFLARE_OR_BLOCKED 13 / DNS_FAIL 10 / TIMEOUT 4 / HTTP_ERROR 3 / ONLINE_LOGIN_REQUIRED 2 / SERVICE_STOPPED 1`。

- ✅ 多变体重试(https / www / http)、超时进 `needs_review.csv` 待人工用国内网络复核、`STOPPED_SERVICES` 人工覆盖。
- 🟡 唯一瑕疵:`CLOUDFLARE_OR_BLOCKED` 把 cf-challenge(**活着但被挡**)和 521/522(**源站宕机**)混在一桶,但只影响 13/292,属小问题。
- 🟡 同一 URL 内无二次重试(但多变体 + needs_review 已缓解)。

---

## 6. 最硬的验证手段(尚未做)

自建的 **new-api / sub2api 实例是完美 oracle**。把三个采集器指向自己这两个实例:
- 指纹认不认得出自己?(认不出 = 指纹有洞)
- enrich 的 favicon/ASN/SSL 对不对?
- contacts/privacy 在已知放入的内容上抓全没?

再从真实站**随机抽 20–30 个人工打标**,与脚本输出比,算出每个采集器的**准确率 / 漏检率**。这一步能把"审出的问题"变成论文里可写的准确率数字。**当前没有任何准确率基线。**

---

## 修复优先级(按解锁效果排)

1. **重做 `tech_stack` 分类器**(解锁整条分析线):去掉 `xxx2api` catch-all;`/api/status` 解析 JSON 取 `system_name`+`version`;family 级信号(残留 one-api 字符串)降到 medium 且不与 fork 独有信号同权;SPA/blocked/unidentified 拆独立桶;并**真正跑一遍提交输出**。
2. **`enrich` 补证书 SAN + 指纹**(直接拉满归并质量);删 `ssl_org`;favicon 加 content-type 校验。
3. **全局加 `*_status` 字段**(`ok`/`failed`/`not_found`),失败可重试 → 区分失败与缺失。
4. **privacy 接 LLM 编码**(原料已在 `privacy_snapshots/`,不用重爬);**contacts 扩到渲染后 DOM / 图标链接**以救回 Telegram 漏检。
5. **指向自建实例做准确率验证**,产出每个采集器的准确率/漏检率基线。

---

## 附:bug 复现脚本

```python
import sys; sys.path.insert(0, 'scripts')
from tech_stack_fingerprint_probe import classify, FetchResult, domain_from_url as d

# 1. xxx2api catch-all 误判无关文案
classify(d("https://x.com"), [FetchResult("https://x.com/", headers={}, body="we support any2api")])
#   -> xxx2api / medium

# 2. 真 sub2api 站被多标 xxx2api
classify(d("https://s.com"), [FetchResult("https://s.com/", headers={}, body="Sub2API - Subscription to API Conversion Platform")])
#   -> sub2api|xxx2api / high

# 3. new-api fork 残留 one-api → 双标 high
classify(d("https://r.com"), [FetchResult("https://r.com/", headers={"x-new-api-version":"v0.8.1"}, body="New API powered by one-api core")])
#   -> new-api|one-api / high

# 4. SPA 空壳 → unknown
classify(d("https://spa.com"), [FetchResult("https://spa.com/", headers={"server":"nginx"}, body='<div id="root"></div>')])
#   -> unknown / low
```
