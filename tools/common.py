"""各数据源共用的数据模型与工具函数。

每个 adapter 把自己的原始数据转成同一种活动记录（dict），字段见 make_event()。
"""
import datetime as dt
import html
import re
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Toronto")

POSTAL_RE = re.compile(r"^[A-Z]\d[A-Z]\d[A-Z]\d$", re.I)
# 加拿大邮编首字母 → 省份
PROVINCE_BY_POSTAL = {
    "A": "NL", "B": "NS", "C": "PE", "E": "NB", "G": "QC", "H": "QC", "J": "QC",
    "K": "ON", "L": "ON", "M": "ON", "N": "ON", "P": "ON", "R": "MB", "S": "SK",
    "T": "AB", "V": "BC", "X": "NT", "Y": "YT",
}
PROVINCES = {
    "ON": "ON", "ONTARIO": "ON", "QC": "QC", "QUEBEC": "QC", "BC": "BC",
    "BRITISH COLUMBIA": "BC", "AB": "AB", "ALBERTA": "AB", "MB": "MB", "MANITOBA": "MB",
    "SK": "SK", "SASKATCHEWAN": "SK", "NS": "NS", "NOVA SCOTIA": "NS", "NB": "NB",
    "NEW BRUNSWICK": "NB", "NL": "NL", "PE": "PE", "YT": "YT", "NT": "NT", "NU": "NU",
}
# 多伦多 1998 年合并前的城区名，统一归到 Toronto
TORONTO_DISTRICTS = {"toronto", "etobicoke", "north york", "scarborough", "york", "east york"}

# 列表页的统一中文主题（顺序即筛选按钮顺序）
TOPICS = [
    "练英语·新移民", "亲子·儿童", "青少年", "长者", "手工·爱好", "科技·编程",
    "阅读·讲座", "文化·艺术·展览", "音乐·演出", "节庆·市集·美食",
    "运动·户外·游戏", "宠物", "健康", "求职·理财·成长", "社区", "展会",
]
NEWCOMER_RE = re.compile(r"\b(esl|newcomers?|settlement|conversation circles?|english conversation|"
                         r"english (?:class|practice|café|cafe)|citizenship)\b", re.I)
CHINESE_RE = re.compile(r"mandarin|cantonese|chinese|[一-鿿]", re.I)
PET_RE = re.compile(r"\b(pets?|dogs?|puppy|puppies|kittens?|cat show)\b", re.I)


def make_event(**kw):
    """统一活动记录。必填：id, source, name, start。其余按需填写。"""
    event = {
        "id": None, "slug": None, "source": None, "source_name": None, "source_url": None, "credit": None,
        "name": None, "start": None, "end": None, "all_day": False,
        "place_name": None, "address": {"@type": "PostalAddress"}, "geo": None, "city": None,
        "categories": [], "topics": [], "audiences": [],
        "free": None, "price_low": None, "price_high": None, "offer_url": None,
        "registration": None, "full": False, "accessible": None,
        "image": None, "description": "", "organizer": None,
        "series_key": None, "cancelled": False, "chinese": False,
        "notes": [], "errors": [],
    }
    event.update(kw)
    # 来源里常有连续空格、不换行空格；页面渲染时会被合并，和标记对不上
    for key in ("name", "place_name", "description", "organizer"):
        if event[key]:
            event[key] = " ".join(event[key].split())
    event["address"] = {k: " ".join(v.split()) if isinstance(v, str) else v for k, v in event["address"].items()}
    text = f"{event['name']} {event['description']}"
    event["chinese"] = event["chinese"] or bool(CHINESE_RE.search(text))
    if NEWCOMER_RE.search(text) and "练英语·新移民" not in event["topics"]:
        event["topics"] = ["练英语·新移民"] + event["topics"]
    if PET_RE.search(event["name"] or ""):
        event["topics"] = event["topics"] + ["宠物"]
    event["topics"] = [t for t in TOPICS if t in set(event["topics"])]
    return event


# ---------- 时间 ----------

def normalize_times(start, end):
    """返回 (start, end, all_day, notes)。处理全天活动、无结束时间等来源数据问题。"""
    notes = []
    if isinstance(start, dt.date) and not isinstance(start, dt.datetime):
        return start, (end if end and end >= start else start), True, notes
    if start.time() == dt.time(0, 0) and (end is None or end.time() in (dt.time(0, 0), dt.time(23, 59), dt.time(23, 59, 59))):
        notes.append("来源时间是 00:00 起，按全天活动处理，只写日期")
        end_date = end.date() if end is not None and end.date() >= start.date() else start.date()
        if end is not None and end.time() == dt.time(0, 0) and end.date() > start.date():
            end_date = end.date() - dt.timedelta(days=1)
        return start.date(), end_date, True, notes
    if end is not None and end <= start:
        notes.append("来源结束时间 ≤ 开始时间，已省略 endDate")
        end = None
    return start, end, False, notes


def local(value):
    """'2026-10-31T14:00:00' 这类不带偏移的本地时间 → 带多伦多时区的 datetime。"""
    return dt.datetime.fromisoformat(value).replace(tzinfo=TZ)


# ---------- 地址 ----------

def normalize_postal(token):
    compact = (token or "").replace(" ", "").upper()
    return f"{compact[:3]} {compact[3:]}" if POSTAL_RE.match(compact) else None


def canonical_city(name):
    if not name:
        return None
    return "Toronto" if name.strip().lower() in TORONTO_DISTRICTS else name.strip()


def build_address(street, locality, region=None, postal=None, country=None):
    """补全省份/国家并返回 (address, notes)。"""
    notes = []
    if postal and not region:
        region = PROVINCE_BY_POSTAL.get(postal[0])
        notes.append(f"省份缺失，按邮编首字母推断为 {region}")
    if postal and not country:
        country = "CA"
        notes.append("国家缺失，按加拿大邮编格式推断为 CA")
    if not postal:
        notes.append("地址缺邮编（Google 要求详细地址，可能拿不到活动富结果）")
    address = {"@type": "PostalAddress"}
    for key, value in (("streetAddress", street), ("addressLocality", locality),
                       ("addressRegion", region), ("postalCode", postal), ("addressCountry", country)):
        if value:
            address[key] = value
    return address, notes


def parse_location(raw):
    """把 'Venue, 123 Street, City, ON, L5B 1A1, Canada' 拆成 (场馆名, PostalAddress, notes, errors)。"""
    notes, errors = [], []
    postal = region = country = None
    rest = []
    for token in (t.strip() for t in re.split(r",|\s{2,}", raw or "")):
        if not token:
            continue
        # "ON M2K 3C9" 这种省份和邮编挤在一起的写法
        m = re.fullmatch(r"([A-Za-z .]+?)\s+([A-Z]\d[A-Z]\s?\d[A-Z]\d)", token, re.I)
        if m and m.group(1).upper() in PROVINCES:
            region, postal = PROVINCES[m.group(1).upper()], normalize_postal(m.group(2))
            continue
        if normalize_postal(token):
            postal = normalize_postal(token)
            if token.upper() != postal:
                notes.append(f"邮编格式已规范化：{token} → {postal}")
        elif token.upper() in PROVINCES:
            region = PROVINCES[token.upper()]
        elif token.lower() in ("canada", "ca"):
            country = "CA"
        else:
            rest.append(token)

    name = street = locality = None
    if len(rest) >= 3:
        name, street, locality = ", ".join(rest[:-2]), rest[-2], rest[-1]
    elif len(rest) == 2:
        if rest[1][:1].isdigit():
            name, street = rest
        else:
            street, locality = rest
    elif len(rest) == 1:
        name = rest[0]
    if not name and street:
        name = street
    for field, value in (("场馆名", name), ("街道地址", street), ("城市", locality)):
        if not value:
            errors.append(f"地址缺少{field}")
    address, addr_notes = build_address(street, canonical_city(locality), region, postal, country)
    return name, address, notes + addr_notes, errors


# ---------- 文本 ----------

def slugify(text, limit=60):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:limit].strip("-") or "event"


def excerpt(text, limit=320):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(re.sub(r"https?://\S+", "", text))
    text = re.sub(r"\s*\n\s*", "\n", text).strip()
    paragraphs = [p.strip() for p in text.split("\n") if len(p.strip()) > 20]
    text = re.sub(r"\s+", " ", " ".join(paragraphs))
    if len(text) <= limit:
        return text
    cut = text[:limit]
    stop = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[:stop + 1] if stop > limit * 0.5 else cut.rsplit(" ", 1)[0] + "…").strip()


def esc(text):
    return html.escape(text or "", quote=True)
