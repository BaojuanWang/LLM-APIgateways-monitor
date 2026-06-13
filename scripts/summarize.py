"""
存活状态汇总脚本
运行位置: scripts/summarize.py
读取 results/monitor_results.csv，输出每个平台的综合存活状态
"""

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

BASE_DIR    = Path(__file__).parent.parent
RESULTS_CSV = BASE_DIR / "results" / "monitor_results.csv"
OUTPUT_DIR  = BASE_DIR / "results"

# 状态分层
ALIVE_STATUSES       = {"ONLINE", "CLOUDFLARE_OR_BLOCKED", "ONLINE_LOGIN_REQUIRED",
                        "HTTP_444", "ALIVE_BLOCKED", "REDIRECTED"}
UNCERTAIN_STATUSES   = {"TIMEOUT", "HTTP_ERROR"}
DEAD_STATUSES        = {"DNS_FAIL", "PARKED_OR_FOR_SALE"}

def classify_overall(status_counts):
    """根据历史状态判定综合存活状态"""
    statuses = set(status_counts.keys())

    # 有任何一次确认存活 → ALIVE
    if statuses & ALIVE_STATUSES:
        return "ALIVE"
    # 全是不确定 → UNCERTAIN
    if statuses <= UNCERTAIN_STATUSES:
        return "UNCERTAIN"
    # 全是DNS_FAIL → DEAD
    if statuses <= DEAD_STATUSES:
        return "DEAD"
    return "UNCERTAIN"


def load_results():
    if not RESULTS_CSV.exists():
        raise FileNotFoundError(f"找不到 {RESULTS_CSV}")

    platforms = defaultdict(lambda: {
        "platform_name": "",
        "source": "",
        "source_category": "",
        "checks": [],
        "status_counts": defaultdict(int),
        "last_status": "",
        "last_timestamp": "",
        "last_final_url": "",
        "last_page_title": "",
    })

    with open(RESULTS_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            domain = row.get("domain", "").strip()
            if not domain:
                continue
            p = platforms[domain]
            p["platform_name"] = row.get("platform_name", "") or p["platform_name"]

            source = row.get("source", "")
            p["source"] = source
            p["source_category"] = "manual" if source in ("Taobao", "Xiaohongshu") else "hvoy"

            status = row.get("online_status", "")
            p["status_counts"][status] += 1
            p["checks"].append({
                "timestamp": row.get("timestamp", ""),
                "status":    status,
            })

            # 保留最新一次
            ts = row.get("timestamp", "")
            if ts > p["last_timestamp"]:
                p["last_timestamp"]  = ts
                p["last_status"]     = status
                p["last_final_url"]  = row.get("final_url", "")
                p["last_page_title"] = row.get("page_title", "")

    return platforms


def make_date_path(stem, suffix):
    date_str = datetime.now().strftime("%Y-%m-%d")
    p = OUTPUT_DIR / f"{stem}_{date_str}.{suffix}"
    if not p.exists():
        return p
    n = 2
    while True:
        p = OUTPUT_DIR / f"{stem}_{date_str}_{n}.{suffix}"
        if not p.exists():
            return p
        n += 1


def save_excel(platforms):
    wb = Workbook()

    # 颜色
    header_fill   = PatternFill("solid", start_color="2D5EA2")
    header_font   = Font(bold=True, color="FFFFFF", name="Arial", size=10)
    alive_fill    = PatternFill("solid", start_color="D4EFDF")
    uncertain_fill= PatternFill("solid", start_color="FEF9E7")
    dead_fill     = PatternFill("solid", start_color="FADBD8")
    alt_fill      = PatternFill("solid", start_color="F0F4FA")

    status_fill = {
        "ALIVE":     alive_fill,
        "UNCERTAIN": uncertain_fill,
        "DEAD":      dead_fill,
    }

    # ── Sheet 1: 综合汇总 ─────────────────────────────────────
    ws = wb.active
    ws.title = "综合汇总"

    headers = [
        "域名", "平台名称", "来源", "来源分类",
        "综合判定", "检测次数", "最近状态", "最近检测时间",
        "ALIVE次数", "UNCERTAIN次数", "DEAD次数",
        "各状态明细", "最终URL", "页面标题"
    ]

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    rows = []
    for domain, p in platforms.items():
        sc = p["status_counts"]
        overall = classify_overall(sc)
        total = sum(sc.values())
        alive_n     = sum(v for k, v in sc.items() if k in ALIVE_STATUSES)
        uncertain_n = sum(v for k, v in sc.items() if k in UNCERTAIN_STATUSES)
        dead_n      = sum(v for k, v in sc.items() if k in DEAD_STATUSES)
        detail = ", ".join(f"{k}×{v}" for k, v in sorted(sc.items()))
        rows.append((overall, domain, p, total, alive_n, uncertain_n, dead_n, detail))

    # 排序：DEAD在前，UNCERTAIN其次，ALIVE最后（方便review）
    order = {"DEAD": 0, "UNCERTAIN": 1, "ALIVE": 2}
    rows.sort(key=lambda x: order.get(x[0], 9))

    for row_idx, (overall, domain, p, total, alive_n, uncertain_n, dead_n, detail) in enumerate(rows, 2):
        fill = status_fill.get(overall, alt_fill)
        vals = [
            domain,
            p["platform_name"],
            p["source"],
            p["source_category"],
            overall,
            total,
            p["last_status"],
            p["last_timestamp"],
            alive_n,
            uncertain_n,
            dead_n,
            detail,
            p["last_final_url"],
            p["last_page_title"],
        ]
        for col, val in enumerate(vals, 1):
            cell = ws.cell(row=row_idx, column=col, value=val)
            cell.font = Font(name="Arial", size=10)
            cell.alignment = Alignment(vertical="center")
            cell.fill = fill

    col_widths = [28, 18, 12, 10, 10, 8, 24, 22, 8, 10, 8, 35, 35, 40]
    for col, width in enumerate(col_widths, 1):
        ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = width
    ws.row_dimensions[1].height = 20
    ws.freeze_panes = "A2"

    # ── Sheet 2: 仅DEAD ───────────────────────────────────────
    ws2 = wb.create_sheet("疑似关闭")
    for col, h in enumerate(headers, 1):
        cell = ws2.cell(row=1, column=col, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
    dead_rows = [r for r in rows if r[0] == "DEAD"]
    for row_idx, (overall, domain, p, total, alive_n, uncertain_n, dead_n, detail) in enumerate(dead_rows, 2):
        vals = [domain, p["platform_name"], p["source"], p["source_category"],
                overall, total, p["last_status"], p["last_timestamp"],
                alive_n, uncertain_n, dead_n, detail, p["last_final_url"], p["last_page_title"]]
        for col, val in enumerate(vals, 1):
            cell = ws2.cell(row=row_idx, column=col, value=val)
            cell.font = Font(name="Arial", size=10)
            cell.fill = dead_fill
    for col, width in enumerate(col_widths, 1):
        ws2.column_dimensions[ws2.cell(row=1, column=col).column_letter].width = width
    ws2.freeze_panes = "A2"

    # ── Sheet 3: 仅UNCERTAIN ──────────────────────────────────
    ws3 = wb.create_sheet("待确认")
    for col, h in enumerate(headers, 1):
        cell = ws3.cell(row=1, column=col, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
    uncertain_rows = [r for r in rows if r[0] == "UNCERTAIN"]
    for row_idx, (overall, domain, p, total, alive_n, uncertain_n, dead_n, detail) in enumerate(uncertain_rows, 2):
        vals = [domain, p["platform_name"], p["source"], p["source_category"],
                overall, total, p["last_status"], p["last_timestamp"],
                alive_n, uncertain_n, dead_n, detail, p["last_final_url"], p["last_page_title"]]
        for col, val in enumerate(vals, 1):
            cell = ws3.cell(row=row_idx, column=col, value=val)
            cell.font = Font(name="Arial", size=10)
            cell.fill = uncertain_fill
    for col, width in enumerate(col_widths, 1):
        ws3.column_dimensions[ws3.cell(row=1, column=col).column_letter].width = width
    ws3.freeze_panes = "A2"

    # ── Sheet 4: 说明 ─────────────────────────────────────────
    ws4 = wb.create_sheet("说明")
    total_platforms = len(platforms)
    alive_count     = sum(1 for r in rows if r[0] == "ALIVE")
    uncertain_count = sum(1 for r in rows if r[0] == "UNCERTAIN")
    dead_count      = sum(1 for r in rows if r[0] == "DEAD")
    meta = [
        ("生成时间",    datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("数据来源",    str(RESULTS_CSV)),
        ("平台总数",    total_platforms),
        ("ALIVE",      f"{alive_count} 个（入口确认存活）"),
        ("UNCERTAIN",  f"{uncertain_count} 个（需进一步确认）"),
        ("DEAD",       f"{dead_count} 个（DNS解析失败，疑似关闭）"),
        ("", ""),
        ("判定规则",   ""),
        ("ALIVE",      "至少一次检测返回 ONLINE / Cloudflare / 444 / 登录页"),
        ("UNCERTAIN",  "所有检测均为 TIMEOUT 或 HTTP_ERROR"),
        ("DEAD",       "所有检测均为 DNS_FAIL"),
    ]
    for r, (k, v) in enumerate(meta, 1):
        ws4.cell(row=r, column=1, value=k).font = Font(bold=True, name="Arial")
        ws4.cell(row=r, column=2, value=str(v)).font = Font(name="Arial")
    ws4.column_dimensions["A"].width = 14
    ws4.column_dimensions["B"].width = 45

    path = make_date_path("summary", "xlsx")
    wb.save(path)
    return path, alive_count, uncertain_count, dead_count


def main():
    print("读取检测结果...")
    platforms = load_results()
    print(f"共 {len(platforms)} 个平台")

    path, alive, uncertain, dead = save_excel(platforms)

    print(f"\n── 综合判定 ──")
    print(f"  ALIVE     {alive}")
    print(f"  UNCERTAIN {uncertain}")
    print(f"  DEAD      {dead}")
    print(f"\n✅ 已保存: {path}")


if __name__ == "__main__":
    main()
