#!/usr/bin/env python3
"""大多伦多活动汇总站生成器（多伦多 + 密西沙加）。

数据源（各自一个 adapter，见 tools/adapters/）：
  city    多伦多市政府节庆日历  data/city/YYYY-MM-DD.json（只能在浏览器里手动导出，见 说明.md）
  tpl     多伦多公共图书馆      data/tpl/（--fetch 自动下载）
  vm      Visit Mississauga    data/ical/vm_YYYY-MM.ics（--fetch 自动下载）
  manual  手工收录              data/manual/events.json（每条注明核实日期和出处）

输出 site/：每个场次一个英文详情页（带 schema.org Event JSON-LD）、系列页、中文列表页、sitemap。
先生成到 site.tmp/，成功后才替换 site/；任一来源数量比上次少一半以上会中止（--force 跳过）。

用法：
  python3 tools/build.py --fetch                              # 下载最新数据并生成
  python3 tools/build.py --base-url https://<用户名>.github.io/<仓库名>
只用 Python 标准库。
"""
import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render  # noqa: E402
from adapters import ical, manual, toronto_city, tpl  # noqa: E402
from common import TOPICS, TZ  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = ROOT / "site"
PLACEHOLDER_BASE = "https://example.com"
SOURCES = [  # 顺序 = 列表页来源编号；去重时靠前的优先保留
    {"key": "city", "dir": "city", "label": "多伦多市政府节庆日历"},
    {"key": "manual", "dir": "manual", "label": "手工收录"},
    {"key": "vm", "dir": "vm", "label": "Visit Mississauga"},
    {"key": "tpl", "dir": "tpl", "label": "多伦多公共图书馆"},
]
SOURCE_NOTES = {
    "city": "主办方提交、市政府审核；本站只用一句话简介，不转载图片。需要每周在浏览器里手动导出一次。",
    "manual": "官方日历里没有、手工核实后收录的活动，每条注明核实日期。",
    "vm": "密西沙加旅游局官方日历，每天自动更新。",
    "tpl": "108 个分馆的免费活动，每天自动更新；分馆临时关闭的场次标为地点待核实。",
}
GAPS = [
    "Eventbrite、Meetup 上的民间活动（没有公开接口，爬取违反条款）",
    "Ticketmaster 的商业演出和体育赛事（需要自己注册 API key，尚未接入）",
    "NOW Toronto、Harbourfront Centre（网站拒绝自动访问）",
    "密西沙加、宾顿等其他城市的图书馆活动（没有可用的开放数据）",
    "宾顿、约克区、杜兰区、奥克维尔等城市的官方活动（没有可用日历；奥克维尔的日历只有 2019–2021 年旧数据）",
]
ADAPTERS = {"city": toronto_city, "tpl": tpl, "vm": ical, "manual": manual}


# ---------- 下载 ----------

def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "GTA-events-builder/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except urllib.error.URLError as exc:
        # python.org 版 Python 在 macOS 上常缺根证书，退回系统自带的 curl
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        return subprocess.run(["curl", "-fsSL", url], check=True, capture_output=True, timeout=120).stdout


def save_checked(path, url, check, label):
    """下载并检查内容；失败只警告、保留旧文件（数量骤降由后面的闸门拦截）。"""
    try:
        data = download(url)
    except Exception as exc:  # noqa: BLE001  网络错误种类很多，统一当作这个来源本次不可用
        print(f"  ⚠ {label} 下载失败：{exc}")
        return False
    if not check(data):
        print(f"  ⚠ {label} 下载内容不对（{len(data):,} 字节），保留旧文件")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    print(f"  已下载 {label}：{len(data):,} 字节")
    return True


def fetch(today):
    print("下载数据：")
    save_checked(DATA / "tpl" / "tpl-events-feed.json", tpl.EVENTS_URL,
                 lambda b: b.lstrip().startswith(b"[") and b"EventID" in b, "图书馆活动 feed")
    save_checked(DATA / "tpl" / "tpl-branches.csv", tpl.BRANCHES_URL,
                 lambda b: b"BranchName" in b[:500], "图书馆分馆信息")
    month = today.replace(day=1)
    for _ in range(3):
        key = f"{month:%Y-%m}"
        save_checked(DATA / "ical" / f"vm_{key}.ics", ical.SITES["vm"]["feed"].format(month=key),
                     lambda b: b"BEGIN:VCALENDAR" in b, f"Visit Mississauga {key}")
        month = (month + dt.timedelta(days=32)).replace(day=1)


# ---------- 整理 ----------

def day_of(e):
    return e["start"] if e["all_day"] else e["start"].date()


def last_day(e):
    end = e["end"] or e["start"]
    return end if e["all_day"] else end.date()


def norm_title(name):
    name = re.sub(r"\b20\d\d\b", " ", (name or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", name).strip()


def dedupe(events):
    """跨来源去重：标题（去年份、标点）+ 开始日期 + 邮编前三位（没有就用城市）。"""
    order = {s["key"]: i for i, s in enumerate(SOURCES)}
    kept, log = {}, []
    for e in sorted(events, key=lambda x: order[x["source"]]):
        area = (e["address"].get("postalCode") or e["city"] or "")[:3].upper()
        key = (norm_title(e["name"]), day_of(e).isoformat(), area)
        if key in kept and kept[key]["source"] != e["source"]:
            log.append(f"{e['source']} 的 “{e['name']}”（{key[1]}）与 {kept[key]['source']} 重复，保留后者")
            continue
        kept.setdefault(key, e)
        if kept[key] is not e and kept[key]["source"] == e["source"]:
            kept[(*key, e["id"])] = e  # 同一来源同名同日的不同场次，照常保留
    return list(kept.values()), log


def short_hash(text, n=6):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def assign_paths(events, base_url):
    used = set()
    for e in events:
        day = day_of(e)
        hhmm = "allday" if e["all_day"] else f"{e['start']:%H%M}"
        slug = (e["slug"] or "event")[:50].strip("-")
        n = 6
        while True:
            tail = f"{slug}-{hhmm}-{short_hash(e['id'], n)}"
            path = f"events/{e['source']}/{day:%Y-%m}/{day.isoformat()}-{tail}.html"
            if path not in used:
                break
            n += 2
        used.add(path)
        e["tail"], e["path"] = tail, path
        e["page_url"] = f"{base_url.rstrip('/')}/{path}"


def build_series(events):
    groups = {}
    for e in events:
        groups.setdefault(e["series_key"], []).append(e)
    series = {}
    for key, items in groups.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda x: (day_of(x).isoformat(), x["start"].isoformat()))
        first = items[0]
        path = f"series/{first['source']}/{(first['slug'] or 'series')[:50].strip('-')}-{short_hash(key)}.html"
        series[path] = items
        for e in items:
            e["series_path"] = path
    return series


def listing_rows(events, today, window_days):
    """列表页用的紧凑数据（见 render.APP_JS 里的字段说明）。"""
    horizon = today + dt.timedelta(days=window_days - 1)
    src_index = {s["key"]: i for i, s in enumerate(SOURCES)}
    places, place_index, series_list, series_index, rows, window = [], {}, [], {}, [], []
    # 同一天里有具体时间的排前面，全天和多日展览排后面
    for e in sorted(events, key=lambda x: (day_of(x).isoformat(), "99:99" if x["all_day"] else f"{x['start']:%H:%M}", x["name"])):
        if day_of(e) > horizon or last_day(e) < today:
            continue
        window.append(e)
        place = (e["place_name"] or "地点待定", e["city"] or "")
        if place not in place_index:
            place_index[place] = len(places)
            places.append(list(place))
        sp = e.get("series_path")
        if sp and sp not in series_index:
            series_index[sp] = len(series_list)
            series_list.append(sp)
        topics = sum(1 << TOPICS.index(t) for t in e["topics"])
        virtual = any("线上" in x for x in e["errors"])
        flags = (1 * bool(e["free"]) | 2 * (e["registration"] == "drop-in") | 4 * e["chinese"] | 8 * e["full"]
                 | 16 * e["cancelled"] | 32 * bool(e["errors"]) | 64 * virtual)
        start = day_of(e).isoformat() if e["all_day"] else f"{e['start']:%Y-%m-%d %H:%M}"
        end = last_day(e).isoformat() if e["all_day"] and last_day(e) != day_of(e) else ""
        rows.append([e["tail"], e["name"], start, end, place_index[place], topics, flags,
                     src_index[e["source"]], series_index.get(sp, -1)])
    return {"places": places, "series": series_list, "events": rows}, window


# ---------- 主流程 ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", action="store_true", help="先下载图书馆和 Visit Mississauga 的最新数据")
    ap.add_argument("--base-url", default=PLACEHOLDER_BASE, help="网站上线后的根网址")
    ap.add_argument("--today", help="按这一天生成（测试用，YYYY-MM-DD）")
    ap.add_argument("--window-days", type=int, default=60, help="列表页显示未来多少天（详情页不受限制）")
    ap.add_argument("--force", action="store_true", help="数量骤降也照样生成")
    args = ap.parse_args()
    now = dt.datetime.now(TZ)
    today = dt.date.fromisoformat(args.today) if args.today else now.date()
    generated = now.strftime("%Y-%m-%d %H:%M %Z")
    if args.fetch:
        fetch(today)

    events, counts, city_export = [], {}, None
    for s in SOURCES:
        result = ADAPTERS[s["key"]].load(DATA, today)
        if s["key"] == "city":
            result, city_export = result
        counts[s["key"]] = len(result)
        events += result

    meta_path = SITE / "build_meta.json"
    if meta_path.exists() and not args.force:
        previous = json.loads(meta_path.read_text(encoding="utf-8")).get("counts", {})
        drops = [f"{k}: {previous[k]} → {counts.get(k, 0)}" for k in previous
                 if previous[k] >= 20 and counts.get(k, 0) < previous[k] * 0.5]
        if drops:
            raise SystemExit("数量比上次少一半以上，已中止（旧站点保留；确认无误可加 --force）：" + "；".join(drops))

    events, dedupe_log = dedupe(events)
    assign_paths(events, args.base_url)
    series = build_series(events)
    listing, window = listing_rows(events, today, args.window_days)

    out = ROOT / "site.tmp"
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    (out / "data").mkdir()
    (out / "assets" / "site.css").write_text(render.CSS, encoding="utf-8")
    (out / "assets" / "app.js").write_text(render.APP_JS, encoding="utf-8")
    for e in events:
        target = out / e["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render.detail_page(e, "../../../", generated), encoding="utf-8")
    for path, items in series.items():
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render.series_page(items, "../../", generated), encoding="utf-8")

    data = {"generated": generated, "topics": TOPICS,
            "sources": [{"dir": s["dir"], "label": s["label"]} for s in SOURCES], **listing}
    (out / "data" / "upcoming.js").write_text(
        "window.GTA=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")

    city_stale = bool(city_export and (today - city_export).days > 14)
    ctx = {
        "generated": generated, "window_days": args.window_days, "window_count": len(window),
        "sources": [{"label": s["label"], "count": sum(e["source"] == s["key"] for e in events),
                     "marked": sum(e["source"] == s["key"] and not e["errors"] for e in events),
                     "note": SOURCE_NOTES[s["key"]] + (f"（本次数据导出于 {city_export}）" if s["key"] == "city" and city_export else "")}
                    for s in SOURCES],
        "gaps": GAPS, "city_export": city_export, "city_stale": city_stale,
        "credits": ["Contains information licensed under the Open Government Licence – Toronto.",
                    "密西沙加活动数据来自 Visit Mississauga 官方日历。手工收录的活动以主办方官网为准。"],
        "prerender": render.prerender_cards([e for e in window if day_of(e) <= today + dt.timedelta(days=1)][:60]),
    }
    (out / "index.html").write_text(render.index_page(ctx), encoding="utf-8")

    base = args.base_url.rstrip("/")
    urls = [f"{base}/index.html"] + [f"{base}/{e['path']}" for e in events] + [f"{base}/{p}" for p in series]
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"<url><loc>{render.esc(u)}</loc><lastmod>{today}</lastmod></url>\n" for u in urls)
        + "</urlset>\n", encoding="utf-8")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n", encoding="utf-8")
    (out / "build_meta.json").write_text(json.dumps(
        {"generated": generated, "today": today.isoformat(), "base_url": base, "counts": counts,
         "pages": {"events": len(events), "series": len(series)}, "window": len(window)},
        ensure_ascii=False, indent=1), encoding="utf-8")

    if SITE.exists():
        shutil.rmtree(SITE)
    out.rename(SITE)

    errors = {}
    for e in events:
        for msg in e["errors"][:1]:
            errors[(e["source"], msg)] = errors.get((e["source"], msg), 0) + 1
    log = [f"# 构建日志\n\n生成：{generated}；按 {today} 计算；列表窗口 {args.window_days} 天\n",
           "## 各来源\n", "| 来源 | 读入 | 去重后 | 已加标记 |", "|---|---|---|---|"]
    for s in SOURCES:
        mine = [e for e in events if e["source"] == s["key"]]
        log.append(f"| {s['label']} | {counts[s['key']]} | {len(mine)} | {sum(not e['errors'] for e in mine)} |")
    log += [f"\n详情页 {len(events)} 个，系列页 {len(series)} 个，列表窗口内 {len(window)} 场。\n",
            "## 未加标记的原因\n"] + [f"- {s}：{m}（{n} 条）" for (s, m), n in sorted(errors.items(), key=lambda x: -x[1])]
    log += ["\n## 跨来源去重\n"] + ([f"- {x}" for x in dedupe_log] or ["- 无"])
    (ROOT / "构建日志.md").write_text("\n".join(log) + "\n", encoding="utf-8")

    print(f"完成：详情页 {len(events):,}，系列页 {len(series):,}，列表窗口 {len(window):,} 场 → {SITE}")
    for s in SOURCES:
        print(f"  {s['label']}：{sum(e['source'] == s['key'] for e in events):,}")
    if dedupe_log:
        print(f"  跨来源去重 {len(dedupe_log)} 条（见 构建日志.md）")


if __name__ == "__main__":
    main()
