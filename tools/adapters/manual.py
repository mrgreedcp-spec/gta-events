"""手工收录的活动（官方日历里没有、但值得收录的）。

每条放在 data/manual/events.json，必须来自主办方官网，并在 verified 字段写明核实日期和出处。
描述用自己的话写事实，不抄官网文案。时间写本地时间（不带偏移），程序按多伦多时区补。
"""
import json
from pathlib import Path

from common import build_address, local, make_event, normalize_postal, normalize_times, slugify

CREDIT = "Event details from the organizer's website, checked by hand on {date}."


def load(data_dir, today):
    path = Path(data_dir, "manual", "events.json")
    if not path.exists():
        return []
    events = []
    for m in json.loads(path.read_text(encoding="utf-8")):
        start, end, all_day, notes = normalize_times(local(m["start"]), local(m["end"]) if m.get("end") else None)
        last = end or start
        if (last if all_day else last.date()) < today:
            continue
        address, addr_notes = build_address(m.get("street"), m.get("city"), m.get("region"),
                                            normalize_postal(m.get("postal")), "CA")
        events.append(make_event(
            id=m["id"], source="manual", source_name=m.get("source_name") or "Organizer website",
            source_url=m["source_url"], credit=CREDIT.format(date=m["verified"][:10]), slug=slugify(m["name"]),
            name=m["name"], start=start, end=end, all_day=all_day,
            place_name=m.get("place_name"), address=address, city=m.get("city"),
            categories=m.get("categories", []), topics=m.get("topics", []),
            free=m.get("free"), price_low=m.get("price_low"), price_high=m.get("price_high"),
            offer_url=m.get("offer_url"), registration=m.get("registration"),
            image=m.get("image"), description=m.get("description", ""), organizer=m.get("organizer"),
            series_key=f"manual:{m['id']}", notes=notes + addr_notes,
            errors=[] if m.get("street") and m.get("city") else ["地址不完整"],
        ))
    return events
