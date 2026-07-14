"""
域名信息enrichment脚本
运行位置: scripts/enrich.py

一次性字段（只查新域名）：
- WHOIS注册时间、注册商
- SSL证书颁发机构、组织名

定期字段（每次都查）：
- IP地址、地理位置、ASN、托管商
- SSL证书过期时间
- HTTP响应头（Server、X-Powered-By、技术栈）
- favicon hash
"""

import csv
import json
import re
import socket
import ssl
import hashlib
import time
import random
from datetime import datetime, timezone
from pathlib import Path

import requests
import dns.resolver

BASE_DIR      = Path(__file__).parent.parent
DATA_DIR      = BASE_DIR / "data"
HVOY_CSV      = DATA_DIR / "hvoy_latest.csv"
MANUAL_CSV    = DATA_DIR / "manual_sites.csv"
MASTER_SITES_CSV = DATA_DIR / "master_sites.csv"   # discovery-layer confirmed list
ENRICHMENT_CSV= DATA_DIR / "enrichment.csv"

TIMEOUT = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

# ── 字段定义 ──────────────────────────────────────────────────
STATIC_FIELDS = [
    "whois_reg_date", "whois_registrar", "whois_expiry_date",
    # registrant identity — the "who operates this" signal. Often redacted
    # (privacy proxy / GDPR) but frequently present for .cn/.com.cn and some
    # budget registrars. registrar (above) is the reseller; these are the org.
    "whois_registrant_org", "whois_registrant_name", "whois_registrant_country",
    "ssl_issuer", "ssl_org", "ssl_san", "ssl_fingerprint", "ssl_not_before",
]
DYNAMIC_FIELDS = [
    "ip", "ip_country", "ip_city", "ip_asn", "ip_hosting",
    "ssl_expiry", "server_header", "powered_by", "tech_stack",
    "favicon_hash", "last_enriched",
]
ALL_FIELDS = ["domain"] + STATIC_FIELDS + DYNAMIC_FIELDS


# ── 工具函数 ──────────────────────────────────────────────────
def extract_domain(url):
    if not url: return None
    url = str(url).strip()
    url = re.sub(r'^https?://', '', url)
    return url.split('/')[0].split('?')[0].lower() or None


def load_platforms():
    domains = {}
    for csv_path, source in [(HVOY_CSV, "hvoy"), (MANUAL_CSV, "manual"),
                             (MASTER_SITES_CSV, "discovery")]:
        if not csv_path.exists():
            continue
        with open(csv_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                d = extract_domain(row.get("domain", ""))
                if d:
                    domains[d] = source
    return domains


def load_existing():
    if not ENRICHMENT_CSV.exists():
        return {}
    with open(ENRICHMENT_CSV, encoding="utf-8-sig") as f:
        return {row["domain"]: row for row in csv.DictReader(f)}


def save_all(records):
    with open(ENRICHMENT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=ALL_FIELDS)
        writer.writeheader()
        writer.writerows(records)


# ── WHOIS ─────────────────────────────────────────────────────
def get_whois(domain):
    keys = ["whois_reg_date", "whois_registrar", "whois_expiry_date",
            "whois_registrant_org", "whois_registrant_name", "whois_registrant_country"]
    result = {k: "" for k in keys}
    try:
        import whois
        w = whois.whois(domain)
        reg = w.creation_date
        exp = w.expiration_date
        if isinstance(reg, list): reg = reg[0]
        if isinstance(exp, list): exp = exp[0]
        result["whois_reg_date"]   = str(reg)[:10] if reg else ""
        result["whois_expiry_date"]= str(exp)[:10] if exp else ""
        result["whois_registrar"]  = str(w.registrar or "")[:80]

        # registrant identity — field names vary by TLD/registry, so try a
        # prioritized list and take the first non-empty. Lists → first item.
        def first(*names):
            for nm in names:
                v = w.get(nm) if hasattr(w, "get") else getattr(w, nm, None)
                if isinstance(v, list):
                    v = next((x for x in v if x), None)
                if v and str(v).strip().lower() not in ("none", "redacted for privacy",
                                                          "redacted", "not disclosed"):
                    return str(v).strip()[:120]
            return ""
        result["whois_registrant_org"]     = first("org", "registrant_org", "registrant_organization")
        result["whois_registrant_name"]    = first("name", "registrant_name")
        result["whois_registrant_country"] = first("country", "registrant_country")
    except Exception:
        pass
    return result


# ── SSL证书 ───────────────────────────────────────────────────
def get_ssl(domain):
    result = {k: "" for k in
              ["ssl_issuer", "ssl_org", "ssl_expiry", "ssl_san", "ssl_fingerprint",
               "ssl_not_before"]}
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=domain) as s:
            s.settimeout(TIMEOUT)
            s.connect((domain, 443))
            cert = s.getpeercert()
            der  = s.getpeercert(binary_form=True)   # DER bytes for fingerprint
        # 颁发机构
        issuer = dict(x[0] for x in cert.get("issuer", []))
        result["ssl_issuer"] = issuer.get("organizationName", "")[:80]
        # 组织名（证书持有人）
        subject = dict(x[0] for x in cert.get("subject", []))
        result["ssl_org"] = subject.get("organizationName", "")[:80]
        # 过期时间
        exp = cert.get("notAfter", "")
        if exp:
            dt = datetime.strptime(exp, "%b %d %H:%M:%S %Y %Z")
            result["ssl_expiry"] = dt.strftime("%Y-%m-%d")
        # 证书首次签发时间（notBefore）≈ 站点上线时间，覆盖率远高于 WHOIS
        nb = cert.get("notBefore", "")
        if nb:
            dt = datetime.strptime(nb, "%b %d %H:%M:%S %Y %Z")
            result["ssl_not_before"] = dt.strftime("%Y-%m-%d")
        # SAN（同一张证书覆盖的所有域名）——运营者归并最硬的强信号
        san = sorted({v for (k, v) in cert.get("subjectAltName", ()) if k == "DNS"})
        result["ssl_san"] = ";".join(san[:20])
        # 证书指纹（SHA-256 of DER）——同指纹≈同一张证书≈同源
        if der:
            result["ssl_fingerprint"] = hashlib.sha256(der).hexdigest()
    except Exception:
        pass
    return result


# ── IP / 地理位置 / ASN ───────────────────────────────────────
def get_ip_info(domain):
    result = {k: "" for k in ["ip", "ip_country", "ip_city", "ip_asn", "ip_hosting"]}
    try:
        ip = socket.gethostbyname(domain)
        result["ip"] = ip
        # 用 ip-api.com 免费接口（无需key，限制45次/分钟）
        resp = requests.get(f"http://ip-api.com/json/{ip}?fields=country,city,as,org",
                            timeout=TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            result["ip_country"] = data.get("country", "")
            result["ip_city"]    = data.get("city", "")
            result["ip_asn"]     = data.get("as", "")[:60]
            result["ip_hosting"] = data.get("org", "")[:60]
    except Exception:
        pass
    return result


# ── HTTP响应头 / 技术栈 ───────────────────────────────────────
def get_http_headers(domain):
    result = {k: "" for k in ["server_header", "powered_by", "tech_stack", "favicon_hash"]}
    try:
        resp = requests.get(f"https://{domain}", headers=HEADERS,
                           timeout=TIMEOUT, allow_redirects=True, verify=False)
        result["server_header"] = resp.headers.get("Server", "")[:60]
        result["powered_by"]    = resp.headers.get("X-Powered-By", "")[:60]

        # 技术栈识别
        tech = []
        h = {k.lower(): v.lower() for k, v in resp.headers.items()}
        text = resp.text[:5000].lower() if resp.text else ""
        if "cloudflare" in h.get("server", "") or "cloudflare" in text: tech.append("Cloudflare")
        if "nginx" in h.get("server", ""): tech.append("Nginx")
        if "apache" in h.get("server", ""): tech.append("Apache")
        if "next.js" in text or "__next" in text: tech.append("Next.js")
        if "react" in text: tech.append("React")
        if "vue" in text: tech.append("Vue")
        if "new-api" in text or "newapi" in text: tech.append("NewAPI")
        if "one-api" in text or "oneapi" in text: tech.append("OneAPI")
        result["tech_stack"] = ", ".join(tech)

        # favicon hash
        favicon_url = f"https://{domain}/favicon.ico"
        fr = requests.get(favicon_url, headers=HEADERS, timeout=TIMEOUT, verify=False)
        if fr.status_code == 200 and fr.content:
            result["favicon_hash"] = hashlib.md5(fr.content).hexdigest()[:12]
    except Exception:
        pass
    return result


# ── 主程序 ────────────────────────────────────────────────────
def main():
    import warnings
    import urllib3
    warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

    print("读取平台列表...")
    platforms = load_platforms()
    print(f"共 {len(platforms)} 个域名")

    print("读取已有enrichment数据...")
    existing = load_existing()
    print(f"已有记录: {len(existing)} 个")

    records = {}
    # 保留已有记录
    for domain, row in existing.items():
        records[domain] = {f: row.get(f, "") for f in ALL_FIELDS}

    total = len(platforms)
    for idx, (domain, source) in enumerate(platforms.items(), 1):
        print(f"\n[{idx}/{total}] {domain}")

        if domain not in records:
            records[domain] = {f: "" for f in ALL_FIELDS}
            records[domain]["domain"] = domain

        rec = records[domain]
        is_new = domain not in existing

        # ── 一次性字段：新域名首次查，或已有记录里该字段为空时回填/重试 ──
        # （旧逻辑首次失败会被永久缓存成空、再不重试；这里改成"缺就补"，
        #   同时让已有 292 行能回填新增的 ssl_san / ssl_fingerprint。）
        # re-query WHOIS if we've never seen the domain, lack a reg date, OR
        # the stored row predates the registrant-identity columns (one-time
        # migration — checked on the RAW existing row, which lacks the key
        # entirely under the old schema).
        need_whois = (is_new or not rec.get("whois_reg_date")
                      or "whois_registrant_org" not in existing.get(domain, {}))
        need_ssl   = is_new or not rec.get("ssl_san") or not rec.get("ssl_not_before")

        if need_whois:
            print(f"  WHOIS...", end=" ", flush=True)
            rec.update(get_whois(domain))
            print(rec.get("whois_reg_date") or "无")

        if need_ssl:
            print(f"  SSL(static)...", end=" ", flush=True)
            ssl_data = get_ssl(domain)
            for k in ("ssl_issuer", "ssl_org", "ssl_expiry", "ssl_san",
                      "ssl_fingerprint", "ssl_not_before"):
                rec[k] = ssl_data[k]
            print(rec.get("ssl_san") or rec.get("ssl_issuer") or "无")

        if not need_whois and not need_ssl:
            print(f"  静态字段已有，跳过")

        # ── 定期字段（每次都查）──
        print(f"  IP/地理位置...", end=" ", flush=True)
        rec.update(get_ip_info(domain))
        print(rec.get("ip_country") or "无")

        print(f"  HTTP响应头/技术栈...", end=" ", flush=True)
        rec.update(get_http_headers(domain))
        print(rec.get("tech_stack") or "无")

        # SSL过期时间每次刷新（未在上面查过 static 时补一次轻量查询）
        if not need_ssl:
            ssl_data = get_ssl(domain)
            rec["ssl_expiry"] = ssl_data["ssl_expiry"]
            # 指纹/SAN 若此前为空也顺手补上
            if not rec.get("ssl_fingerprint") and ssl_data.get("ssl_fingerprint"):
                rec["ssl_san"]         = ssl_data["ssl_san"]
                rec["ssl_fingerprint"] = ssl_data["ssl_fingerprint"]

        rec["last_enriched"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 每10个保存一次，防止中途崩溃丢数据
        if idx % 10 == 0:
            save_all(list(records.values()))
            print(f"  [自动保存 {idx}/{total}]")

        time.sleep(random.uniform(1.0, 2.0))

    save_all(list(records.values()))
    print(f"\n✅ 完成，共 {len(records)} 条记录")
    print(f"   已保存: {ENRICHMENT_CSV}")


if __name__ == "__main__":
    main()
