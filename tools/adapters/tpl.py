"""多伦多公共图书馆（TPL）活动 feed + 分馆信息表。

数据：Toronto Open Data
- library-branch-programs-and-events-feed → data/tpl/tpl-events-feed.json
- library-branch-general-information（4326 CSV）→ data/tpl/tpl-branches.csv
许可：Open Government Licence – Toronto。feed 没有描述和活动链接：描述由字段拼成事实句，
链接用 BiblioCommons 活动页（2026-09-30 在浏览器里抽查过可打开）。
"""
import csv
import json
import re
from pathlib import Path

from common import build_address, local, make_event, normalize_postal, normalize_times, slugify

EVENTS_URL = ("https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/fb343332-03cd-40b9-a1c8-c03a4a85ca1e/"
              "resource/aa5e1425-77f4-4cb4-a8ea-eb5ce7d4f34c/download/tpl-events-feed.json")
BRANCHES_URL = ("https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/f5aa9b07-da35-45e6-b31f-d6790eb9bd9b/"
                "resource/e69b6ebb-8688-4533-8fd9-b63bff1cacdd/download/tpl-branch-general-information-4326.csv")
EVENT_PAGE = "https://tpl.bibliocommons.com/v2/events/{id}"
CREDIT = "Contains information licensed under the Open Government Licence – Toronto (Toronto Public Library)."

TYPE_TOPICS = {
    "Conversation Circles": ["练英语·新移民"], "Language Learning": ["练英语·新移民"],
    "Crafts & Hobbies": ["手工·爱好"], "3D Printing": ["手工·爱好", "科技·编程"],
    "Fabrication Studio": ["手工·爱好", "科技·编程"],
    "Culture": ["文化·艺术·展览"], "Arts & Entertainment": ["文化·艺术·展览"], "Exhibits": ["文化·艺术·展览"],
    "History & Genealogy": ["文化·艺术·展览"],
    "Reading Programs & Storytimes": ["阅读·讲座"], "Book Clubs": ["阅读·讲座"],
    "Book Clubs & Writers Groups": ["阅读·讲座"], "Writing Groups": ["阅读·讲座"],
    "Author Talks & Lectures": ["阅读·讲座"],
    "Science & Engineering": ["科技·编程"], "Coding & Robotics": ["科技·编程"],
    "Artificial Intelligence": ["科技·编程"], "Computer Basics & Office Software": ["科技·编程"],
    "Audio & Visual": ["科技·编程"], "Digital Safety": ["科技·编程"],
    "Games & Sports": ["运动·户外·游戏"], "Nature & the Environment": ["运动·户外·游戏"],
    "Health & Wellness": ["健康"],
    "Personal Development": ["求职·理财·成长"], "Personal Finance": ["求职·理财·成长"],
    "Small Business & Entrepreneurship": ["求职·理财·成长"], "Career & Job Search": ["求职·理财·成长"],
    "Civic & Community Engagement": ["社区"], "Library Visits & Tours": ["社区"],
}
AUDIENCE_TOPICS = {
    "Preschool Children (0-5)": "亲子·儿童", "School Age Children (6-12)": "亲子·儿童",
    "Teens (13-17)": "青少年", "Older Adults": "长者",
}


def branch_key(name):
    """分馆名规范化：去掉 '- Closed'、'(formely …)'、统一 'St.Clair' 写法。"""
    name = re.sub(r"\s*-\s*Closed\s*$", "", name or "")
    name = re.sub(r"\s*\(formerly.*?\)|\s*\(formely.*?\)", "", name, flags=re.I)
    name = name.replace("St.Clair", "St. Clair")
    return name.strip().lower()


def load_branches(path):
    branches = {}
    for row in csv.DictReader(open(path, encoding="utf-8-sig")):
        if row["PhysicalBranch"] != "1":
            continue
        # Address 例：'1515 Albion Road, Toronto, ON, M9V 1B2'、'Woodside Square Mall, 1571 Sandhurst Circle, Toronto, ON, M1V 1V2'
        parts = [p.strip() for p in re.split(r",\s*Toronto\b", row["Address"])[0].split(",")]
        street = next((p for p in reversed(parts) if p[:1].isdigit()), parts[-1])
        website = (row["Website"] or "").replace("tpl.ca.ca", "tpl.ca")
        address, _ = build_address(street, "Toronto", "ON", normalize_postal(row["PostalCode"]), "CA")
        branches[branch_key(row["BranchName"])] = {
            "name": re.sub(r"\s*\(forme?r?ly.*?\)", "", row["BranchName"]).strip(),
            "address": address, "website": website,
            "geo": (float(row["Lat"]), float(row["Long"])) if row["Lat"] and row["Long"] else None,
        }
    return branches


def split(value):
    return [v.strip() for v in (value or "").split(",") if v.strip() and v.strip() != "None"]


def load(data_dir, today):
    if not Path(data_dir, "tpl", "tpl-events-feed.json").exists() or not Path(data_dir, "tpl", "tpl-branches.csv").exists():
        print("  ⚠ 没有图书馆数据，本次跳过")
        return []
    branches = load_branches(Path(data_dir, "tpl", "tpl-branches.csv"))
    raw = json.loads(Path(data_dir, "tpl", "tpl-events-feed.json").read_text(encoding="utf-8"))
    # 同一个 EventID 可能出现两次（一条写分馆名，一条写"分馆名 - Closed"），合并成一条
    by_id = {}
    for r in raw:
        by_id.setdefault(r["EventID"], []).append(r)
    events = []
    for rows in by_id.values():
        closed_any = any((x.get("LocationName") or "").rstrip().endswith("Closed") for x in rows)
        r = next((x for x in rows if not (x.get("LocationName") or "").rstrip().endswith("Closed")), rows[0])
        if r.get("Status") == "ENDED" or not r.get("StartTime"):
            continue
        start, end, all_day, notes = normalize_times(local(r["StartTime"]), local(r["EndTime"]) if r.get("EndTime") else None)
        if (start if all_day else start.date()) < today:
            continue

        location = r.get("LocationName") or "None"
        branch = branches.get(branch_key(location))
        errors = []
        if location == "None":
            errors.append("来源未提供地点")
        elif branch is None:
            errors.append(f"分馆 '{location}' 在分馆信息表里找不到")
        elif closed_any:
            errors.append("分馆临时关闭，活动实际地点请以图书馆页面为准")
        branch_name = branch["name"] if branch else re.sub(r"\s*-\s*Closed$", "", location)
        place = f"{branch_name} Branch, Toronto Public Library" if location != "None" else None

        types = [t.replace("​", "") for t in split(r.get("EventTypes"))]
        audiences = split(r.get("Audiences"))
        full = r.get("IsFull") == "True" or r.get("RegistrationIsFull") == "True"
        title = (r.get("Title") or "").strip()
        dropin = bool(re.search(r"drop[\s-]?in", title, re.I))
        facts = [f"A free program at the {branch_name} branch of Toronto Public Library." if place
                 else "A free Toronto Public Library program."]
        if audiences:
            facts.append("For: " + ", ".join(audiences) + ".")
        if types:
            facts.append("Program type: " + ", ".join(dict.fromkeys(types)) + ".")
        facts.append("Drop-in program." if dropin else "Check the library event page for registration details.")

        events.append(make_event(
            id=f"tpl-{r['EventID']}", source="tpl", source_name="Toronto Public Library",
            source_url=EVENT_PAGE.format(id=r["EventID"]), credit=CREDIT, slug=slugify(title),
            name=title, start=start, end=end, all_day=all_day,
            place_name=place, address=branch["address"] if branch else {"@type": "PostalAddress"},
            geo=branch["geo"] if branch else None, city="Toronto",
            categories=types, audiences=audiences,
            topics=[t for x in types for t in TYPE_TOPICS.get(x, [])] + [AUDIENCE_TOPICS[a] for a in audiences if a in AUDIENCE_TOPICS],
            free=True, price_low=0, offer_url=EVENT_PAGE.format(id=r["EventID"]),
            registration="drop-in" if dropin else None, full=full,
            image=None if "TPLIcons" in (r.get("FeaturedImageUrl") or "") else (r.get("FeaturedImageUrl") or None),
            description=" ".join(facts), organizer="Toronto Public Library",
            series_key=f"tpl:{slugify(title)}:{branch_key(location)}",
            notes=notes, errors=errors,
        ))
    return events
