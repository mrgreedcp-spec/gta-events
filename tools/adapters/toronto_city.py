"""多伦多市政府 Festivals & Events 日历（Toronto Open Data: festivals-events）。

这个接口会拦截脚本（curl、无头浏览器一律 403），不能自动下载，只能在正常浏览器里导出。
导出方法见 说明.md；导出文件放 data/city/YYYY-MM-DD.json，本模块读取日期最新的一份。
许可：Open Government Licence – Toronto。活动描述和图片由主办方提交，属于许可排除的第三方
权利，所以只用主办方写的一句话简介（short_description）加链接，不引用图片。
"""
import datetime as dt
import json
import re
from pathlib import Path

from common import TZ, build_address, canonical_city, make_event, normalize_postal, normalize_times, slugify

CREDIT = "Contains information licensed under the Open Government Licence – Toronto (City of Toronto Festivals & Events calendar)."
CALENDAR_PAGE = "https://www.toronto.ca/explore-enjoy/festivals-events/festivals-events-calendar/"

TOPIC_MAP = {
    "Live Performances": ["音乐·演出"], "Music": ["音乐·演出"], "Theatre": ["音乐·演出"], "Dance": ["音乐·演出"],
    "Comedy": ["音乐·演出"], "Nightlife": ["音乐·演出"], "Film": ["音乐·演出"],
    "Arts/Exhibits": ["文化·艺术·展览"], "Museum": ["文化·艺术·展览"], "History": ["文化·艺术·展览"],
    "Cultural": ["文化·艺术·展览"], "Indigenous": ["文化·艺术·展览"], "2SLGBTQ+": ["文化·艺术·展览"],
    "Artisan": ["手工·爱好", "节庆·市集·美食"],
    "Food/Culinary": ["节庆·市集·美食"], "Farmers' Market": ["节庆·市集·美食"],
    "Street Festival": ["节庆·市集·美食"], "Celebrations": ["节庆·市集·美食"],
    "Family/Children": ["亲子·儿童"],
    "Environmental": ["运动·户外·游戏"], "Tour": ["运动·户外·游戏"], "Sports": ["运动·户外·游戏"],
    "Run/Walk": ["运动·户外·游戏"], "Trivia": ["运动·户外·游戏"],
    "Talks": ["阅读·讲座"], "Literary": ["阅读·讲座"], "Seminars/Workshops": ["阅读·讲座"],
    "Consumer Show/Convention": ["展会"], "Charity/Cause": ["社区"], "Public Square": ["社区"],
}
# 展览类每天一个场次，按 Google 的多日活动规则合并成一段起止日期；演出类每场单独一页
EXHIBIT = {"Arts/Exhibits", "Museum"}
PERFORMANCE = {"Live Performances", "Music", "Theatre", "Dance", "Comedy"}
MERGE_GAP_DAYS = 3


def parse_city_location(text, event_locations):
    """'Venue: 55 Centre Ave, Toronto, ON, M5G 2H5' → (场馆名, PostalAddress, geo, notes, errors)。"""
    notes, errors = [], []
    text = (text or "").strip()
    if not text or re.search(r"\(virtual\)|virtual|online", text, re.I):
        return None, {"@type": "PostalAddress"}, None, notes, ["线上活动（Google 活动搜索不支持纯线上活动）"]
    venue, _, addr = text.partition(": ")
    if not addr:
        venue, addr = None, text
    tokens = [t.strip() for t in re.split(r",|\s{2,}", addr) if t.strip()]
    postal = region = None
    rest = []
    for tok in tokens:
        m = re.fullmatch(r"(ON|Ontario)\s+([A-Z]\d[A-Z]\s?\d[A-Z]\d)", tok, re.I)
        if m:
            region, postal = "ON", normalize_postal(m.group(2))
        elif normalize_postal(tok):
            postal = normalize_postal(tok)
        elif tok.upper() in ("ON", "ONTARIO"):
            region = "ON"
        elif tok.lower() != "canada":
            rest.append(tok)
    street = next((t for t in rest if t[:1].isdigit()), None)
    locality = rest[-1] if len(rest) >= 2 and not rest[-1][:1].isdigit() else None
    if street and not locality:
        locality = "Toronto"
        notes.append("地址缺城市，按市政府日历默认填 Toronto")
    if not street:
        errors.append("地址缺少街道门牌（可能是街区或路线）")
    geo = None
    for loc in event_locations:
        if loc.get("address") and street and street.lower() in loc["address"].lower() and loc.get("lat") and loc.get("lng"):
            geo = (float(loc["lat"]), float(loc["lng"]))
    # 市政府日历里的地点都在安省（2026-09-30 导出的数据核对过城市字段），缺省份/国家时直接补
    address, addr_notes = build_address(street, canonical_city(locality), region or "ON", postal, "CA")
    return venue or street, address, geo, notes + addr_notes, errors


def complete_sentence(text):
    """来源的 short_description 常在半句处截断，补省略号，免得看起来像排版错误。"""
    text = " ".join((text or "").split())
    return text if not text or re.search(r"[.!?\"”’)]$", text) else text.rstrip(",;:- ") + "…"


def price_info(e):
    def num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    if e.get("free") == "Yes":
        return True, 0.0, None
    low, high = num(e.get("price_low")), num(e.get("price_high"))
    if low is None:
        low = num(e.get("price"))
    return False, low, high if high and low is not None and high > low else None


def runs(dates):
    """把排好序的日期切成若干段，相邻两天间隔不超过 MERGE_GAP_DAYS 就算同一段。"""
    groups = []
    for d in dates:
        if groups and (d - groups[-1][-1]).days <= MERGE_GAP_DAYS:
            groups[-1].append(d)
        else:
            groups.append([d])
    return groups


def load(data_dir, today):
    files = sorted(Path(data_dir, "city").glob("*.json"))
    if not files:
        return [], None
    payload = json.loads(files[-1].read_text(encoding="utf-8"))
    export_date = dt.date.fromisoformat(files[-1].stem[:10])
    by_event, seen = {}, set()
    for occ in payload["occurrences"]:
        key = (occ["sid"], occ["start"], occ["location"])
        if key in seen:  # 来源里有完全重复的场次
            continue
        seen.add(key)
        by_event.setdefault(occ["sid"], []).append(occ)

    events = []
    for sid, occs in by_event.items():
        e = payload["events"][sid]
        cats = e.get("categories") or []
        free, low, high = price_info(e)
        reg = {"Yes": "required", "No": "drop-in"}.get(e.get("reservations_required"))
        link = e.get("ticket_website") or e.get("website") or CALENDAR_PAGE
        if link and not link.startswith("http"):
            link = "https://" + link
        base = dict(
            source="city", source_name="City of Toronto", credit=CREDIT, slug=slugify(e["name"]),
            name=e["name"].strip(), categories=cats, topics=[t for c in cats for t in TOPIC_MAP.get(c, [])],
            free=free, price_low=low, price_high=high,
            offer_url=e.get("ticket_website") if (e.get("ticket_website") or "").startswith("http") else None,
            registration=reg, accessible=e.get("accessible") == "Yes",
            description=complete_sentence(e.get("short_description")), source_url=link,
            series_key=f"city:{sid}",
        )
        occs.sort(key=lambda o: o["start"])
        merge = bool(EXHIBIT & set(cats)) and not (PERFORMANCE & set(cats)) and len(occs) >= 5
        if merge:
            by_loc = {}
            for o in occs:
                by_loc.setdefault(o["location"], []).append(dt.datetime.fromisoformat(o["start"]).astimezone(TZ).date())
            for loc_text, dates in by_loc.items():
                place, address, geo, notes, errors = parse_city_location(loc_text, e.get("locations") or [])
                for run in runs(sorted(set(dates))):
                    if run[-1] < today:
                        continue
                    events.append(make_event(
                        **base, id=f"city-{sid[:12]}-{run[0].isoformat()}-run",
                        start=run[0], end=run[-1], all_day=True,
                        place_name=place, address=address, geo=geo, city=address.get("addressLocality"),
                        notes=notes + ([f"展览类：{len(run)} 个开放日合并为 {run[0]} 至 {run[-1]}"] if len(run) > 1 else []),
                        errors=errors,
                    ))
            continue
        for o in occs:
            start = dt.datetime.fromisoformat(o["start"]).astimezone(TZ)
            start, end, all_day, t_notes = normalize_times(start, None)
            if (start if all_day else start.date()) < today:
                continue
            place, address, geo, notes, errors = parse_city_location(o["location"], e.get("locations") or [])
            events.append(make_event(
                **base, id=f"city-{sid[:12]}-{o['start'][:16]}-{slugify(o['location'] or '', 12)}",
                start=start, end=end, all_day=all_day,
                place_name=place, address=address, geo=geo, city=address.get("addressLocality") or "Toronto",
                notes=t_notes + notes, errors=errors,
            ))
    return events, export_date
