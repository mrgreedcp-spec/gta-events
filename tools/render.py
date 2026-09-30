"""页面模板：英文详情页（带 JSON-LD）、中文系列页、中文列表页，以及共用的 CSS/JS。"""
import json

from common import TOPICS, esc

WEEKDAY_ZH = "一二三四五六日"
SITE_NAME_EN = "GTA Events"
SITE_NAME_ZH = "大多伦多活动汇总"


# ---------- 格式 ----------

def en_when(e):
    s, t = e["start"], e["end"]
    day = lambda d: d.strftime("%a, %b %-d, %Y")
    clock = lambda d: d.strftime("%-I:%M %p").replace(":00 ", " ")
    if e["all_day"]:
        return day(s) + (f" – {day(t)}" if t and t != s else "") + ("" if t and t != s else " (all day)")
    if t is None:
        return f"{day(s)} · {clock(s)}"
    if t.date() == s.date():
        return f"{day(s)} · {clock(s)} – {clock(t)}"
    return f"{day(s)}, {clock(s)} – {day(t)}, {clock(t)}"


def zh_day(d):
    return f"{d.month}月{d.day}日 周{WEEKDAY_ZH[d.weekday()]}"


def zh_when(e):
    s, t = e["start"], e["end"]
    if e["all_day"]:
        return zh_day(s) + (f" – {zh_day(t)}" if t and t != s else " 全天")
    if t is None:
        return f"{zh_day(s)} {s:%H:%M}"
    if t.date() == s.date():
        return f"{zh_day(s)} {s:%H:%M}–{t:%H:%M}"
    return f"{zh_day(s)} {s:%H:%M} – {zh_day(t)} {t:%H:%M}"


def price_text(e):
    if e["free"]:
        return "Free"
    if e["price_low"] is not None:
        low = f"${e['price_low']:,.2f}".replace(".00", "")
        if e["price_high"]:
            return f"{low} – ${e['price_high']:,.2f}".replace(".00", "")
        return low if e["price_low"] > 0 else "Free"
    return None


def address_line(addr):
    parts = [addr.get("streetAddress"), addr.get("addressLocality"),
             " ".join(p for p in (addr.get("addressRegion"), addr.get("postalCode")) if p),
             "Canada" if addr.get("addressCountry") == "CA" else addr.get("addressCountry")]
    return ", ".join(p for p in parts if p)


# ---------- 结构化数据 ----------

def event_jsonld(e):
    data = {"@context": "https://schema.org", "@type": "Event", "name": e["name"],
            "startDate": e["start"].isoformat()}
    if e["end"] and (e["all_day"] or e["end"] != e["start"]):
        data["endDate"] = e["end"].isoformat()
    data["eventStatus"] = "https://schema.org/" + ("EventCancelled" if e["cancelled"] else "EventScheduled")
    data["eventAttendanceMode"] = "https://schema.org/OfflineEventAttendanceMode"
    place = {"@type": "Place", "name": e["place_name"], "address": e["address"]}
    if e["geo"]:
        place["geo"] = {"@type": "GeoCoordinates", "latitude": e["geo"][0], "longitude": e["geo"][1]}
    data["location"] = place
    if e["image"]:
        data["image"] = [e["image"]]
    if e["description"]:
        data["description"] = e["description"]
    if e["price_low"] is not None:
        offer = {"@type": "Offer", "price": f"{e['price_low']:.2f}", "priceCurrency": "CAD"}
        if e["offer_url"]:
            offer["url"] = e["offer_url"]
        if e["full"]:
            offer["availability"] = "https://schema.org/SoldOut"
        data["offers"] = offer
    if e["organizer"]:
        data["organizer"] = {"@type": "Organization", "name": e["organizer"]}
    data["url"] = e["page_url"]
    return data


# ---------- 外壳 ----------

def shell(lang, title, body, root, head_extra="", description=""):
    desc = f'\n<meta name="description" content="{esc(description)}">' if description else ""
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>{desc}
<link rel="stylesheet" href="{root}assets/site.css">
{head_extra}
</head>
<body>
{body}
</body>
</html>
"""


def detail_page(e, root, generated):
    head = f'<link rel="canonical" href="{esc(e["page_url"])}">'
    if not e["errors"]:
        ld = json.dumps(event_jsonld(e), ensure_ascii=False, indent=1).replace("</", "<\\/")
        head += f'\n<script type="application/ld+json">\n{ld}\n</script>'
    facts = [("When", esc(en_when(e)))]
    if e["place_name"] or address_line(e["address"]):
        facts.append(("Where", "<br>".join(esc(x) for x in (e["place_name"], address_line(e["address"])) if x)))
    if price_text(e):
        facts.append(("Price", esc(price_text(e))))
    if e["registration"]:
        facts.append(("Registration", "Not required (drop-in)" if e["registration"] == "drop-in" else "Required"))
    if e["audiences"]:
        facts.append(("For", esc(", ".join(e["audiences"]))))
    if e["organizer"]:
        facts.append(("Organizer", esc(e["organizer"])))
    if e["categories"]:
        facts.append(("Category", esc(", ".join(dict.fromkeys(e["categories"])))))
    facts_html = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in facts)
    badges = ""
    if e["cancelled"]:
        badges += '<span class="tag bad">Cancelled</span>'
    if e["full"]:
        badges += '<span class="tag warn">Full</span>'
    if e["errors"]:
        badges += f'<span class="tag warn">Location to be confirmed with the organizer</span>'
    series = f'<a class="btn ghost" href="{root}{e["series_path"]}">All dates of this program</a>' if e.get("series_path") else ""
    image = f'<img class="hero" src="{esc(e["image"])}" alt="" loading="lazy">' if e["image"] else ""
    body = f"""<div class="wrap">
<p class="crumbs"><a href="{root}index.html">← All GTA events</a></p>
<header><h1>{esc(e['name'])}</h1>{f'<p>{badges}</p>' if badges else ''}</header>
{image}
<dl class="facts">{facts_html}</dl>
{f'<p>{esc(e["description"])}</p>' if e['description'] else ''}
<p class="actions"><a class="btn" href="{esc(e['source_url'])}" rel="noopener">Details &amp; registration ({esc(e['source_name'])})</a>{series}</p>
<footer>{esc(e['credit'])} Times are local (Toronto). Please confirm details with the organizer before you go. Updated {generated}.</footer>
</div>"""
    title = f"{e['name']} – {en_when(e)}" + (f" · {e['place_name']}" if e["place_name"] else "") + f" | {SITE_NAME_EN}"
    return shell("en", title, body, root, head, description=(e["description"] or e["name"])[:155])


def series_page(items, root, generated):
    first = items[0]
    groups, current = [], None
    for e in items:
        month = f"{e['start'].year}年{e['start'].month}月"
        if month != current:
            if current:
                groups.append("</ul>")
            groups.append(f'<h2 class="month">{month}</h2><ul class="dates">')
            current = month
        flags = "（已满）" if e["full"] else ""
        groups.append(f'<li><a href="{root}{e["path"]}">{esc(zh_when(e))}</a>{flags}</li>')
    groups.append("</ul>")
    place = first["place_name"] or "地点待定"
    body = f"""<div class="wrap">
<p class="crumbs"><a href="{root}index.html">← 返回活动列表</a></p>
<header><h1>{esc(first['name'])}</h1>
<p class="sub">{esc(place)} · 共 {len(items)} 场 · 来源：{esc(first['source_name'])}</p></header>
<div class="panel">这是一个重复举办的系列活动。点日期进入该场次的详情页（英文），报名方式以主办方页面为准。</div>
{''.join(groups)}
<footer>{esc(first['credit'])} 更新于 {generated}。</footer>
</div>"""
    return shell("zh-CN", f"{first['name']} · {place} — 全部 {len(items)} 场 | {SITE_NAME_ZH}", body, root,
                 description=f"{first['name']}（{place}）全部场次")


def index_page(ctx):
    src_rows = "".join(f"<li><b>{esc(s['label'])}</b>：{s['count']:,} 条，其中 {s['marked']:,} 条已加结构化标记。{esc(s['note'])}</li>"
                       for s in ctx["sources"])
    gaps = "".join(f"<li>{esc(g)}</li>" for g in ctx["gaps"])
    topic_chips = "".join(f'<button class="chip" type="button" data-topic="{i}" aria-pressed="false">{esc(t)}</button>'
                          for i, t in enumerate(TOPICS))
    stale = (f'<p class="tag warn">市政府日历是 {ctx["city_export"]} 手动导出的，已超过 14 天，请重新导出。</p>'
             if ctx.get("city_stale") else "")
    body = f"""<div class="wrap">
<header><h1>{SITE_NAME_ZH}</h1>
<p class="sub">多伦多 + 密西沙加 · 未来 {ctx['window_days']} 天共 <b id="total">{ctx['window_count']:,}</b> 场 · 更新于 {ctx['generated']}</p></header>
{stale}
<details class="panel"><summary>数据来源与覆盖范围（不是"全部"活动，请看这里）</summary>
<ul>{src_rows}</ul>
<p>没有覆盖：</p><ul>{gaps}</ul>
<p>活动详情页是英文的，因为 Google 在加拿大只支持英文活动页；列表和系列页是中文。</p>
</details>
<section class="filters" aria-label="筛选">
<div class="row" role="group" aria-label="时间">
<button class="chip" type="button" data-range="today" aria-pressed="false">今天</button>
<button class="chip" type="button" data-range="tomorrow" aria-pressed="false">明天</button>
<button class="chip" type="button" data-range="weekend" aria-pressed="false">本周末</button>
<button class="chip" type="button" data-range="7" aria-pressed="false">7 天内</button>
<button class="chip" type="button" data-range="30" aria-pressed="false">30 天内</button>
<button class="chip" type="button" data-range="all" aria-pressed="true">全部 {ctx['window_days']} 天</button>
</div>
<div class="row" role="group" aria-label="主题"><button class="chip" type="button" data-topic="" aria-pressed="true">全部主题</button>{topic_chips}</div>
<div class="row controls">
<label>城市 <select id="city"><option value="">全部</option><option value="Toronto">多伦多</option><option value="Mississauga">密西沙加</option></select></label>
<label>来源 <select id="source"><option value="">全部</option>{''.join(f'<option value="{i}">{esc(s["label"])}</option>' for i, s in enumerate(ctx["sources"]))}</select></label>
<label><input type="checkbox" id="free"> 免费</label>
<label><input type="checkbox" id="dropin"> 无需预约</label>
<label><input type="checkbox" id="chinese"> 中文相关</label>
<input type="search" id="q" placeholder="搜索活动名、场馆、分馆" aria-label="关键词">
</div>
</section>
<p class="count" id="count" aria-live="polite"></p>
<div id="list">{ctx['prerender']}</div>
<p><button class="btn ghost" type="button" id="more" hidden>再显示 100 场</button></p>
<footer>{' '.join(esc(c) for c in ctx['credits'])}<br>活动信息以主办方为准；标"地点待核实"的活动，请在出发前到主办方页面确认。</footer>
</div>
<script src="data/upcoming.js"></script>
<script src="assets/app.js"></script>"""
    return shell("zh-CN", f"{SITE_NAME_ZH}（多伦多 + 密西沙加）", body, "",
                 description="多伦多和密西沙加未来 60 天的公开活动汇总：图书馆、市政府节庆、密西沙加官方日历。")


def prerender_cards(items, root=""):
    """无 JS 时也能看到的前几十条（JS 加载后会被替换）。"""
    out, current = [], None
    for e in items:
        day = e["start"] if e["all_day"] else e["start"].date()
        if day != current:
            out.append(f'<h2 class="day">{zh_day(day)}</h2>')
            current = day
        time = "全天" if e["all_day"] else f"{e['start']:%H:%M}"
        out.append(f'<article class="card"><p class="time">{time}</p><div><h3><a href="{root}{e["path"]}">{esc(e["name"])}</a></h3>'
                   f'<p class="meta">{esc(e["place_name"] or "地点待定")}</p></div></article>')
    return "".join(out)


CSS = """:root{--bg:#f7f5f0;--surface:#fff;--text:#1d1d1b;--muted:#65625a;--line:#e3dfd5;
--accent:#b4441f;--accent-soft:#f6e3da;--ok:#2f6b3a;--ok-soft:#e1efe2;--warn:#8a5a00;--warn-soft:#f7ebcf;
--bad:#9b1c1c;--bad-soft:#f8dddd;--radius:12px}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#171613;--surface:#22201c;
--text:#eeebe3;--muted:#a8a397;--line:#38352e;--accent:#f08a5d;--accent-soft:#3a261c;--ok:#8fd19a;
--ok-soft:#1d3322;--warn:#e8c16a;--warn-soft:#3a2f14;--bad:#f19a9a;--bad-soft:#3d1d1d}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Segoe UI",Roboto,sans-serif}
a{color:var(--accent)}
.wrap{max-width:880px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.7rem;line-height:1.25;margin:0 0 6px}
.sub{color:var(--muted);margin:0 0 16px;font-size:.95rem}
.crumbs{margin:0 0 12px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:12px 16px;margin:0 0 16px;font-size:.92rem}
.panel summary{cursor:pointer;font-weight:600}
.panel ul{margin:8px 0;padding-left:20px}
.filters{position:sticky;top:0;z-index:2;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line);margin-bottom:8px}
.row{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 8px}
.controls{align-items:center;gap:10px 14px;font-size:.92rem}
.controls select,.controls input[type=search]{font:inherit;padding:5px 8px;border:1px solid var(--line);border-radius:8px;background:var(--surface);color:var(--text)}
.controls input[type=search]{flex:1 1 200px;min-width:0}
.chip{border:1px solid var(--line);background:var(--surface);color:var(--text);border-radius:999px;padding:4px 12px;font:inherit;font-size:.88rem;cursor:pointer}
.chip[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:#fff}
.count{color:var(--muted);font-size:.9rem;margin:6px 0}
h2.day,h2.month{font-size:1rem;color:var(--muted);margin:22px 0 8px;font-weight:600}
.card{display:grid;grid-template-columns:64px 1fr;gap:12px;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:10px 12px;margin:0 0 8px}
.card .time{margin:0;font-variant-numeric:tabular-nums;color:var(--muted);font-size:.92rem}
.card h3{margin:0 0 2px;font-size:1rem;line-height:1.35}
.card h3 a{color:var(--text);text-decoration:none}
.card h3 a:hover{text-decoration:underline}
.meta{color:var(--muted);font-size:.88rem;margin:0}
.tags{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}
.tag{display:inline-block;font-size:.76rem;padding:1px 8px;border-radius:999px;background:var(--accent-soft);color:var(--accent);margin:0 4px 0 0}
.tag.ok{background:var(--ok-soft);color:var(--ok)}
.tag.warn{background:var(--warn-soft);color:var(--warn)}
.tag.bad{background:var(--bad-soft);color:var(--bad)}
.hero{width:100%;max-height:340px;object-fit:cover;border-radius:var(--radius);margin:8px 0 16px;background:var(--line)}
dl.facts{display:grid;grid-template-columns:auto 1fr;gap:6px 16px;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:14px 16px;margin:0 0 16px}
dl.facts dt{color:var(--muted)}
dl.facts dd{margin:0;min-width:0;overflow-wrap:anywhere}
.btn{display:inline-block;background:var(--accent);color:#fff;text-decoration:none;border-radius:999px;padding:8px 16px;margin:6px 8px 0 0;border:1px solid var(--accent);font:inherit;cursor:pointer}
.btn.ghost{background:transparent;color:var(--accent)}
ul.dates{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:6px}
ul.dates li{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:6px 10px;font-size:.92rem}
footer{color:var(--muted);font-size:.84rem;margin-top:32px;border-top:1px solid var(--line);padding-top:12px}
@media (max-width:520px){h1{font-size:1.4rem}.card{grid-template-columns:52px 1fr;gap:8px}.filters{position:static}}
"""

APP_JS = r"""(function () {
  var D = window.GTA; if (!D) return;
  var SRC_DIR = D.sources.map(function (s) { return s.dir; });
  var WD = '一二三四五六日';
  var fmt = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/Toronto', year: 'numeric', month: '2-digit', day: '2-digit'});
  var today = fmt.format(new Date());
  function addDays(iso, n) { var d = new Date(iso + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); }
  function dow(iso) { return new Date(iso + 'T12:00:00Z').getUTCDay(); }
  function dayLabel(iso) { var d = new Date(iso + 'T12:00:00Z'); return (d.getUTCMonth() + 1) + '月' + d.getUTCDate() + '日 周' + WD[(d.getUTCDay() + 6) % 7]; }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]; }); }
  // 每条：[文件尾, 名称, 开始, 结束, 场馆序号, 主题位, 标记位, 来源序号, 系列序号]
  var ev = D.events.map(function (a) {
    return {tail: a[0], name: a[1], start: a[2], end: a[3], place: D.places[a[4]], topics: a[5], flags: a[6], src: a[7], series: a[8],
            date: a[2].slice(0, 10), text: (a[1] + ' ' + D.places[a[4]][0]).toLowerCase()};
  }).filter(function (e) { return e.date >= today || (e.end && e.end.length === 10 && e.end >= today); });
  var state = {range: 'all', topic: '', city: '', source: '', free: false, dropin: false, chinese: false, q: '', shown: 100};
  function inRange(e) {
    var r = state.range, d = e.date < today ? today : e.date;
    if (r === 'all') return true;
    if (r === 'today') return d === today;
    if (r === 'tomorrow') return d === addDays(today, 1);
    if (r === 'weekend') {
      var w = dow(today), sat = addDays(today, w === 0 ? -1 : 6 - w), sun = addDays(sat, 1);
      return (d >= sat && d <= sun) || (e.date <= sun && e.end && e.end.length === 10 && e.end >= sat);
    }
    return d <= addDays(today, +r - 1);
  }
  function match(e) {
    if (!inRange(e)) return false;
    if (state.topic !== '' && !(e.topics & (1 << +state.topic))) return false;
    if (state.city && e.place[1] !== state.city) return false;
    if (state.source !== '' && e.src !== +state.source) return false;
    if (state.free && !(e.flags & 1)) return false;
    if (state.dropin && !(e.flags & 2)) return false;
    if (state.chinese && !(e.flags & 4)) return false;
    if (state.q && e.text.indexOf(state.q) === -1) return false;
    return true;
  }
  function card(e) {
    var t = e.start.length === 10 ? (e.end && e.end !== e.start ? '至 ' + (+e.end.slice(5, 7)) + '/' + (+e.end.slice(8, 10)) : '全天') : e.start.slice(11, 16);
    var href = 'events/' + SRC_DIR[e.src] + '/' + e.date.slice(0, 7) + '/' + e.date + '-' + e.tail + '.html';
    var tags = [];
    for (var i = 0; i < D.topics.length; i++) if (e.topics & (1 << i)) tags.push('<span class="tag">' + D.topics[i] + '</span>');
    if (e.flags & 1) tags.push('<span class="tag ok">免费</span>');
    if (e.flags & 2) tags.push('<span class="tag ok">无需预约</span>');
    if (e.flags & 4) tags.push('<span class="tag">中文相关</span>');
    if (e.flags & 8) tags.push('<span class="tag warn">已满</span>');
    if (e.flags & 16) tags.push('<span class="tag bad">已取消</span>');
    if (e.flags & 64) tags.push('<span class="tag warn">线上</span>');
    else if (e.flags & 32) tags.push('<span class="tag warn">地点待核实</span>');
    var series = e.series >= 0 ? ' · <a href="' + D.series[e.series] + '">全部场次</a>' : '';
    return '<article class="card"><p class="time">' + t + '</p><div><h3><a href="' + href + '">' + esc(e.name) + '</a></h3>' +
      '<p class="meta">' + esc(e.place[0]) + ' · ' + D.sources[e.src].label + series + '</p><div class="tags">' + tags.join('') + '</div></div></article>';
  }
  var list = document.getElementById('list'), more = document.getElementById('more'), count = document.getElementById('count');
  function render() {
    var hits = ev.filter(match), html = [], last = '';
    hits.slice(0, state.shown).forEach(function (e) {
      var d = e.date < today ? today : e.date;
      if (d !== last) { html.push('<h2 class="day">' + dayLabel(d) + (e.date < today ? '（进行中）' : '') + '</h2>'); last = d; }
      html.push(card(e));
    });
    list.innerHTML = html.join('') || '<p class="count">没有符合条件的活动，换个筛选试试。</p>';
    count.textContent = '共 ' + hits.length.toLocaleString() + ' 场' + (hits.length > state.shown ? '，已显示前 ' + state.shown : '');
    more.hidden = hits.length <= state.shown;
  }
  // 筛选条件写进网址（?topic=宠物&range=weekend&free=1），方便分享
  function saveUrl() {
    var p = new URLSearchParams();
    if (state.range !== 'all') p.set('range', state.range);
    if (state.topic !== '') p.set('topic', D.topics[+state.topic]);
    ['city', 'source'].forEach(function (k) { if (state[k] !== '') p.set(k, state[k]); });
    ['free', 'dropin', 'chinese'].forEach(function (k) { if (state[k]) p.set(k, '1'); });
    if (state.q) p.set('q', state.q);
    try { history.replaceState(null, '', location.pathname + (p.toString() ? '?' + p : '')); } catch (e) {}
  }
  function syncControls() {
    document.querySelectorAll('[data-range]').forEach(function (x) { x.setAttribute('aria-pressed', String(x.getAttribute('data-range') === state.range)); });
    document.querySelectorAll('[data-topic]').forEach(function (x) { x.setAttribute('aria-pressed', String(x.getAttribute('data-topic') === state.topic)); });
    ['city', 'source'].forEach(function (k) { document.getElementById(k).value = state[k]; });
    ['free', 'dropin', 'chinese'].forEach(function (k) { document.getElementById(k).checked = state[k]; });
    var q = document.getElementById('q');
    if (document.activeElement !== q) q.value = state.q;  // 正在打字时不回写，免得吞掉空格
  }
  function update(key, value) { state[key] = value; state.shown = 100; syncControls(); saveUrl(); render(); }
  var params = new URLSearchParams(location.search);
  if (params.get('range')) state.range = params.get('range');
  if (params.get('topic') && D.topics.indexOf(params.get('topic')) >= 0) state.topic = String(D.topics.indexOf(params.get('topic')));
  ['city', 'source'].forEach(function (k) { if (params.get(k)) state[k] = params.get(k); });
  ['free', 'dropin', 'chinese'].forEach(function (k) { state[k] = params.get(k) === '1'; });
  state.q = (params.get('q') || '').toLowerCase();
  document.querySelectorAll('[data-range]').forEach(function (b) { b.addEventListener('click', function () { update('range', b.getAttribute('data-range')); }); });
  document.querySelectorAll('[data-topic]').forEach(function (b) { b.addEventListener('click', function () { update('topic', b.getAttribute('data-topic')); }); });
  ['city', 'source'].forEach(function (id) { document.getElementById(id).addEventListener('change', function (e) { update(id, e.target.value); }); });
  ['free', 'dropin', 'chinese'].forEach(function (id) { document.getElementById(id).addEventListener('change', function (e) { update(id, e.target.checked); }); });
  document.getElementById('q').addEventListener('input', function (e) { update('q', e.target.value.trim().toLowerCase()); });
  more.addEventListener('click', function () { state.shown += 100; render(); });
  syncControls();
  render();
})();
"""
