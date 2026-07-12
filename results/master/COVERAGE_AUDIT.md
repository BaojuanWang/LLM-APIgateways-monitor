# 特征覆盖 / 缺失审计  (N=1089 站)

每个特征拿到多少、unknown 占多少、缺失原因、拿不到怎么处理。

## 1. 逐字段可获取率

| 特征 | 已获取 | 覆盖率 | 缺失 | 缺失类别 |
|---|---:|---:|---:|---|
| 发现层框架 | 932 | 86% | 157 | collectible |
| 证书 not_before | 1037 | 95% | 52 | structural |
| 证书指纹 | 1037 | 95% | 52 | structural |
| 证书公司名(Org) | 6 | 1% | 1083 | structural |
| WHOIS 注册日 | 1015 | 93% | 74 | redactable |
| WHOIS 注册商 | 1015 | 93% | 74 | redactable |
| WHOIS 注册人机构 | 0 | 0% | 1089 | redactable |
| 源站 IP | 1073 | 99% | 16 | structural |
| 托管 ASN | 1065 | 98% | 24 | structural |
| IP 国家 | 1072 | 98% | 17 | structural |
| favicon 指纹 | 900 | 83% | 189 | transient |
| ICP 备案主体 | 25 | 2% | 1064 | collectible |
| 隐私政策 | 284 | 26% | 805 | collectible |
| 隐私·适用法律 | 131 | 12% | 958 | collectible |
| 隐私·第三方共享 | 131 | 12% | 958 | collectible |
| 支付方式 | 155 | 14% | 934 | collectible |
| Telegram 触达 | 14 | 1% | 1075 | collectible |
| 第三方榜单评分 | 246 | 23% | 843 | collectible |
| 存活状态 | 292 | 27% | 797 | transient |

## 2. 面板分类分布(unknown 显式,双分母)

每类给两个占比:占**全部站**、占**有数据的站**(剔除 unknown 后)。


### stack_family  (共 1089;有数据 868;unknown 221)

| 值 | 站数 | 占全部 | 占有数据 | 类型 |
|---|---:|---:|---:|---|
| one-api-family | 838 | 77% | 97% |  |
| unlabeled | 144 | 13% | — | ⚠unknown |
| openai-compatible-unknown | 73 | 7% | — | ⚠unknown |
| sub2api | 30 | 3% | 3% |  |
| confirmed-unknown | 4 | 0% | — | ⚠unknown |

### site_role  (共 1089;有数据 868;unknown 221)

| 值 | 站数 | 占全部 | 占有数据 | 类型 |
|---|---:|---:|---:|---|
| relay | 838 | 77% | 97% |  |
| unidentified | 221 | 20% | — | ⚠unknown |
| conversion_layer | 30 | 3% | 3% |  |

### hosting_type  (共 1089;有数据 1073;unknown 16)

| 值 | 站数 | 占全部 | 占有数据 | 类型 |
|---|---:|---:|---:|---|
| cdn_fronted | 760 | 70% | 71% |  |
| direct_origin | 313 | 29% | 29% |  |
| unknown | 16 | 1% | — | ⚠unknown |

### maturity_tier  (共 1089;有数据 1088;unknown 1)

| 值 | 站数 | 占全部 | 占有数据 | 类型 |
|---|---:|---:|---:|---|
| new_2026 | 663 | 61% | 61% |  |
| established | 233 | 21% | 21% |  |
| growing_2025 | 192 | 18% | 18% |  |
| unknown | 1 | 0% | — | ⚠unknown |

## 3. 拿不到怎么办(按缺失类别的处置策略)

| 类别 | 处置策略 | 涉及字段 |
|---|---|---|
| **structural** | 结构上不可得(如 CDN 后真实源站 IP、免费证书无公司名)。**缺失本身是信号**(=刻意不透明);报为显式 unknown 桶,永不插补。 | 证书 not_before, 证书指纹, 证书公司名(Org), 源站 IP, 托管 ASN, IP 国家 |
| **collectible** | 尚未采集(采集器没覆盖到)。跑对应采集器补齐(deep_dig.sh);在补齐前,统计只在'已采子集'上做并注明分母。 | 发现层框架, ICP 备案主体, 隐私政策, 隐私·适用法律, 隐私·第三方共享, 支付方式, Telegram 触达, 第三方榜单评分 |
| **redactable** | 可能被隐私代理/GDPR 脱敏。报'脱敏率';用备用信号回退(注册商→ICP备案→证书Org→关于页公司名)。 | WHOIS 注册日, WHOIS 注册商, WHOIS 注册人机构 |
| **transient** | 探测时点站点失活/超时。重试;标为 churn,不与'永久缺失'混淆。 | favicon 指纹, 存活状态 |
| **derived** | 由其他字段派生,缺失=上游字段缺失。跟随上游。 |  |

**总原则**:①永不插补——缺失作为显式 unknown 桶参与统计;②每个统计量注明分母(全部 vs 已采子集);③结构性缺失(CDN/免费证书)**本身当信号**(=刻意不透明);④可采缺失跑采集器补,脱敏缺失走备用信号回退链。
