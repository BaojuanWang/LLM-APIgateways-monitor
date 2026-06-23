# LLM-APIgateways-monitor

# LLM中转站监测项目 - 快速上手文档

## 项目目标
系统性测量中国 LLM 中转站（API relay）生态：站点发现、存活状态、阻断情况、截图证据、基础技术/合规线索，以及部分模型资源/价格线索。

## GitHub Repo
`BaojuanWang/LLM-APIgateways-monitor`（私有）

---

## 文件结构
```
llm-relay-monitor/
├── .github/workflows/
│   ├── monitor.yml                 ← 定时检测站点存活，不再自动抓 hvoy
│   ├── screenshot.yml              ← 定时/手动截图
│   └── enrich.yml                  ← 域名补充信息
├── data/
│   ├── manual_sites.csv            ← 手动收集平台（你自己维护）
│   ├── hvoy_latest.csv             ← 最近一次 hvoy 站点总表（手动源更新）
│   ├── hvoy_latest.json            ← 同上，JSON 格式
│   ├── hvoy_raw/                   ← hvoy 历史存档和 diff
│   ├── hvoy_resources/             ← 手动导入的 hvoy model/resource 汇总
│   │   └── hvoy_resources_site_summary_2026-06-23.csv
│   ├── manual_screenshots/         ← 手动截图证据
│   └── screenshots/                ← 自动截图
├── results/
│   ├── monitor_results.csv         ← 所有检测结果（追加写入）
│   ├── summary_*.xlsx              ← 综合汇总报告
│   ├── latest_status.svg           ← 最新状态图（覆盖）
│   └── daily_status_*.svg          ← 每日状态图归档
└── scripts/
    ├── pipeline.py                 ← 检测平台存活
    ├── summarize.py                ← 生成汇总报告和状态图
    ├── hvoy_tracker.py             ← 旧 hvoy 抓取脚本，保留但 monitor 不再调用
    └── model_price_probe.py        ← 模型价格/资源探测实验脚本
```

---

## 数据来源
| 来源 | 文件 | 更新方式 |
|------|------|----------|
| hvoy.ai 站点榜单 | `data/hvoy_latest.csv`, `data/hvoy_latest.json` | 现在以手动页面源更新为主 |
| hvoy.ai model/resource 榜单 | `data/hvoy_resources/` | 手动提供页面 HTML 后导入 |
| 淘宝/小红书/外部线索 | `data/manual_sites.csv` | 手动追加 |
| 自动存活检测 | `results/monitor_results.csv` | GitHub Actions 定时追加 |
| 自动/手动截图 | `data/screenshots/`, `data/manual_screenshots/` | 自动截图加人工补充 |

### 2026-06-23 手动更新记录
- 新增外部线索：`www.micuapi.ai`，平台名 `米醋API`。
- 已有相近记录：`openclaudecode.cn`，平台名 `米醋AI`，标记为 `hvoy_removed`。
- 因此 `米醋API` 先作为新线索加入，但备注可能与 `openclaudecode.cn / 米醋AI` 有关联，后续再核实。
- 新增 `data/hvoy_resources/hvoy_resources_site_summary_2026-06-23.csv`：来自手动提供的 Hvoy 首页 HTML 中 `__LEADERBOARD_PAYLOAD__`，展开后为 345 条 model-site 记录，汇总为 71 个唯一站点。

### manual_sites.csv 格式
```
source, platform_name, domain, tech_stack, favicon_group, icp_filing, has_privacy_policy, contact_telegram, contact_qq, notes
Taobao, DKAI/大可, codex.dakeai.cc, Nginx, ...
manual, 米醋API, www.micuapi.ai, ..., 2026-06-23 手动加入...
```
新平台直接追加行即可，下次 workflow 自动包含。

---

## 自动流水线
当前 `LLM Relay Monitor` 定时运行：
1. `pipeline.py` 读取 `hvoy_latest.csv` + `manual_sites.csv`，合并去重，对每个域名尝试访问并记录状态。
2. `summarize.py` 聚合历史检测数据，生成 summary Excel 和状态 SVG。
3. GitHub Actions 将 `data/` 和 `results/` 的变化 commit 回仓库。

注意：因为 hvoy.ai 已经对 GitHub Actions 请求返回 403，`monitor.yml` 已经移除自动抓取 hvoy 的步骤。后续 hvoy 站点/资源数据通过手动打开页面、复制页面源，再导入仓库。

---

## 手动导入 hvoy 数据
### 站点总表
如果页面源里有：
```
<script id="__RELAY_SITE_RANKINGS_PAYLOAD__" type="application/json">...</script>
```
可以更新 `data/hvoy_latest.csv/json`，并按日期归档到 `data/hvoy_raw/`。

### 模型资源/价格榜
如果页面源里有：
```
<script id="__LEADERBOARD_PAYLOAD__" type="application/json">...</script>
```
它不是完整站点总表，而是按模型/渠道的 leaderboard。当前做法是导出站点级汇总到：
```
data/hvoy_resources/hvoy_resources_site_summary_YYYY-MM-DD.csv
```
该表每个站点一行，记录覆盖的模型 tab、模型 key、渠道数、价格区间、平均在线率、平均通过率、平均延迟和示例 URL。

---

## 存活状态分类
| 状态 | 含义 | 算法判定 |
|------|------|---------|
| ONLINE | 正常在线 | HTTP 200 |
| CLOUDFLARE_OR_BLOCKED | Cloudflare/人机验证拦截，但站点大概率在线 | CF challenge 页面 |
| ONLINE_LOGIN_REQUIRED | 需登录，实际在线 | HTTP 401/403 或登录页 |
| HTTP_444 | Nginx 拒绝，实际在线 | HTTP 444 |
| TIMEOUT | 超时，不确定 | 连接超时 |
| HTTP_ERROR | 连接错误，不确定 | SSL 错误/连接重置等 |
| DNS_FAIL | 域名解析失败，大概率已关闭 | DNS 解析错误 |
| PARKED_OR_FOR_SALE | 域名停放/出售 | 页面含关键词 |
| SERVICE_STOPPED | 人工确认服务停止维护 | 例如 `api.uglycat.cc` 公告停止维护 |

### 综合判定规则（summarize.py）
- **ALIVE** = 至少一次检测为 ONLINE/CLOUDFLARE/444/LOGIN
- **UNCERTAIN** = 所有检测均为 TIMEOUT 或 HTTP_ERROR
- **DEAD** = 所有检测均为 DNS_FAIL、PARKED、或人工标记 SERVICE_STOPPED

---

## 截图规则
- GitHub Actions 对 Cloudflare/人机验证站点经常只能截到阻断页，不代表真实站点 UI。
- 已人工确认过的 Cloudflare 站点可保留为存活/被拦截状态，不必每轮都要求手动截图。
- 手动截图建议放在：
```
data/manual_screenshots/YYYY-MM-DD/
```
命名建议：
```
{domain_with_underscores}_YYYY-MM-DD_manual.png
{domain_with_underscores}_YYYY-MM-DD_manual_top.png
{domain_with_underscores}_YYYY-MM-DD_manual_bottom.png
```

---

## 查看最新结果
- 最新汇总：`results/summary_*.xlsx`
- 最新状态图：`results/latest_status.svg`
- 每日状态图归档：`results/daily_status_*.svg`
- Hvoy 资源汇总：`data/hvoy_resources/`

---

## 待办
- [ ] 持续核实外部线索和 hvoy 之外的新站点。
- [ ] 区分“同团队换域名/改名”和真正的新平台。
- [ ] 数据积累后分析存活率、Cloudflare 阻断率、资源/价格覆盖差异。
