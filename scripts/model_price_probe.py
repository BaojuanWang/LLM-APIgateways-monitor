"""
Probe model/pricing pages for LLM relay sites.

Reads the latest round from results/monitor_results.csv and writes a best-effort
price snapshot plus a one-row-per-site summary under results/.
"""

import csv
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

BASE_DIR = Path(__file__).parent.parent
RESULTS_CSV = BASE_DIR / "results" / "monitor_results.csv"
OUTPUT_CSV = BASE_DIR / "results" / "model_prices.csv"
SUMMARY_CSV = BASE_DIR / "results" / "model_prices_summary.csv"

TIMEOUT = int(os.getenv("MODEL_PRICE_TIMEOUT", "20"))
MAX_WORKERS = int(os.getenv("MODEL_PRICE_MAX_WORKERS", "6"))
MAX_SITES = int(os.getenv("MODEL_PRICE_MAX_SITES", "0"))
MAX_ROWS_PER_SITE = int(os.getenv("MODEL_PRICE_MAX_ROWS_PER_SITE", "200"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

ALIVE_STATUSES = {
    "ONLINE",
    "REDIRECTED",
    "ONLINE_LOGIN_REQUIRED",
    "ALIVE_BLOCKED",
    "HTTP_200",
    "HTTP_404",
    "HTTP_444",
}

BLOCKED_STATUSES = {"CLOUDFLARE_OR_BLOCKED"}
STOPPED_STATUSES = {"SERVICE_STOPPED"}

MODEL_PAGE_PATHS = [
    "",
    "/pricing",
    "/price",
    "/models",
    "/model",
    "/model-square",
    "/model_square",
    "/modelsquare",
    "/market",
    "/model-market",
    "/model_market",
    "/console/model",
    "/console/models",
    "/dashboard/models",
    "/api/models",
    "/api/model",
    "/api/pricing",
    "/api/price",
    "/api/v1/models",
    "/api/v1/pricing",
    "/api/model/list",
    "/api/models/list",
    "/api/channel/models",
]

OUTPUT_FIELDS = [
    "checked_at",
    "domain",
    "platform_name",
    "monitor_status",
    "source_url",
    "matched_url",
    "access_status",
    "http_status",
    "raw_model_name",
    "model_name",
    "model_tags",
    "provider",
    "model_type",
    "billing_type",
    "input_price",
    "output_price",
    "model_price",
    "price_unit",
    "currency",
    "raw_price_text",
    "confidence",
    "quality_flag",
    "note",
]

SUMMARY_FIELDS = [
    "checked_at",
    "monitor_checked_at",
    "domain",
    "platform_name",
    "monitor_status",
    "access_status",
    "model_rows",
    "usable_price_rows",
    "quality_flags",
    "matched_url",
    "http_status",
    "note",
]

BILLING_TAGS = {
    "按次": "按次",
    "按量": "按量",
    "按token": "按量",
    "token": "按量",
}

QUOTA_TYPE_LABELS = {
    "0": "按量 (quota_type=0)",
    "1": "按次 (quota_type=1)",
}


def origin_from_url(url, domain):
    if url:
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return f"https://{domain}"


def load_latest_round():
    if not RESULTS_CSV.exists():
        raise FileNotFoundError(f"Missing {RESULTS_CSV}")

    latest_ts = ""
    with open(RESULTS_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ts = row.get("timestamp", "")
            if ts > latest_ts:
                latest_ts = ts

    if not latest_ts:
        return [], ""

    latest_dt = datetime.fromisoformat(latest_ts.replace("Z", "+00:00"))
    sites = {}
    with open(RESULTS_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ts = row.get("timestamp", "")
            if not ts:
                continue
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if abs((latest_dt - dt).total_seconds()) > 300:
                continue

            domain = row.get("domain", "").strip()
            if not domain:
                continue
            sites[domain] = {
                "domain": domain,
                "platform_name": row.get("platform_name", ""),
                "online_status": row.get("online_status", ""),
                "final_url": row.get("final_url", ""),
            }

    rows = list(sites.values())
    rows.sort(key=lambda x: x["domain"])
    if MAX_SITES > 0:
        rows = rows[:MAX_SITES]
    return rows, latest_ts


def candidate_urls(site):
    domain = site["domain"]
    origin = origin_from_url(site.get("final_url", ""), domain)
    urls = []
    if site.get("final_url"):
        urls.append(site["final_url"])
    for path in MODEL_PAGE_PATHS:
        urls.append(urljoin(origin + "/", path.lstrip("/")))
    seen = set()
    deduped = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def base_row(site, checked_at, matched_url="", access_status="", http_status="", note=""):
    return {
        "checked_at": checked_at,
        "domain": site["domain"],
        "platform_name": site.get("platform_name", ""),
        "monitor_status": site.get("online_status", ""),
        "source_url": site.get("final_url", "") or f"https://{site['domain']}",
        "matched_url": matched_url,
        "access_status": access_status,
        "http_status": http_status,
        "raw_model_name": "",
        "model_name": "",
        "model_tags": "",
        "provider": "",
        "model_type": "",
        "billing_type": "",
        "input_price": "",
        "output_price": "",
        "model_price": "",
        "price_unit": "",
        "currency": "",
        "raw_price_text": "",
        "confidence": "",
        "quality_flag": "",
        "note": note,
    }


def is_cloudflare(text):
    lower = text[:5000].lower()
    return "cloudflare" in lower and (
        "just a moment" in lower
        or "checking your browser" in lower
        or "cf-chl" in lower
    )


def is_login_required(text, status_code):
    lower = text[:5000].lower()
    if status_code in (401, 403) and not is_cloudflare(text):
        return True
    markers = [
        "sign in required",
        "please sign in",
        "login required",
        "请登录",
        "登录后",
        "需要登录",
        "未登录",
    ]
    return any(marker in lower for marker in markers)


def is_api_error_response(text):
    lower = text[:5000].lower()
    markers = [
        "invalid_request_error",
        "invalid url (get /api",
        "invalid url (get /v1",
        "you may need [get /v1/models]",
        "unsupported endpoint",
    ]
    return any(marker in lower for marker in markers)


def has_price_signal(text):
    lower = text.lower()
    return bool(
        re.search(r"(?:¥|￥|\$)\s*\d", text)
        or re.search(r"\d+(?:\.\d+)?\s*/\s*(?:m|1m|million|token|tokens|次)", lower)
        or any(word in lower for word in ["input price", "output price", "pricing", "price"])
        or any(word in text for word in ["输入价格", "输出价格", "模型价格", "补全价格", "计费"])
    )


def has_model_signal(text):
    lower = text.lower()
    return any(
        marker in lower
        for marker in [
            "gpt",
            "claude",
            "gemini",
            "deepseek",
            "qwen",
            "glm",
            "grok",
            "llama",
            "model",
        ]
    ) or any(marker in text for marker in ["模型", "供应商"])


def has_numeric_price(text):
    return bool(
        re.search(r"(?:¥|￥|\$)\s*\d+(?:\.\d+)?", text)
        or re.search(
            r"(?:输入|输出|补全|模型价格|计费|input|output|prompt|completion|price)"
            r"[^\d¥￥$]{0,40}[¥￥$]?\s*\d+(?:\.\d+)?",
            text,
            re.IGNORECASE,
        )
    )


def is_noise_text_block(text):
    lower = text[:1000].lower()
    noisy_markers = [
        "<!doctype",
        "<html",
        "<head",
        "<meta",
        "<title",
        "<script",
        "<link",
        "application/ld+json",
        "schema.org",
        "open graph",
        "twitter:",
        "invalid_request_error",
        "invalid url",
        "db-authoritative price refresh",
        "model_pricing",
        "overwrites them",
        "const fallback",
    ]
    return lower.lstrip().startswith(("//", "/*", "const ", "let ", "var ", "function ")) or any(
        marker in lower for marker in noisy_markers
    )


def clean_text(value, limit=300):
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:limit]


def first_value(item, keys):
    lowered = {str(k).lower(): v for k, v in item.items()}
    for key in keys:
        if key.lower() in lowered and lowered[key.lower()] not in (None, ""):
            return clean_text(lowered[key.lower()])
    return ""


def value_by_key_contains(item, include_words, exclude_words=()):
    for key, value in item.items():
        lower_key = str(key).lower()
        if all(word in lower_key for word in include_words) and not any(
            word in lower_key for word in exclude_words
        ):
            if value not in (None, ""):
                return clean_text(value)
    return ""


def append_note(note, addition):
    if not addition:
        return note
    return f"{note}；{addition}" if note else addition


def normalize_model_name(raw_name):
    name = clean_text(raw_name, 200)
    tags = []
    while True:
        match = re.match(r"^\s*\[([^\]]{1,40})\]\s*", name)
        if not match:
            break
        tags.append(clean_text(match.group(1), 40))
        name = name[match.end() :].strip()
    return (name or clean_text(raw_name, 200)), tags


def billing_type_from(raw_billing, tags):
    for tag in tags:
        normalized = tag.lower().replace(" ", "")
        if normalized in BILLING_TAGS:
            return BILLING_TAGS[normalized]
    raw = clean_text(raw_billing, 80)
    return QUOTA_TYPE_LABELS.get(raw, raw)


def generic_price_value(item):
    preferred_keys = ["model_price", "modelprice", "unit_price", "unitprice", "price"]
    lowered = {str(key).lower(): value for key, value in item.items()}
    for key in preferred_keys:
        value = lowered.get(key)
        if value not in (None, ""):
            return clean_text(value)
    for key, value in item.items():
        lower_key = str(key).lower()
        if "price" not in lower_key:
            continue
        if any(word in lower_key for word in ["input", "output", "prompt", "completion"]):
            continue
        if value not in (None, ""):
            return clean_text(value)
    return ""


def is_zero_price(value):
    if value in (None, ""):
        return False
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return bool(match and float(match.group()) == 0)


def quality_flags_for_price_row(row):
    flags = []
    if row["model_price"] and not row["input_price"] and not row["output_price"]:
        flags.append("GENERIC_PRICE_ONLY")
    if not any(row[field] for field in ["input_price", "output_price", "model_price"]):
        flags.append("MISSING_PRICE")
    if any(is_zero_price(row[field]) for field in ["input_price", "output_price", "model_price"]):
        flags.append("ZERO_PRICE_CHECK")
    if row["model_tags"]:
        flags.append("MODEL_TAGS_NORMALIZED")
    return "|".join(flags) or "OK"


def looks_like_model_item(item):
    keys = {str(k).lower() for k in item.keys()}
    key_text = " ".join(keys)
    value_text = " ".join(clean_text(v, 80) for v in item.values())
    combined = f"{key_text} {value_text}"
    has_name = any(k in keys for k in ["model", "model_name", "modelname", "name", "id"])
    has_price = "price" in key_text or "quota" in key_text or has_price_signal(value_text)
    return has_name and has_price and has_model_signal(combined)


def extract_from_json(data, site, url, checked_at):
    rows = []
    seen = set()

    def walk(obj):
        if len(rows) >= MAX_ROWS_PER_SITE:
            return
        if isinstance(obj, dict):
            if looks_like_model_item(obj):
                row = base_row(site, checked_at, url, "PUBLIC_JSON", "", "")
                raw_model_name = first_value(
                    obj,
                    ["model_name", "modelName", "model", "name", "id", "model_id", "modelId"],
                )
                row["raw_model_name"] = raw_model_name
                row["model_name"], model_tags = normalize_model_name(raw_model_name)
                row["model_tags"] = "|".join(model_tags)
                row["provider"] = first_value(
                    obj,
                    ["provider", "vendor", "supplier", "company", "owner", "group", "platform"],
                )
                row["model_type"] = first_value(obj, ["type", "model_type", "category", "mode"])
                raw_billing = first_value(
                    obj, ["billing_type", "billing", "charge_type", "quota_type"]
                )
                row["billing_type"] = billing_type_from(raw_billing, model_tags)
                row["input_price"] = (
                    value_by_key_contains(obj, ["input", "price"])
                    or value_by_key_contains(obj, ["prompt", "price"])
                    or value_by_key_contains(obj, ["input"])
                )
                row["output_price"] = (
                    value_by_key_contains(obj, ["output", "price"])
                    or value_by_key_contains(obj, ["completion", "price"])
                    or value_by_key_contains(obj, ["output"])
                )
                row["model_price"] = generic_price_value(obj)
                row["currency"] = first_value(obj, ["currency", "currency_code"])
                row["price_unit"] = first_value(obj, ["unit", "price_unit", "quota_unit"])
                price_bits = []
                for key, value in obj.items():
                    if any(word in str(key).lower() for word in ["price", "quota", "billing"]):
                        price_bits.append(f"{key}={clean_text(value, 100)}")
                row["raw_price_text"] = "; ".join(price_bits)[:800]
                row["confidence"] = "0.75"
                row["quality_flag"] = quality_flags_for_price_row(row)
                row["note"] = "从 JSON 字段自动抽取"
                if "GENERIC_PRICE_ONLY" in row["quality_flag"]:
                    row["note"] = append_note(row["note"], "通用价格不能视为输入价")
                if "ZERO_PRICE_CHECK" in row["quality_flag"]:
                    row["note"] = append_note(
                        row["note"], "价格为 0，可能是倍率/计费模式字段，需核对"
                    )
                key = (
                    row["model_name"],
                    row["provider"],
                    row["billing_type"],
                    row["input_price"],
                    row["output_price"],
                    row["model_price"],
                )
                if key not in seen:
                    seen.add(key)
                    rows.append(row)
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(data)
    return rows


def extract_model_name_from_block(block):
    lines = [clean_text(line, 120) for line in block.splitlines()]
    lines = [line for line in lines if line]
    for line in lines[:8]:
        lower = line.lower()
        if has_model_signal(line) and not has_price_signal(line) and len(line) <= 80:
            return line
    return lines[0][:80] if lines else ""


def extract_price(patterns, block):
    for pattern in patterns:
        m = re.search(pattern, block, re.IGNORECASE)
        if m:
            return clean_text(m.group(1), 80)
    return ""


def extract_from_text(text, site, url, checked_at, http_status):
    if not has_price_signal(text) or not has_model_signal(text):
        return []
    if is_api_error_response(text):
        return []

    blocks = re.split(r"\n\s*\n", text)
    if len(blocks) < 5:
        lines = [line for line in text.splitlines() if line.strip()]
        blocks = ["\n".join(lines[i : i + 10]) for i in range(0, len(lines), 6)]

    input_patterns = [
        r"(?:输入|input|prompt)[^\d¥￥$]{0,30}([¥￥$]?\s*\d+(?:\.\d+)?\s*(?:/[^\s,，。；;]*)?)",
    ]
    output_patterns = [
        r"(?:输出|补全|output|completion)[^\d¥￥$]{0,30}([¥￥$]?\s*\d+(?:\.\d+)?\s*(?:/[^\s,，。；;]*)?)",
    ]
    generic_price_pattern = r"([¥￥$]\s*\d+(?:\.\d+)?\s*(?:/[A-Za-z0-9万百万百万tokensToken次]+)?)"

    rows = []
    seen = set()
    for block in blocks:
        block = block.strip()
        if len(block) < 20 or len(block) > 1500:
            continue
        if is_noise_text_block(block):
            continue
        if not has_price_signal(block) or not has_model_signal(block):
            continue
        if not has_numeric_price(block):
            continue

        model_name = extract_model_name_from_block(block)
        if is_noise_text_block(model_name) or model_name.startswith(("{", "[", "<")):
            continue
        input_price = extract_price(input_patterns, block)
        output_price = extract_price(output_patterns, block)
        if not input_price and not output_price:
            m = re.search(generic_price_pattern, block)
            input_price = clean_text(m.group(1), 80) if m else ""
        if not (model_name or input_price or output_price):
            continue
        if not (input_price or output_price):
            continue

        key = (model_name, input_price, output_price)
        if key in seen:
            continue
        seen.add(key)

        row = base_row(site, checked_at, url, "PUBLIC_PAGE", http_status, "")
        row["raw_model_name"] = model_name
        row["model_name"] = model_name
        row["input_price"] = input_price
        row["output_price"] = output_price
        row["raw_price_text"] = clean_text(block, 800)
        row["confidence"] = "0.45"
        row["quality_flag"] = "PAGE_TEXT_REVIEW"
        row["note"] = "从页面文本自动抽取，格式多样，需人工核对"
        rows.append(row)
        if len(rows) >= MAX_ROWS_PER_SITE:
            break
    return rows


def fetch(session, url):
    return session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True, verify=False)


def probe_site(site, checked_at):
    online_status = site.get("online_status", "")
    if online_status in STOPPED_STATUSES:
        return [
            base_row(
                site,
                checked_at,
                site.get("final_url", ""),
                "SERVICE_STOPPED",
                "",
                "最新监测状态为 SERVICE_STOPPED，确认停止维护，跳过价格抓取",
            )
        ]

    if online_status in BLOCKED_STATUSES:
        return [
            base_row(
                site,
                checked_at,
                site.get("final_url", ""),
                "CLOUDFLARE_OR_BLOCKED",
                "",
                "监测已显示 Cloudflare/被拦截，跳过价格抓取",
            )
        ]

    if online_status not in ALIVE_STATUSES:
        return [
            base_row(
                site,
                checked_at,
                site.get("final_url", ""),
                "SITE_NOT_REACHABLE",
                "",
                f"最新监测状态为 {online_status}，跳过价格抓取",
            )
        ]

    session = requests.Session()
    best_status = "NO_MODEL_PAGE_FOUND"
    best_http_status = ""
    login_url = ""
    blocked_url = ""
    api_error_url = ""

    for url in candidate_urls(site):
        try:
            resp = fetch(session, url)
            http_status = str(resp.status_code)
            best_http_status = http_status
            content_type = resp.headers.get("content-type", "").lower()
            text = resp.text or ""

            if is_cloudflare(text):
                best_status = "CLOUDFLARE_OR_BLOCKED"
                blocked_url = str(resp.url)
                continue

            if is_login_required(text, resp.status_code):
                best_status = "LOGIN_REQUIRED"
                login_url = str(resp.url)
                continue

            if is_api_error_response(text):
                best_status = "API_ERROR"
                api_error_url = str(resp.url)
                continue

            json_rows = []
            if "json" in content_type:
                try:
                    data = resp.json()
                    json_rows = extract_from_json(data, site, str(resp.url), checked_at)
                except json.JSONDecodeError:
                    json_rows = []
            if json_rows:
                for row in json_rows:
                    row["http_status"] = http_status
                return json_rows

            text_rows = extract_from_text(text, site, str(resp.url), checked_at, http_status)
            if text_rows:
                return text_rows

            if resp.status_code < 400 and (has_price_signal(text) or has_model_signal(text)):
                best_status = "PARSE_FAILED"

        except Exception as exc:
            best_status = "FETCH_FAILED"
            best_http_status = ""
            last_error = clean_text(exc, 180)
            continue

        time.sleep(0.2)

    matched_url = login_url or blocked_url or api_error_url or site.get("final_url", "")
    note = "没有找到公开模型价格页"
    if best_status == "LOGIN_REQUIRED":
        note = "模型广场/价格页可能需要登录"
    elif best_status == "CLOUDFLARE_OR_BLOCKED":
        note = "价格页请求被 Cloudflare/人机验证拦截"
    elif best_status == "API_ERROR":
        note = "OpenAI-compatible API 返回错误信息，不是公开价格数据"
    elif best_status == "PARSE_FAILED":
        note = "页面似乎包含模型/价格文本，但自动解析失败"
    elif best_status == "FETCH_FAILED":
        note = f"请求失败：{locals().get('last_error', '')}"

    return [base_row(site, checked_at, matched_url, best_status, best_http_status, note)]


def save_rows(rows):
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    rows.sort(
        key=lambda row: (
            row.get("domain", ""),
            row.get("access_status", ""),
            row.get("model_name", ""),
            row.get("billing_type", ""),
        )
    )
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def save_summary(rows, monitor_checked_at):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["domain"], []).append(row)

    summary_rows = []
    for domain in sorted(grouped):
        site_rows = grouped[domain]
        first = site_rows[0]
        model_rows = [row for row in site_rows if row.get("model_name")]
        usable_rows = [
            row
            for row in model_rows
            if any(row.get(field) for field in ["input_price", "output_price", "model_price"])
        ]
        flag_counts = {}
        for row in model_rows:
            for flag in row.get("quality_flag", "").split("|"):
                if flag and flag != "OK":
                    flag_counts[flag] = flag_counts.get(flag, 0) + 1
        flags = "|".join(f"{key}:{flag_counts[key]}" for key in sorted(flag_counts))
        note = first.get("note", "") if not model_rows else ""
        if len(model_rows) >= MAX_ROWS_PER_SITE:
            flags = append_note(flags, f"ROW_LIMIT_REACHED:{MAX_ROWS_PER_SITE}").replace("；", "|")
            note = "已达到单站点行数上限，结果可能被截断"
        summary_rows.append(
            {
                "checked_at": first.get("checked_at", ""),
                "monitor_checked_at": monitor_checked_at,
                "domain": domain,
                "platform_name": first.get("platform_name", ""),
                "monitor_status": first.get("monitor_status", ""),
                "access_status": first.get("access_status", ""),
                "model_rows": len(model_rows),
                "usable_price_rows": len(usable_rows),
                "quality_flags": flags,
                "matched_url": first.get("matched_url", ""),
                "http_status": first.get("http_status", ""),
                "note": note,
            }
        )

    with open(SUMMARY_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(summary_rows)


def main():
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    sites, latest_ts = load_latest_round()
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"最新监测轮次: {latest_ts or 'n/a'}")
    print(f"待探测站点: {len(sites)}")
    print(f"并发数: {MAX_WORKERS}")

    rows = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(probe_site, site, checked_at): site for site in sites}
        for idx, future in enumerate(as_completed(futures), 1):
            site = futures[future]
            try:
                site_rows = future.result()
            except Exception as exc:
                site_rows = [
                    base_row(
                        site,
                        checked_at,
                        site.get("final_url", ""),
                        "PROBE_FAILED",
                        "",
                        clean_text(exc, 200),
                    )
                ]
            rows.extend(site_rows)
            status = site_rows[0].get("access_status", "") if site_rows else "EMPTY"
            print(f"[{idx:3d}/{len(sites)}] {site['domain']:<35} {status:<24} rows={len(site_rows)}")

    save_rows(rows)
    save_summary(rows, latest_ts)
    print(f"\n已保存: {OUTPUT_CSV}")
    print(f"站点汇总: {SUMMARY_CSV}")
    print(f"总行数: {len(rows)}")


if __name__ == "__main__":
    main()
