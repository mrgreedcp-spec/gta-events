#!/usr/bin/env python3
"""独立校验：只看 site/ 里生成的文件，按 Google Event 结构化数据规则和本站约定逐条检查。

不复用 build.py 的数据。输出 校验报告.md（汇总）和 校验明细.csv（每页每条问题）。
规则来源：https://developers.google.com/search/docs/appearance/structured-data/event
"""
import csv
import datetime as dt
import html
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
LD_RE = re.compile(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', re.S)
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?[+-]\d{2}:\d{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATUS = {f"https://schema.org/{s}" for s in
          ("EventScheduled", "EventCancelled", "EventPostponed", "EventRescheduled", "EventMovedOnline")}
MODES = {f"https://schema.org/{m}" for m in
         ("OfflineEventAttendanceMode", "OnlineEventAttendanceMode", "MixedEventAttendanceMode")}
AVAIL = {f"https://schema.org/{a}" for a in ("InStock", "SoldOut", "PreOrder", "LimitedAvailability", "OnlineOnly")}
BUDGET = {"index.html": 150_000, "data/upcoming.js": 1_000_000, "assets/site.css": 8_000, "assets/app.js": 15_000}


def visible_text(page):
    body = page.split("<body>", 1)[-1]
    body = re.sub(r"<script.*?</script>", " ", body, flags=re.S)
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)))


def parse_when(value):
    if DATE_RE.match(value or ""):
        return dt.date.fromisoformat(value)
    if DATETIME_RE.match(value or ""):
        return dt.datetime.fromisoformat(value)
    return None


def check_event_page(path, page, today):
    """返回 (结论, 错误列表, 提示列表, url)。结论：通过 / 通过（有提示）/ 失败 / 无标记。"""
    errors, warnings = [], []
    if '<meta charset="utf-8">' not in page:
        errors.append("缺 meta charset")
    if '<html lang="en">' not in page:
        errors.append("详情页不是英文（加拿大只支持英文活动页）")
    canonical = re.search(r'<link rel="canonical" href="([^"]+)"', page)
    canonical = html.unescape(canonical.group(1)) if canonical else None
    blocks = LD_RE.findall(page)
    text = visible_text(page)
    if not blocks:
        if "Location to be confirmed" not in text:
            errors.append("没有标记，但页面上也没有'地点待核实'提示")
        return "无标记", errors, warnings, canonical
    if len(blocks) > 1:
        errors.append("一页里有多段 JSON-LD")
    try:
        data = json.loads(blocks[0])
    except json.JSONDecodeError as exc:
        return "失败", errors + [f"JSON 解析失败：{exc}"], warnings, canonical

    if data.get("@context") not in ("https://schema.org", "http://schema.org") or data.get("@type") != "Event":
        errors.append("@context/@type 不对")
    name = data.get("name") or ""
    if not name:
        errors.append("缺 name")
    start = parse_when(data.get("startDate"))
    if start is None:
        errors.append("startDate 格式不对")
    else:
        start_day = start if isinstance(start, dt.date) and not isinstance(start, dt.datetime) else start.date()
        if start_day < today:
            warnings.append("startDate 早于构建日")
    if "endDate" in data:
        end = parse_when(data["endDate"])
        if end is None:
            errors.append("endDate 格式不对")
        elif start is not None and type(end) is type(start) and end < start:
            errors.append("endDate 早于 startDate")
    else:
        warnings.append("缺 endDate（推荐）")
    loc = data.get("location") or {}
    addr = loc.get("address") or {}
    if loc.get("@type") != "Place" or addr.get("@type") != "PostalAddress":
        errors.append("location/address 类型不对")
    for field in ("streetAddress", "addressLocality"):
        if not addr.get(field):
            errors.append(f"地址缺 {field}")
    for field in ("addressRegion", "postalCode", "addressCountry"):
        if not addr.get(field):
            warnings.append(f"地址缺 {field}")
    if loc.get("name") and loc["name"].lower() in name.lower():
        warnings.append("活动名里含场馆名（Google 建议 name 不放地点）")
    if data.get("eventStatus") not in STATUS:
        errors.append("eventStatus 取值不对")
    if data.get("eventAttendanceMode") not in MODES:
        errors.append("eventAttendanceMode 取值不对")
    offers = data.get("offers")
    if offers:
        try:
            if float(offers.get("price")) < 0:
                errors.append("offers.price 为负")
        except (TypeError, ValueError):
            errors.append("offers.price 不是数字")
        if offers.get("priceCurrency") != "CAD":
            errors.append("offers.priceCurrency 不是 CAD")
        if "url" in offers and not offers["url"].startswith("https://"):
            warnings.append("offers.url 不是 https")
        if "availability" in offers and offers["availability"] not in AVAIL:
            errors.append("offers.availability 取值不对")
    else:
        warnings.append("缺 offers（推荐）")
    for img in data.get("image", []):
        if not img.startswith("https://"):
            errors.append("image 不是 https 绝对地址")
    url = data.get("url", "")
    if not url.startswith("https://"):
        errors.append("url 不是 https 绝对地址")
    elif "example.com" in url:
        warnings.append("url 仍是占位域名 example.com")
    if canonical != url:
        errors.append("JSON-LD 的 url 和 canonical 不一致")

    # 标记内容必须在页面上看得到
    if name and name not in text:
        errors.append("name 不在页面可见文字里")
    if start is not None and start.strftime("%b %-d, %Y") not in text:
        errors.append("开始日期不在页面可见文字里")
    for field, value in (("场馆名", loc.get("name")), ("街道地址", addr.get("streetAddress"))):
        if value and value not in text:
            errors.append(f"{field}不在页面可见文字里")
    return ("失败" if errors else ("通过（有提示）" if warnings else "通过")), errors, warnings, url


def main():
    meta = json.loads((SITE / "build_meta.json").read_text(encoding="utf-8"))
    today = dt.date.fromisoformat(meta["today"])
    verdicts = defaultdict(Counter)
    issue_count, issue_example, rows, urls = Counter(), {}, [], Counter()

    event_files = sorted((SITE / "events").rglob("*.html"))
    for path in event_files:
        source = path.relative_to(SITE / "events").parts[0]
        verdict, errors, warnings, url = check_event_page(path, path.read_text(encoding="utf-8"), today)
        verdicts[source][verdict] += 1
        if url:
            urls[url] += 1
        rel = str(path.relative_to(SITE))
        for level, items in (("错误", errors), ("提示", warnings)):
            for msg in items:
                key = (source, level, msg)
                issue_count[key] += 1
                issue_example.setdefault(key, rel)
                rows.append([rel, source, verdict, level, msg])

    site_checks = []
    dup = [u for u, n in urls.items() if n > 1]
    site_checks.append(("详情页网址全站唯一", not dup, f"{len(dup)} 个重复" if dup else f"{len(urls):,} 个"))
    series_files = sorted((SITE / "series").rglob("*.html"))
    ld_in_nav = [str(p.relative_to(SITE)) for p in series_files + [SITE / "index.html"]
                 if LD_RE.search(p.read_text(encoding="utf-8"))]
    site_checks.append(("系列页和列表页没有 Event 标记", not ld_in_nav, ", ".join(ld_in_nav[:3]) or f"检查 {len(series_files) + 1} 页"))
    no_charset = [str(p.relative_to(SITE)) for p in series_files + [SITE / "index.html"]
                  if '<meta charset="utf-8">' not in p.read_text(encoding="utf-8")]
    site_checks.append(("系列页和列表页都有 UTF-8 声明", not no_charset, ", ".join(no_charset[:3]) or "全部有"))

    sitemap = re.findall(r"<loc>(.*?)</loc>", (SITE / "sitemap.xml").read_text(encoding="utf-8"))
    expected = 1 + len(event_files) + len(series_files)
    base = meta["base_url"]
    missing = [u for u in sitemap if not (SITE / html.unescape(u)[len(base) + 1:]).exists()]
    site_checks.append(("sitemap 条数 = 列表页 + 详情页 + 系列页", len(sitemap) == expected, f"{len(sitemap):,} / {expected:,}"))
    site_checks.append(("sitemap 里的网址都有对应文件", not missing, f"{len(missing)} 个缺失" if missing else "全部存在"))

    raw = (SITE / "data" / "upcoming.js").read_text(encoding="utf-8")
    listing = json.loads(raw[len("window.GTA="):].rstrip().rstrip(";"))
    dirs = [s["dir"] for s in listing["sources"]]
    broken = []
    for row in listing["events"]:
        date = row[2][:10]
        rel = f"events/{dirs[row[7]]}/{date[:7]}/{date}-{row[0]}.html"
        if not (SITE / rel).exists():
            broken.append(rel)
    broken += [p for p in listing["series"] if not (SITE / p).exists()]
    site_checks.append(("列表数据里每条都能打开对应页面", not broken, f"{len(broken)} 个失效" if broken else f"{len(listing['events']):,} 条"))
    in_window = len(listing["events"])
    site_checks.append(("列表窗口内活动 ≥ 4,000 场", in_window >= 4000, f"{in_window:,} 场"))
    for rel, limit in BUDGET.items():
        size = (SITE / rel).stat().st_size
        site_checks.append((f"{rel} ≤ {limit // 1000} KB", size <= limit, f"{size / 1000:,.0f} KB"))

    tpl = verdicts.get("tpl", Counter())
    tpl_marked = tpl["通过"] + tpl["通过（有提示）"] + tpl["失败"]
    tpl_ok = (tpl["通过"] + tpl["通过（有提示）"]) / tpl_marked if tpl_marked else 0
    site_checks.append(("图书馆已加标记的详情页 0 错误比例 ≥ 95%", tpl_ok >= 0.95, f"{tpl_ok:.1%}"))

    kinds = ["通过", "通过（有提示）", "失败", "无标记"]
    src_rows = "\n".join(f"| {s} | " + " | ".join(f"{verdicts[s][k]:,}" for k in kinds) + f" | {sum(verdicts[s].values()):,} |"
                         for s in sorted(verdicts))
    check_rows = "\n".join(f"| {'✓' if ok else '✗'} {name} | {detail} |" for name, ok, detail in site_checks)
    top = issue_count.most_common(20)
    issue_rows = "\n".join(f"| {s} | {lvl} | {msg} | {n:,} | {issue_example[(s, lvl, msg)]} |" for (s, lvl, msg), n in top)
    report = f"""# 结构化标记校验报告

校验时间：{dt.datetime.now():%Y-%m-%d %H:%M}；站点生成于 {meta['generated']}（按 {today} 计算）
规则来源：[Google Event 结构化数据文档](https://developers.google.com/search/docs/appearance/structured-data/event)
这是本地规则检查，不等于 Google 官方认可；上线后应用 Rich Results Test 每个来源抽查几页。

## 全站检查

| 检查项 | 结果 |
|---|---|
{check_rows}

## 详情页结论（按来源）

"无标记"是生成时就判定地点不可靠的页面（分馆关闭、线上活动、只有街区名等），页面上会显示"Location to be confirmed"。

| 来源 | 通过 | 通过（有提示） | 失败 | 无标记 | 合计 |
|---|---|---|---|---|---|
{src_rows}

## 最常见的问题（前 20 类）

| 来源 | 级别 | 问题 | 页数 | 示例 |
|---|---|---|---|---|
{issue_rows or '| - | - | 无 | 0 | - |'}

全部明细见 校验明细.csv。
"""
    (ROOT / "校验报告.md").write_text(report, encoding="utf-8")
    with open(ROOT / "校验明细.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["页面", "来源", "结论", "级别", "问题"])
        w.writerows(rows)

    failed = [name for name, ok, _ in site_checks if not ok]
    print(f"详情页 {len(event_files):,}，系列页 {len(series_files):,}")
    for s in sorted(verdicts):
        print(f"  {s}: " + "，".join(f"{k} {verdicts[s][k]:,}" for k in kinds if verdicts[s][k]))
    print("全站检查：" + ("全部通过" if not failed else "未通过 → " + "；".join(failed)))
    print(f"报告 → {ROOT / '校验报告.md'}")
    sys.exit(1 if failed or sum(v["失败"] for v in verdicts.values()) else 0)


if __name__ == "__main__":
    main()
