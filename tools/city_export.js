// 多伦多市政府节庆日历导出脚本（每周一次）
//
// 这个接口会拦截脚本类客户端，只能在正常浏览器里、在它自己的页面上运行：
// 1. 用 Chrome 打开 https://secure.toronto.ca/c3api_data/v2/DataAccess.svc/festivals_events/events?$top=1
// 2. 按 Cmd+Option+J 打开控制台，把本文件全部内容粘进去，回车
// 3. 等几十秒，浏览器会下载 YYYY-MM-DD.json；把它放进项目的 data/city/ 文件夹，再运行 build.py
// 输出格式与 tools/adapters/toronto_city.py 读取的格式一致。
(async () => {
  const API = 'https://secure.toronto.ca/c3api_data/v2/DataAccess.svc/festivals_events/events';
  const today = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/Toronto', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date());
  const offset = new Intl.DateTimeFormat('en-US', {timeZone: 'America/Toronto', timeZoneName: 'longOffset'})
    .formatToParts(new Date()).find(p => p.type === 'timeZoneName').value.replace('GMT', '') || '-05:00';
  const filter = `calendar_date ge ${today}T00:00:00${offset}`;
  const rows = [];
  let total = null;
  for (let skip = 0; total === null || skip < total; skip += 500) {
    const url = `${API}?$format=application/json;odata.metadata=none&$count=true&$orderby=id&$top=500&$skip=${skip}&$filter=${encodeURIComponent(filter)}`;
    const d = await (await fetch(url)).json();
    total = d['@odata.count'];
    rows.push(...d.value);
    console.log(`已取 ${rows.length} / ${total}`);
    if (!d.value.length) break;
  }
  if (rows.length !== total) throw new Error(`条数不一致：${rows.length} / ${total}，请重试`);

  const parseJ = x => { if (typeof x !== 'string') return x; try { return JSON.parse(x); } catch (e) { return x; } };
  const nul = x => (x === null || x === 'null' || x === '' || x === undefined) ? null : x;
  const events = {}, occurrences = [];
  for (const r of rows) {
    const sid = r.submission_id;
    if (!events[sid]) {
      events[sid] = {
        name: r.event_name, short_description: nul(r.short_description),
        categories: parseJ(r.event_category) || [], status: r.event_status,
        free: r.free_event, price_low: nul(r.event_price_low), price_high: nul(r.event_price_high), price: nul(r.event_price),
        reservations_required: r.reservations_required, accessible: r.accessible_event,
        website: nul(r.event_website), ticket_website: nul(r.ticket_website),
        startdate: r.event_startdate, enddate: r.event_enddate, expirydate: r.event_expirydate,
        locations: (parseJ(r.event_locations) || []).map(l => {
          const g = parseJ(l.location_gps); const gp = Array.isArray(g) && g[0] ? g[0] : {};
          return {name: nul(l.location_name), address: nul(l.location_address),
                  lat: gp.gps_lat ?? (nul(l.geo_lat) ? +l.geo_lat : null), lng: gp.gps_lng ?? (nul(l.geo_long) ? +l.geo_long : null), type: l.location_type};
        }),
      };
    }
    const ts = Date.parse(r.calendar_date);
    const d = (parseJ(r.event_dates) || []).find(x => x.date === ts);
    occurrences.push({id: r.id, sid, start: r.calendar_date, time_of_day: r.calendar_time_of_day, location: d && d.locations ? d.locations[0] : null});
  }
  const out = JSON.stringify({source: 'City of Toronto Festivals & Events calendar (festivals-events)', api: API,
    exported_at: new Date().toISOString(), filter: filter + ', $orderby=id', row_count: rows.length, events, occurrences});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([out], {type: 'application/json'}));
  a.download = `${today}.json`;
  document.body.appendChild(a); a.click(); a.remove();
  console.log(`完成：${Object.keys(events).length} 个活动、${occurrences.length} 个场次，已下载 ${today}.json`);
})();
