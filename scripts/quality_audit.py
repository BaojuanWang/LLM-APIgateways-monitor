"""
Quality audit for fetched privacy-policy snapshots.

Run from the repository root:
    python3 scripts/quality_audit.py \
        --snapshots-dir data/privacy_snapshots \
        --out data/quality_audit.csv

This script is intentionally rule-based and has no LLM/API dependency. It is
meant to separate usable policy text from SPA/config/noise captures before
running any downstream coding prompt.
"""

import argparse
import csv
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path


FIELDS = [
    "domain",
    "date",
    "snapshot_file",
    "quality_label",
    "confidence",
    "length",
    "noise_ratio",
    "policy_keyword_hits",
    "legal_doc_title_hits",
    "empty_signal_hits",
]

LABEL_WRONG_EMPTY = "wrong_page_or_empty"
LABEL_NOISE = "js_shell_or_logo_noise"
LABEL_SPA_TERMS = "spa_embedded_terms"
LABEL_USABLE = "usable_policy_text"


POLICY_KEYWORD_PATTERNS = [
    r"隐私政策|privacy\s+policy",
    r"个人信息|personal\s+information|personal\s+data",
    r"收集|collect(?:ion|ed|s)?",
    r"使用.*信息|how\s+we\s+use|use\s+your\s+information",
    r"数据|data",
    r"API\s*使用|API\s*usage|usage\s+data|token\s+counts?",
    r"请求|prompt|response|request(?:s)?",
    r"日志|log(?:s|ging)?",
    r"保留|retain|retention",
    r"存储|store|storage|stored",
    r"第三方|third[-\s]?party",
    r"共享|share|sharing",
    r"披露|disclos(?:e|ure)",
    r"cookie",
    r"删除|delete|deletion",
    r"访问|access",
    r"更正|correct|rectif",
    r"安全|security|encrypt",
    r"联系|contact|support@|email",
    r"GDPR|欧盟|EEA|European",
]

LEGAL_DOC_TITLE_PATTERNS = [
    r"隐私政策|privacy\s+policy",
    r"服务条款|terms\s+of\s+service|service\s+terms",
    r"用户协议|user\s+agreement",
    r"使用政策|usage\s+policy|use\s+policy|acceptable\s+use",
    r"服务特定条款|service[-\s]?specific\s+terms",
    r"支持的国家|supported\s+regions?|supported\s+countries",
    r"Cookie\s*政策|cookie\s+policy",
    r"免责声明|disclaimer",
]

EMPTY_SIGNAL_PATTERNS = [
    r"you\s+need\s+to\s+enable\s+javascript",
    r"enable\s+javascript\s+to\s+run\s+this\s+app",
    r"404|not\s+found|页面不存在|找不到页面",
    r"403|forbidden|access\s+denied|拒绝访问",
    r"just\s+a\s+moment|checking\s+your\s+browser|cloudflare",
    r"登录|login|required|请登录",
    r"loading|加载中",
]

HYDRATION_MARKERS = [
    "(self.__next_f",
    "self.__next_f.push",
    "__NEXT_DATA__",
    "webpackJsonp",
]

BASE64_RE = re.compile(
    r"(?:data:[^,]{0,120};base64,)?[A-Za-z0-9+/]{180,}={0,2}"
)
LONG_CODE_TOKEN_RE = re.compile(
    r"[A-Za-z0-9_/$+.:;{}()[\]\"'=,\-\\]{160,}"
)
HTML_TAG_RE = re.compile(r"<[^>]{1,120}>")
FILENAME_RE = re.compile(
    r"^(?P<domain>.+)_(?P<date>\d{4}-\d{2}-\d{2})(?:_(?P<run>\d+))?\.txt$"
)


def compile_patterns(patterns):
    return [re.compile(pattern, re.IGNORECASE) for pattern in patterns]


POLICY_KEYWORD_RES = compile_patterns(POLICY_KEYWORD_PATTERNS)
LEGAL_DOC_TITLE_RES = compile_patterns(LEGAL_DOC_TITLE_PATTERNS)
EMPTY_SIGNAL_RES = compile_patterns(EMPTY_SIGNAL_PATTERNS)


def parse_snapshot_name(path):
    match = FILENAME_RE.match(path.name)
    if not match:
        return path.stem, ""
    return match.group("domain"), match.group("date")


def normalize_text(text):
    return re.sub(r"\s+", " ", text).strip()


def count_distinct_matches(text, patterns):
    return sum(1 for pattern in patterns if pattern.search(text))


def strip_hydration_tail_for_analysis(text):
    """
    If a page has a readable policy followed by Next/SPA hydration payload,
    analyze only the readable prefix. This prevents otherwise usable policies
    from being classified as noise because of framework serialization.
    """
    lower = text.lower()
    positions = [lower.find(marker.lower()) for marker in HYDRATION_MARKERS]
    positions = [pos for pos in positions if pos > 0]
    if not positions:
        return text

    pos = min(positions)
    prefix = text[:pos]
    if len(normalize_text(prefix)) >= 500 and count_distinct_matches(prefix, POLICY_KEYWORD_RES) >= 3:
        return prefix
    return text


def estimate_noise_ratio(text):
    if not text:
        return 0.0

    spans = []
    for regex in (BASE64_RE, LONG_CODE_TOKEN_RE, HTML_TAG_RE):
        spans.extend(match.span() for match in regex.finditer(text))

    marker_hits = 0
    marker_patterns = [
        "window.__",
        "self.__next_f",
        "_next/static",
        "function(){",
        "document.",
        "localStorage",
        "className",
        "children",
        "data:image",
        "base64",
    ]
    lower = text.lower()
    for marker in marker_patterns:
        marker_hits += lower.count(marker.lower())

    if not spans:
        noise_chars = 0
    else:
        spans.sort()
        merged = []
        for start, end in spans:
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            else:
                merged[-1][1] = max(merged[-1][1], end)
        noise_chars = sum(end - start for start, end in merged)

    # Markers are signals, not full spans. Give them a modest weight so large
    # base64 blobs dominate the ratio, while ordinary framework residue does not.
    noise_chars += marker_hits * 20
    return min(1.0, noise_chars / max(1, len(text)))


def choose_confidence(label, length, noise_ratio, policy_hits, legal_hits, empty_hits):
    if label == LABEL_WRONG_EMPTY:
        if length < 100 or empty_hits >= 2:
            return "high"
        return "medium"
    if label == LABEL_NOISE:
        if noise_ratio >= 0.40:
            return "high"
        if policy_hits == 0:
            return "medium"
        return "low"
    if label == LABEL_SPA_TERMS:
        if legal_hits >= 3:
            return "high"
        return "medium"
    if label == LABEL_USABLE:
        if length >= 1500 and policy_hits >= 5 and noise_ratio < 0.15:
            return "high"
        return "medium"
    return "low"


def classify_snapshot(path, min_empty_length=100, min_usable_length=500, noise_threshold=0.25):
    raw_text = path.read_text(encoding="utf-8-sig", errors="replace")
    raw_text = normalize_text(raw_text)
    analysis_text = normalize_text(strip_hydration_tail_for_analysis(raw_text))

    domain, date = parse_snapshot_name(path)
    length = len(raw_text)
    analysis_length = len(analysis_text)
    policy_hits = count_distinct_matches(analysis_text, POLICY_KEYWORD_RES)
    legal_hits = count_distinct_matches(analysis_text, LEGAL_DOC_TITLE_RES)
    empty_hits = count_distinct_matches(analysis_text, EMPTY_SIGNAL_RES)
    noise_ratio = estimate_noise_ratio(analysis_text)

    if length < min_empty_length or (empty_hits > 0 and analysis_length < min_usable_length):
        label = LABEL_WRONG_EMPTY
    elif noise_ratio > noise_threshold:
        label = LABEL_NOISE
    elif policy_hits == 0:
        if analysis_length < min_usable_length or empty_hits > 0:
            label = LABEL_WRONG_EMPTY
        else:
            label = LABEL_NOISE
    elif legal_hits >= 2:
        label = LABEL_SPA_TERMS
    elif analysis_length >= min_usable_length and policy_hits >= 2:
        label = LABEL_USABLE
    else:
        label = LABEL_WRONG_EMPTY

    confidence = choose_confidence(
        label=label,
        length=length,
        noise_ratio=noise_ratio,
        policy_hits=policy_hits,
        legal_hits=legal_hits,
        empty_hits=empty_hits,
    )

    return {
        "domain": domain,
        "date": date,
        "snapshot_file": path.name,
        "quality_label": label,
        "confidence": confidence,
        "length": length,
        "noise_ratio": f"{noise_ratio:.3f}",
        "policy_keyword_hits": policy_hits,
        "legal_doc_title_hits": legal_hits,
        "empty_signal_hits": empty_hits,
    }


def iter_snapshot_files(snapshots_dir):
    return sorted(
        path for path in snapshots_dir.glob("*.txt")
        if path.is_file() and not path.name.startswith(".")
    )


def write_csv(rows, out_path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows):
    label_counts = Counter(row["quality_label"] for row in rows)
    confidence_counts = Counter(row["confidence"] for row in rows)

    print("\nQuality audit summary")
    print(f"  total: {len(rows)}")
    for label, count in sorted(label_counts.items()):
        print(f"  {label:<24} {count}")

    print("\nConfidence")
    for confidence, count in sorted(confidence_counts.items()):
        print(f"  {confidence:<8} {count}")

    low_rows = [row for row in rows if row["confidence"] == "low"]
    if low_rows:
        print("\nLow-confidence files to inspect first:")
        for row in low_rows:
            print(f"  - {row['snapshot_file']} ({row['quality_label']})")


def run_audit(args):
    snapshots_dir = Path(args.snapshots_dir)
    out_path = Path(args.out)

    if not snapshots_dir.exists():
        raise FileNotFoundError(f"Missing snapshots directory: {snapshots_dir}")

    rows = [
        classify_snapshot(
            path,
            min_empty_length=args.min_empty_length,
            min_usable_length=args.min_usable_length,
            noise_threshold=args.noise_threshold,
        )
        for path in iter_snapshot_files(snapshots_dir)
    ]
    write_csv(rows, out_path)
    print_summary(rows)
    print(f"\nSaved: {out_path}")
    return rows


def run_self_test():
    samples = {
        "tokenmix.ai_2026-06-23.txt": (
            "Privacy Policy Last updated March 29 2026. "
            "We collect account information, payment information, API usage data, "
            "request metadata, token counts, IP address, cookies, and device data. "
            "We disclose data to third-party processors and retain logs for legal "
            "compliance. Contact support@example.com. " * 20
        ),
        "derouter.ai_2026-06-23.txt": (
            "隐私政策 最后更新 2026-03-28。我们收集的信息包括电子邮箱地址、"
            "API 使用数据、Token 消耗量、使用时间戳、交易记录、IP 地址。"
            "我们不会在服务器上存储您的 AI 对话内容。我们依赖第三方服务。"
            "您可以申请访问、更正或删除个人数据。联系我们 support@example.com。"
            * 18
            + " self.__next_f.push([1,\"className children _next/static\"]);"
        ),
        "anpin.ai_2026-06-23.txt": (
            "window.__APP_CONFIG__={login_agreement_documents:["
            "{\"title\":\"服务条款\",\"content_md\":\"# 服务条款 本平台提供 API 网关服务。\"},"
            "{\"title\":\"使用政策\",\"content_md\":\"# 使用政策 禁止违法用途。\"},"
            "{\"title\":\"服务特定条款\",\"content_md\":\"# 服务特定条款 ## 隐私与数据保护 "
            "我们收集账户信息、使用数据、支付信息、技术日志。使用数据保留90日。"
            "请求内容将转发至上游模型提供商，不会用于训练任何 AI 模型。\"}]}"
            * 6
        ),
        "unity2.ai_2026-06-23.txt": (
            "Unity2.Ai You need to enable JavaScript to run this app. "
            "login_agreement_documents title 服务条款 content_md title 使用政策 content_md "
            "data:image/png;base64," + ("A" * 5000)
        ),
        "empty.example_2026-06-23.txt": "You need to enable JavaScript to run this app.",
    }

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for filename, content in samples.items():
            (tmp_path / filename).write_text(content, encoding="utf-8")

        rows = [classify_snapshot(path) for path in iter_snapshot_files(tmp_path)]
        labels = {row["snapshot_file"]: row["quality_label"] for row in rows}

        expected = {
            "tokenmix.ai_2026-06-23.txt": LABEL_USABLE,
            "derouter.ai_2026-06-23.txt": LABEL_USABLE,
            "anpin.ai_2026-06-23.txt": LABEL_SPA_TERMS,
            "unity2.ai_2026-06-23.txt": LABEL_NOISE,
            "empty.example_2026-06-23.txt": LABEL_WRONG_EMPTY,
        }

        failed = {
            filename: (expected[filename], labels.get(filename))
            for filename in expected
            if labels.get(filename) != expected[filename]
        }
        if failed:
            print("Self-test failed:", failed, file=sys.stderr)
            return 1

        print_summary(rows)
        print("\nSelf-test passed.")
        return 0


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Rule-based quality audit for privacy policy snapshots."
    )
    parser.add_argument(
        "--snapshots-dir",
        default="data/privacy_snapshots",
        help="Directory containing *.txt policy snapshots.",
    )
    parser.add_argument(
        "--out",
        default="data/quality_audit.csv",
        help="Output CSV path.",
    )
    parser.add_argument(
        "--min-empty-length",
        type=int,
        default=100,
        help="Snapshots shorter than this are wrong_page_or_empty.",
    )
    parser.add_argument(
        "--min-usable-length",
        type=int,
        default=500,
        help="Minimum length for a readable policy candidate.",
    )
    parser.add_argument(
        "--noise-threshold",
        type=float,
        default=0.25,
        help="Noise ratio above this is js_shell_or_logo_noise.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run built-in synthetic tests and exit.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    if args.self_test:
        return run_self_test()
    run_audit(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
