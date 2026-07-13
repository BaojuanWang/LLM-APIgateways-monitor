# §4.1 核心结果 · 发现方法偏差与结构集中度

**这是本研究最硬的一块论证。写作时直接用。**

## 一句话

用第二个独立、框架无关的发现方法(FOFA 网络空间测绘)测量了第一个方法(GitHub 代码搜索)的偏差,并证明核心结论"结构集中"在两个方法下都成立。

## 数据(confirmed 站,按发现来源分组,framework 字段)

> **口径注**:此处 GitHub **764 = 发现层原始条目数(去重前)**;按 eTLD+1 归并去重后为 **652 个唯一站**
> (112 差为同站多主机名折叠)。FOFA 280 本就唯一。**one-api 占比在两口径下逐位相同**
> (764→96% ≡ 652→96%;FOFA 71%/尾 24% 不变),故本论证与单位无关。分析层其余表(N=1089)用去重口径 652。

| 指标 | GitHub codesearch(764 原始/652 去重,框架指纹→有偏) | FOFA G1(280,框架无关→无偏) | 差 |
|---|---|---|---|
| **one-api 家族** | **96%** (736) | **71%** (198) | 25 pt |
| **框架未识别的异构尾**(openai 兼容 / unknown) | **2%** (14) | **24%** (66) | 12× |
| sub2api(货源存疑,非"转换层") | 1.8% (14) | 5.7% (16) | — |

## 一张表同时成立三件事(通常互相矛盾)

1. **GitHub 有偏** —— 靠框架指纹发现,自然 96% 是 one-api;差 25 个点量化了偏差幅度。
2. **但结构集中是真的,不是 artifact** —— 即使框架无关的 FOFA,one-api 家族仍占 71%,依然压倒性主导。
3. **FOFA 补回了 GitHub 结构上找不到的异构尾** —— 24% vs 2%(12 倍),GitHub 代码搜索系统性遗漏这一类。

## 论文表述(保守下界版 —— 直接引用)

> one-api 家族在框架无关发现下占 71%,构成集中度的**保守下界**;基于代码搜索的发现高估集中度(96% vs 71%),并系统性遗漏约 24% 的异构 / 无法指纹化尾部。该尾部的一部分可能是未被指纹识别的白标 one-api,因此真实集中度可能更高——无论如何,结论都落在"集中"与"代码搜索有偏"之间。

## 已实测:拆解那 24% 尾部(deep-probe,2026-07-11)

对 FOFA 的 66 个 `openai_compatible_unknown` 尾站跑深度技术栈探针
(`scripts/probe_tail.sh` → `analyze_tail.py`),逐站裁定,**把上面的 caveat 1
从"可能"变成了数据**:

| 尾部裁定 | 数量 | 占尾部 | 说明 |
|---|---:|---:|---|
| **hidden_one_api** | 5 | 8% | FOFA 漏检的改壳 one-api;响应头 `x-oneapi-request-id`/`x-new-api-version`,high 置信 |
| other_known | 0 | 0% | 无其他成型框架 |
| **genuine_unknown** | 59 | 89% | 真异构/自研(50 有真内容 + 9 SPA 空壳) |
| dead | 2 | 3% | 探不通 |

**两个结论(都对论证有利,且现在方向明确):**

1. **下界很紧,71% → 73%**。加回 5 个漏检 one-api、剔除 2 个死站后份额只升 2pt。
   → 集中度**并未被大幅低估**,71% 是个**紧的保守下界**,不是虚的。
2. **尾巴主体(89%)是真异构**,不是伪装的 one-api。59 站 = 全 FOFA 的 21%,
   可达且无任何 one-api 信号。→ 之前担心的"尾巴其实都是改壳 one-api"被证伪
   (只占 8%)。**"代码搜索有偏"这条胳膊反而更硬**:codesearch 遗漏的是
   一个真实存在的异构长尾,对它**结构性失明**。

> **更新后的一句话**:one-api 集中真实且下界紧(FOFA 框架无关下 71%,深度复探
> 收紧至 73%);GitHub codesearch 高估集中度(96%),并**结构性遗漏 ~21% 的真异构
> 长尾**(实测该尾仅 8% 是漏检 one-api,其余为自研/异构)。

5 个 hidden one-api:`2dapi.online` · `llmroute.club` · `maiqilingai.com` ·
`silkroadai.io` · `tokencall.cn`。逐站明细见 `results/tail/tail_verdict.csv`。

## 残留 caveat(必须保留)

**caveat 1(现已量化,但保留残留模糊)**:59 个真异构尾里有 **9 个 SPA 空壳**
(Vue 首屏无内容、`/api/status` 探不到),理论上其中个别可能仍是藏得深的
one-api。故 73% 是 one-api 的**下界**、21% 是异构尾的**上界**。即便这 9 个全算
one-api(最坏情况),异构尾仍 ≥18%、one-api ≤76%——**区间很窄,方向不变**。

**caveat 2(抽样)**:FOFA G1 只是**一个 FOFA 查询**,存在单查询抽样局限。需要 Quake 交叉验证 + 其他 FOFA 查询组(G3/G5)确认这个 71% 不是偶然 → 写进 limitations。

## 口径注意(别在论文里用混)

- **面板 78%** = 809 站合并后的 `stack_family`(含监测站 + Vue 空壳未标)。**不要用于偏差论证。**
- **偏差论证只用 96% vs 71%** = 按发现来源分组的 `framework` 字段(confirmed only,同口径可比)。

## 完整论证链(§4.1 叙事骨架)

1. GitHub 代码搜索发现 764 站,框架指纹显示 96% one-api。
2. 担心这是方法 artifact(循环论证:靠技术栈找 → 找到的都有技术栈)。
3. 引入 FOFA(框架无关的网络空间测绘)独立发现 280 个新站。
4. 对比:FOFA 下 one-api 仍 71%(证明集中是真的)+ 24% 异构尾(证明 GitHub 漏检)。
5. 结论:结构集中真实,但代码搜索高估集中度、系统性漏掉异构尾。

## 后续动作(让结论更精确,非必需)

- **拆那 24% 尾**:对 FOFA 的 openai-未识别站跑 `tech_stack_fingerprint_probe.py`,看多少是魔改 one-api、多少是真自研 → 收紧下界。
- **Quake 交叉验证**:第三个独立发现方法,确认 71% 稳健。
- **证书归并**:full_refresh 后看 FOFA 280 落进已知簇 vs 新簇 → 运营者层的"新 vs 马甲"。

## 复算

```bash
python3 - <<'PY'
import csv, collections
rows=list(csv.DictReader(open("data/master_sites.csv",encoding="utf-8-sig")))
def bucket(fw):
    fw=(fw or "").lower()
    if any(k in fw for k in ["new-api","one-api","oneapi","newapi","voapi","veloera","one-hub","done-hub"]): return "one-api家族"
    if "sub2api" in fw: return "sub2api"
    if "openai_compatible" in fw or "unknown" in fw or not fw: return "异构尾"
    return fw
for name,grp in [("GitHub",[r for r in rows if r.get("origin")!="fofa_g1"]),
                 ("FOFA",[r for r in rows if r.get("origin")=="fofa_g1"])]:
    n=len(grp); c=collections.Counter(bucket(r.get("framework","")) for r in grp)
    print(name, n, {k:f"{100*v/n:.0f}%" for k,v in c.most_common()})
PY
```
_数据快照 2026-07-11;数值随发现层扩充刷新,论证结构不变。_
