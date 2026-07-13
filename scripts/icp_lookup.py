#!/usr/bin/env python3
"""Step ① — ICP filing lookup for the .cn direct-origin sites (LOCAL run).

Chinese sites are legally required to file an ICP record whose subject is a
REAL legal/individual entity name — the hardest 'who is behind this' evidence.
This queries the ICP subject for every .cn* domain in the attribution target
list and writes the entity name / number / type back into the CSV.

Network required → run locally, not in the sandbox (proxy 403s these hosts).
ICP endpoints are rate-limited and anti-bot; this stays polite (slow, one at a
time) and is resumable (skips rows already filled).

Provider: set ICP_API to a JSON endpoint that takes a domain and returns the
subject, e.g. a chinaz/aizhan/west key'd API. Response parsing is defensive
(tries common field names). Without ICP_API it falls back to a best-effort
public HTML lookup, which may break when the provider changes its markup —
if so, plug in a proper API via ICP_API.

    python3 scripts/icp_lookup.py
    ICP_API='https://your.api/icp?domain={domain}&key=XXX' python3 scripts/icp_lookup.py
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
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

ENTITY_KEYS = ("unit", "unitName", "companyName", "subject", "sponsor",
               "owner", "entity", "mainName", "name", "主办单位名称")
NUMBER_KEYS = ("icp", "mainLicence", "license", "serviceLicence", "recordNumber", "备案号")
TYPE_KEYS   = ("natureName", "companyType", "unitNature", "type", "主办单位性质")


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def _pick(d, keys):
    for k in keys:
        for kk in (k, k.lower(), k.upper()):
            if isinstance(d, dict) and d.get(kk):
                return str(d[kk]).strip()
    return ""


def query_icp(domain):
    """Return (entity, number, type). Empty entity = not filed / lookup failed."""
    api = os.environ.get("ICP_API")
    try:
        if api:
            body = _get(api.format(domain=domain))
            try:
                data = json.loads(body)
            except Exception:
                data = {}
            # unwrap common envelopes {code,data:{...}} or {result:{...}}
            for wrap in ("data", "result", "Result", "list", "records"):
                if isinstance(data, dict) and isinstance(data.get(wrap), (dict, list)):
                    data = data[wrap]
                    break
            if isinstance(data, list):
                data = data[0] if data else {}
            return _pick(data, ENTITY_KEYS), _pick(data, NUMBER_KEYS), _pick(data, TYPE_KEYS)
        # fallback: best-effort public HTML (fragile; prefer ICP_API)
        html = _get(f"https://icp.chinaz.com/{domain}")
        ent = re.search(r'主办单位名称[^>]*>\s*([^<\n]{2,40})', html)
        num = re.search(r'(京|沪|粤|浙|苏|鲁|川|渝|冀|豫|鄂|湘|皖|闽|赣|晋|陕|甘|云|贵|辽|吉|黑|蒙|桂|琼|新|宁|青|藏|津)ICP备\d+号(?:-\d+)?', html)
        typ = re.search(r'(企业|个人|事业单位|政府机关|社会团体)', html)
        return (ent.group(1).strip() if ent else "",
                num.group(0) if num else "",
                typ.group(1) if typ else "")
    except Exception as e:
        return "", "", f"ERR:{type(e).__name__}"


def main():
    rows = list(csv.DictReader(open(TARGETS, encoding="utf-8-sig")))
    cols = list(rows[0].keys())
    todo = [r for r in rows if r.get("is_cn") == "Y" and not r.get("icp_entity_name")]
    print(f"待查 ICP 的 .cn 站:{len(todo)}(已填的跳过)")
    for i, r in enumerate(todo, 1):
        ent, num, typ = query_icp(r["domain"])
        r["icp_entity_name"] = ent
        r["icp_number"] = num
        if typ and not typ.startswith("ERR:"):
            r["icp_number"] = (num + f" ({typ})").strip()
        print(f"[{i}/{len(todo)}] {r['domain']:24s} → {ent or '(未备案/查不到)'}  {num}")
        if i % 10 == 0:
            _save(rows, cols)
        time.sleep(2.0)                      # be polite / avoid rate-limit
    _save(rows, cols)

    got = sum(1 for r in rows if r.get("is_cn") == "Y" and r.get("icp_entity_name"))
    cn = sum(1 for r in rows if r.get("is_cn") == "Y")
    print(f"\n完成:{got}/{cn} 个 .cn 站查到备案主体名。回写 {TARGETS}")


def _save(rows, cols):
    with open(TARGETS, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    main()
