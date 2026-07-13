#!/usr/bin/env python3
"""Step ② — reverse-IP / co-hosted domains for the exposed source IPs (LOCAL).

A real (non-CDN) IP that also hosts OTHER relay domains is strong evidence of a
shared operator — potentially collapsing sites the internal signals count as
'independent'. This queries each exposed source IP for co-hosted domains,
flags shared-hosting noise, and marks which co-hosted domains are already in
our dataset (known) vs new (candidate vigilantes).

Network required → run locally (sandbox 403s these hosts). Resumable.

Provider: default is HackerTarget's free reverse-IP endpoint (rate-limited,
~a few hundred/day). For heavier use set REVIP_API to a SecurityTrails/ViewDNS
style endpoint returning newline- or JSON-listed domains.

    python3 scripts/reverse_ip.py
    REVIP_API='https://api.viewdns.info/reverseip/?host={ip}&apikey=XXX&output=json' python3 scripts/reverse_ip.py
"""
from __future__ import annotations
import csv
import json
import os
import re
import time
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = os.path.join(BASE, "results", "master", "direct_origin_targets.csv")
SHARED_HOST_MIN = 50          # >= this many co-hosted domains → shared host, low value
UA = "Mozilla/5.0 (compatible; relay-research/1.0)"


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def reverse_ip(ip):
    """Return a list of domains co-hosted on this IP ([] on failure/none)."""
    api = os.environ.get("REVIP_API")
    try:
        if api:
            body = _get(api.format(ip=ip))
            try:
                data = json.loads(body)
                doms = []
                # ViewDNS: {response:{domains:[{name:...}]}}
                resp = data.get("response", data) if isinstance(data, dict) else data
                arr = resp.get("domains", resp) if isinstance(resp, dict) else resp
                for it in (arr or []):
                    doms.append(it.get("name") if isinstance(it, dict) else str(it))
                return [d for d in doms if d]
            except Exception:
                return [l.strip() for l in body.splitlines() if "." in l and " " not in l.strip()]
        # default: HackerTarget free endpoint
        body = _get(f"https://api.hackertarget.com/reverseiplookup/?q={ip}")
        if "API count exceeded" in body or "error" in body.lower():
            return None                  # quota / error → distinguish from "none"
        return [l.strip() for l in body.splitlines() if "." in l and l.strip()]
    except Exception:
        return None


def main():
    rows = list(csv.DictReader(open(TARGETS, encoding="utf-8-sig")))
    cols = list(rows[0].keys())
    known = {r["domain"] for r in rows}     # our dataset (for known-vs-new)

    # one lookup per unique IP; apply the result to every row on that IP
    ips = {}
    for r in rows:
        if r.get("source_ip") and not r.get("co_hosted_domains"):
            ips.setdefault(r["source_ip"], []).append(r)
    print(f"待反查 IP:{len(ips)}(已填的跳过)")

    for i, (ip, group) in enumerate(ips.items(), 1):
        doms = reverse_ip(ip)
        if doms is None:
            print(f"[{i}/{len(ips)}] {ip:16s} 查询失败/超配额,停在这里(下次续跑)")
            break
        others = sorted(set(d.lower() for d in doms) - {r["domain"] for r in group})
        shared = "Y" if len(doms) >= SHARED_HOST_MIN else ""
        new_ones = [d for d in others if d not in known]
        tag = "共享主机" if shared else (f"{len(new_ones)} 个疑似马甲" if new_ones else "无同驻")
        for r in group:
            r["co_hosted_domains"] = "" if shared else ";".join(others[:30])
            r["ip_is_shared_host"] = shared
        print(f"[{i}/{len(ips)}] {ip:16s} 同驻 {len(doms):3d} 域名 → {tag}")
        if i % 10 == 0:
            _save(rows, cols)
        time.sleep(2.5)                     # HackerTarget is strict; be gentle
    _save(rows, cols)

    with_co = sum(1 for r in rows if r.get("co_hosted_domains"))
    print(f"\n完成一批。{with_co} 个站有非共享同驻域名。回写 {TARGETS}")
    print("下一步:同驻域名里有中转站特征的,就是候选马甲 → 人工确认几个高价值的。")


def _save(rows, cols):
    with open(TARGETS, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    main()
