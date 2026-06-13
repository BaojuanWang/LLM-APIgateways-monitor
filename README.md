# LLM-APIgateways-monitor

# LLM中转站监测项目 — 快速上手文档

## 项目目标
系统性测量中国LLM中转站（API relay）生态，目标投USENIX Security论文。

## GitHub Repo
`BaojuanWang/LLM-APIgateways-monitor`（私有）

---

## 文件结构
```
llm-relay-monitor/
├── .github/workflows/monitor.yml   ← 定时任务，每4小时自动跑
├── data/
│   ├── manual_sites.csv            ← 手动收集平台（你自己维护）
│   ├── hvoy_latest.csv             ← hvoy最新平台列表（自动生成）
│   ├── hvoy_latest.json            ← 同上，JSON格式
│   └── hvoy_raw/                   ← 每次抓取的历史存档
│       ├── hvoy_2026-06-13.json
│       ├── hvoy_2026-06-13.xlsx    ← 含新增/消失平台对比
│       └── diff_2026-06-13.json   ← 有变化才生成
├── results/
│   ├── monitor_results.csv         ← 所有检测结果（追加写入）
│   └── summary_2026-06-13.xlsx    ← 综合汇总报告（每次自动生成）
└── scripts/
    ├── hvoy_tracker.py             ← Step 1: 抓hvoy数据
    ├── pipeline.py                 ← Step 2: 检测平台存活
    └── summarize.py                ← Step 3: 生成汇总报告
```

---

## 数据来源
| 来源 | 数量 | 文件 |
|------|------|------|
| hvoy.ai榜单 | ~208个（自动抓取） | hvoy_latest.csv |
| 淘宝/小红书手动收集 | 28个 | manual_sites.csv |
| **合计去重** | **~233个** | monitor_results.csv |

### manual_sites.csv 格式
```
source, platform_name, domain, tech_stack, favicon_group, icp_filing, has_privacy_policy, contact_telegram, contact_qq, notes
Taobao, DKAI/大可, codex.dakeai.cc, Nginx, ...
Xiaohongshu, 小鲸Ai开放平台, open.xiaojingai.com, ...
```
**新平台直接追加行即可，下次workflow自动包含。**

---

## 自动流水线
每4小时（UTC整点）自动运行：
1. `hvoy_tracker.py` — 请求 hvoy.ai/en/sites，提取页面内嵌JSON（`__RELAY_SITE_RANKINGS_PAYLOAD__`），保存Excel+JSON+CSV，对比上次输出新增/消失平台
2. `pipeline.py` — 读取hvoy_latest.csv + manual_sites.csv，合并去重，对每个域名依次尝试 https://域名 → https://www.域名 → http://域名，结果追加到monitor_results.csv
3. `summarize.py` — 聚合历史检测数据，生成summary Excel

**如果hvoy抓取失败（403/网络错误）→ workflow失败 → GitHub自动发邮件通知**

---

## 存活状态分类
| 状态 | 含义 | 算法判定 |
|------|------|---------|
| ONLINE | 正常在线 | HTTP 200 |
| CLOUDFLARE_OR_BLOCKED | Cloudflare拦截，实际在线 | CF challenge页面 |
| ONLINE_LOGIN_REQUIRED | 需登录，实际在线 | HTTP 401/403 |
| HTTP_444 | Nginx拒绝，实际在线 | HTTP 444 |
| TIMEOUT | 超时，不确定 | 连接超时 |
| HTTP_ERROR | 连接错误，不确定 | SSL错误/连接重置等 |
| DNS_FAIL | 域名解析失败，大概率已关闭 | DNS解析错误 |
| PARKED_OR_FOR_SALE | 域名停放/出售 | 页面含关键词 |

### 综合判定规则（summarize.py）
- **ALIVE** = 至少一次检测为 ONLINE/CLOUDFLARE/444/LOGIN
- **UNCERTAIN** = 所有检测均为 TIMEOUT 或 HTTP_ERROR
- **DEAD** = 所有检测均为 DNS_FAIL

---

## summary Excel结构
4个sheet：
- **综合汇总** — 所有平台，DEAD排最前，含检测次数/各状态明细/最近URL
- **疑似关闭** — 仅DEAD平台（红色）
- **待确认** — 仅UNCERTAIN平台（黄色）
- **说明** — 统计数字和判定规则

---

## 关键技术细节
- hvoy数据从页面HTML的 `<script id="__RELAY_SITE_RANKINGS_PAYLOAD__">` 提取，一次请求拿全部208个平台
- 检测并发10线程，每个域名随机延迟0.3-1秒
- GitHub Actions IP会被Cloudflare识别为云服务IP → CLOUDFLARE_OR_BLOCKED，属正常现象
- `monitor_results.csv` 只追加，不覆盖，保留完整历史
- summary Excel每次生成新文件（带日期后缀），不覆盖历史

---

## 手动操作
**手动触发一次workflow：**
GitHub repo → Actions → LLM Relay Monitor → Run workflow

**新增手动平台：**
直接编辑 `data/manual_sites.csv`，追加一行

**查看最新结果：**
`results/` 文件夹下载最新的 `summary_*.xlsx`

---

## 待办
- [ ] 验证DNS_FAIL的平台是否真的挂了（openclaudecode.cn、code.b886.top、zaimaai.cn、daidaibird.top等）
- [ ] 数据积累1-2周后分析存活率趋势

