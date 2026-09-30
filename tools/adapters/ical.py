"""iCal 数据源（The Events Calendar 插件导出的 ?ical=1 日历）。

新增同类站点：在 SITES 里加一项，文件放 data/ical/<key>_*.ics。
"""
import datetime as dt
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from common import TZ, make_event, normalize_times, parse_location, slugify

SITES = {
    "vm": {
        "name": "Visit Mississauga",
        "feed": "https://www.visitmississauga.ca/events/month/{month}/?ical=1",
        "credit": "Listing data from the Visit Mississauga events calendar.",
    },
}
TOPIC_MAP = {
    "Community": ["社区"], "Music": ["音乐·演出"], "Family": ["亲子·儿童"],
    "Cultural": ["文化·艺术·展览"], "Trade Show / Expo": ["展会"], "Food": ["节庆·市集·美食"],
    "Festival": ["节庆·市集·美食"], "Arts": ["文化·艺术·展览"], "Sports": ["运动·户外·游戏"],
}


def unescape(value):
    return re.sub(r"\\([\\,;nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), value)


def parse_ics(text):
    text = re.sub(r"\r?\n[ \t]", "", text.replace("\r\n", "\n"))
    events = []
    for block in re.findall(r"BEGIN:VEVENT\n(.*?)\nEND:VEVENT", text, re.S):
        props = {}
        for line in block.split("\n"):
            m = re.match(r"([A-Z-]+)((?:;[^:]*)?):(.*)", line)
            if not m:
                continue
            name, params, value = m.groups()
            params = dict(p.split("=", 1) for p in params.split(";")[1:] if "=" in p)
            props.setdefault(name, (params, value))
        events.append(props)
    return events


def parse_dt(prop):
    params, value = prop
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        return dt.datetime.strptime(value, "%Y%m%d").date()
    if value.endswith("Z"):
        return dt.datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc).astimezone(TZ)
    tz = ZoneInfo(params["TZID"]) if "TZID" in params else TZ
    return dt.datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=tz)


def fact_sentence(place, city, categories, site_name):
    where = f" at {place}" if place else ""
    where += f" in {city}" if city else ""
    cats = f" Category: {', '.join(categories)}." if categories else ""
    return f"An event{where}, listed on the {site_name} events calendar.{cats} See the {site_name} page for details, prices and tickets."


def load(data_dir, today):
    events, seen = [], set()
    for key, site in SITES.items():
        for path in sorted(Path(data_dir, "ical").glob(f"{key}_*.ics")):
            for props in parse_ics(path.read_text(encoding="utf-8")):
                if "DTSTART" not in props or "SUMMARY" not in props:
                    continue
                start = parse_dt(props["DTSTART"])
                end = parse_dt(props["DTEND"]) if "DTEND" in props else None
                if isinstance(start, dt.date) and not isinstance(start, dt.datetime) and end is not None:
                    end = end - dt.timedelta(days=1)  # iCal DATE 型 DTEND 是"不含"的那天
                start, end, all_day, notes = normalize_times(start, end)
                start_day = start if all_day else start.date()
                if start_day < today:
                    continue
                uid = props.get("UID", ({}, ""))[1]
                dedupe = (uid, start.isoformat())
                if dedupe in seen:
                    continue
                seen.add(dedupe)

                name = unescape(props["SUMMARY"][1]).strip()
                place, address, loc_notes, loc_errors = parse_location(unescape(props.get("LOCATION", ({}, ""))[1]))
                source_url = props.get("URL", ({}, ""))[1]
                categories = [c.strip() for c in unescape(props.get("CATEGORIES", ({}, ""))[1]).split(",") if c.strip()]
                organizer = props["ORGANIZER"][0].get("CN", "").strip('"') or None if "ORGANIZER" in props else None
                slug = slugify(source_url.rstrip("/").rsplit("/", 1)[-1] if source_url else name)
                events.append(make_event(
                    id=f"{key}-{slugify(uid, 40)}-{start.isoformat()[:16]}", source=key, source_name=site["name"],
                    source_url=source_url, credit=site["credit"], slug=slug,
                    name=name, start=start, end=end, all_day=all_day,
                    place_name=place, address=address, city=address.get("addressLocality"),
                    categories=categories, topics=[t for c in categories for t in TOPIC_MAP.get(c, [])],
                    # 对方的图片和描述原文有版权：不转载，描述用字段拼成事实句，详情链回原页
                    image=None,
                    description=fact_sentence(place, address.get("addressLocality"), categories, site["name"]),
                    organizer=organizer,
                    cancelled=bool(re.search(r"\b(cancel+ed|postponed)\b", name, re.I)),
                    series_key=f"{key}:{slugify(name)}:{slugify(place or '')}",
                    notes=notes + loc_notes, errors=loc_errors,
                ))
    return events
