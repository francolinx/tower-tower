// TOWER wayfinding: "Where am I" / "Take me to" pickers, step-free routing, Speak, sign-photo locate.
(() => {
  const cfg = window.TOWER_CONFIG || {};
  const sparkHttp = (cfg.sparkWs || 'wss://spark-6771.tail626e79.ts.net').replace(/^ws/, 'http');
  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  let nodes = [], byName = new Map(), byId = new Map(), lastRoute = null;
  // ?venue=theshop|saltpalace; alert links (?to=<talk room>) are Salt Palace; else the server default.
  let venue = params.get('venue') || (params.get('to') ? 'saltpalace' : '');
  const vq = () => (venue ? `venue=${encodeURIComponent(venue)}` : '');
  const whereKey = () => `tower.where.${venue || 'default'}`;

  const label = (n) => `${n.name} · ${/^\d+$/.test(String(n.level)) ? 'L' + n.level : n.level}`; // 3 -> L3; L3, ROOF as-is
  function idFromInput(el) {
    const v = el.value.trim();
    if (!v) return null;
    if (byName.has(v)) return byName.get(v);
    const low = v.toLowerCase();
    if (byId.has(low)) return low;
    for (const n of nodes) {
      if (n.name.toLowerCase() === low || (n.aliases || []).includes(low)) return n.id;
    }
    return null;
  }
  function setInput(el, id) { const n = byId.get(id); if (n) el.value = label(n); }

  async function loadNodes() {
    try {
      const r = await fetch(`/api/venue/nodes?${vq()}`);
      const j = await r.json();
      nodes = j.nodes; venue = venue || j.venue;
    } catch { return; }
    const dl = $('venue-nodes');
    dl.innerHTML = ''; byName = new Map(); byId = new Map();
    for (const n of nodes) {
      byName.set(label(n), n.id); byId.set(n.id, n);
      const o = document.createElement('option'); o.value = label(n); dl.appendChild(o);
    }
    let saved = '';
    try { saved = localStorage.getItem(whereKey()) || ''; } catch {}
    const from = params.get('from') || saved || 'north-foyer';
    setInput($('where'), from);
    const to = params.get('to') || params.get('room');
    if (to && byId.has(to)) setInput($('dest'), to);
    if (params.get('step_free') === '1') $('stepfree').checked = true;
    if (location.hash.includes('route') && to) route();
  }

  async function saveWhere() {
    const id = idFromInput($('where'));
    if (!id) return;
    try { localStorage.setItem(whereKey(), id); } catch {}
    const chat_ref = ($('chatref') && $('chatref').value.trim()) || '';
    if (chat_ref && venue === 'saltpalace') {  // alerts are about Salt Palace rooms
      fetch('/api/me/location', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ chat_ref, node: id }),
      }).catch(() => {});
    }
  }
  $('where').addEventListener('change', saveWhere);

  const mins = (s) => (s < 90 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`);
  async function route() {
    const from = idFromInput($('where')), to = idFromInput($('dest'));
    const out = $('route-steps'), sum = $('route-summary');
    if (!from || !to) { sum.textContent = 'Pick where you are and where to go.'; return; }
    sum.textContent = 'routing…'; out.innerHTML = '';
    try {
      const r = await fetch('/api/route', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ from, to, step_free: $('stepfree').checked, venue: venue || null }),
      });
      if (!r.ok) { sum.textContent = 'No route found.'; return; }
      lastRoute = await r.json();
      sum.textContent = `${mins(lastRoute.total_seconds)}${lastRoute.step_free ? ', step-free' : ''}`;
      for (const s of lastRoute.steps) {
        const li = document.createElement('li');
        li.textContent = s.text;
        out.appendChild(li);
      }
      $('speak').disabled = false;
      drawMap(lastRoute);
    } catch { sum.textContent = 'Routing unavailable.'; }
  }

  // ---- inline SVG of one level, drawn from /api/venue/graph (no map images, no external tiles)
  let graph = null, mapLevel = null;
  const lvKey = (n) => (n && n.building === 'hyatt' ? 'Hyatt' : String(n ? n.level : ''));
  const SVGNS = 'http://www.w3.org/2000/svg';
  const el = (tag, attrs, parent) => {
    const e = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  };
  async function loadGraph() {
    if (graph) return graph;
    const r = await fetch(`/api/venue/graph?${vq()}`);
    graph = await r.json();
    graph.byId = new Map(graph.nodes.map((n) => [n.id, n]));
    graph.levels = [...new Set(graph.nodes.map(lvKey))];
    return graph;
  }
  function drawTabs(route) {
    const tabs = $('level-tabs');
    tabs.innerHTML = '';
    const onRoute = new Set((route ? route.path : []).map((id) => lvKey(graph.byId.get(id))));
    for (const lv of graph.levels) {
      const b = document.createElement('button');
      b.type = 'button'; b.setAttribute('role', 'tab');
      b.textContent = (/^\d+$/.test(lv) ? 'L' + lv : lv) + (onRoute.has(lv) ? ' •' : '');
      b.setAttribute('aria-selected', String(lv === mapLevel));
      b.onclick = () => { mapLevel = lv; drawMap(lastRoute, true); };
      tabs.appendChild(b);
    }
  }
  // ---- tap a tile: destination (and route now); second tap within 1.5 s or long-press: origin
  let ripple = null, lastTap = { id: null, t: 0, prevDest: null };
  function goTo(id) {
    lastTap = { id, t: Date.now(), prevDest: idFromInput($('dest')) };
    setInput($('dest'), id);
    if (idFromInput($('where'))) route(); else drawMap(null, true);
  }
  function iAmAt(id, restoreDest) {
    if (restoreDest !== undefined) {
      if (restoreDest) setInput($('dest'), restoreDest); else $('dest').value = '';
    }
    setInput($('where'), id); saveWhere(); ripple = id;
    if (idFromInput($('dest')) && idFromInput($('dest')) !== id) route(); else drawMap(lastRoute, true);
  }
  function bindTile(g, id) {
    let pressTimer = null, longPressed = false;
    g.addEventListener('pointerdown', () => {
      longPressed = false;
      pressTimer = setTimeout(() => { longPressed = true; iAmAt(id); }, 550);
    });
    const cancel = () => clearTimeout(pressTimer);
    g.addEventListener('pointerup', cancel);
    g.addEventListener('pointerleave', cancel);
    g.addEventListener('contextmenu', (e) => e.preventDefault());
    g.addEventListener('click', () => {
      if (longPressed) { longPressed = false; return; }
      if (lastTap.id === id && Date.now() - lastTap.t < 1500) {
        const prev = lastTap.prevDest; lastTap = { id: null, t: 0, prevDest: null };
        iAmAt(id, prev);
      } else goTo(id);
    });
    g.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      if (e.shiftKey) iAmAt(id); else goTo(id);
    });
  }

  // ---- KubeCon: the official venue map as hero, pins + animated route on top
  let schematic = false, pinsData = null, photoZoom = 1;
  async function drawPhotoMap(route) {
    if (!pinsData) {
      try { const r = await fetch(`/api/venue/pins?venue=saltpalace`); if (!r.ok) throw 0; pinsData = await r.json(); }
      catch { schematic = true; return drawMap(route, true); }
    }
    const H = 100 * pinsData.aspect, pins = pinsData.pins;
    const path = route ? route.path : [];
    const wrap = document.createElement('div'); wrap.className = 'photo-map';
    const inner = document.createElement('div'); inner.className = 'photo-inner'; inner.style.width = `${photoZoom * 100}%`;
    const img = document.createElement('img');
    img.src = sparkHttp + pinsData.image; img.alt = 'KubeCon NA 2026 venue map'; img.draggable = false;
    inner.appendChild(img);
    const svg = el('svg', { viewBox: `0 0 100 ${H}`, preserveAspectRatio: 'none', class: 'photo-overlay',
      role: 'img', 'aria-label': `Venue map, pins for ${mapLevel}${route ? ', route highlighted' : ''}` });
    const at = (id) => (pins[id] ? [pins[id][0], pins[id][1] * H / 100] : null);
    const pts = path.map(at).filter(Boolean);  // route through the pinned nodes it passes
    if (pts.length > 1) {
      const d = 'M' + pts.map((p) => p.join(',')).join(' L');
      el('path', { d, class: 'route photo-route' }, svg);
      const dot = el('circle', { r: 0.9, class: 'dot' }, svg);
      if (!matchMedia('(prefers-reduced-motion: reduce)').matches) {
        el('animateMotion', { dur: `${Math.max(2, pts.length * 0.7)}s`, repeatCount: 'indefinite', path: d }, dot);
      }
    }
    const here = idFromInput($('where')), dest = idFromInput($('dest'));
    for (const [id] of Object.entries(pins)) {
      const n = graph.byId.get(id);
      const special = id === here || id === dest || (route && path.includes(id));
      if (!n || (lvKey(n) !== mapLevel && !special)) continue;  // level tabs filter pins
      const [x, y] = at(id);
      const g = el('g', { class: 'tile pin', tabindex: '0', role: 'button',
        'aria-label': `${n.name}: Enter = take me here, Shift+Enter = I am here` }, svg);
      const cls = id === here ? 'pin-dot from' : id === dest ? 'pin-dot to' : 'pin-dot';
      el('circle', { cx: x, cy: y, r: id === here || id === dest ? 1.3 : 0.8, class: cls }, g);
      if (id === here || id === dest) el('text', { x, y: y - 2, class: 'pin-label' }, g).textContent = n.short || n.name;
      bindTile(g, id);
    }
    inner.appendChild(svg); wrap.appendChild(inner);
    const zoom = document.createElement('div'); zoom.className = 'zoom-btns';
    for (const [t, f] of [['−', 1 / 1.5], ['+', 1.5]]) {
      const b = document.createElement('button'); b.type = 'button'; b.textContent = t;
      b.setAttribute('aria-label', t === '+' ? 'Zoom in' : 'Zoom out');
      b.onclick = () => { photoZoom = Math.min(4, Math.max(1, photoZoom * f)); inner.style.width = `${photoZoom * 100}%`; };
      zoom.appendChild(b);
    }
    const cap = document.createElement('p'); cap.className = 'hint map-credit'; cap.textContent = pinsData.attribution;
    const box = $('route-map'); box.innerHTML = '';
    box.appendChild(zoom); box.appendChild(wrap); box.appendChild(cap);
  }

  async function drawMap(route, keepLevel) {
    try { await loadGraph(); } catch { return; }
    const path = route ? route.path : [];
    if (!keepLevel || mapLevel === null) {
      const start = graph.byId.get(path[0]) || graph.byId.get(idFromInput($('where')) || '');
      mapLevel = start ? lvKey(start) : graph.levels[0];
    }
    drawTabs(route);
    if (venue === 'saltpalace' && !schematic) { await drawPhotoMap(route); return; }
    const nodes = graph.nodes.filter((n) => lvKey(n) === mapLevel);
    if (!nodes.length) return;
    const xs = nodes.map((n) => n.x), ys = nodes.map((n) => n.y), pad = 8;
    const minX = Math.min(...xs) - pad, maxX = Math.max(...xs) + pad;
    const minY = Math.min(...ys) - pad, maxY = Math.max(...ys) + pad;
    const P = (n) => [n.x - minX, maxY - n.y]; // north up
    const svg = el('svg', { viewBox: `0 0 ${maxX - minX} ${maxY - minY}`, role: 'img',
      'aria-label': `Map of ${mapLevel}${route ? ', route highlighted' : ''}` });
    const ids = new Set(nodes.map((n) => n.id));
    for (const e of graph.edges) {
      if (!ids.has(e.a) || !ids.has(e.b)) continue;
      const [x1, y1] = P(graph.byId.get(e.a)), [x2, y2] = P(graph.byId.get(e.b));
      el('line', { x1, y1, x2, y2, class: 'edge' }, svg);
    }
    const onRoute = new Set(path);
    for (const n of nodes) {
      const [x, y] = P(n);
      const label = (n.short || n.name).slice(0, 18);
      const w = Math.max(10, label.length * 1.3), h = 5;
      const cls = ['box', onRoute.has(n.id) ? 'on-route' : '', n.id === path[0] ? 'from' : '',
        n.id === path[path.length - 1] ? 'to' : ''].join(' ');
      const g = el('g', { class: 'tile', tabindex: '0', role: 'button',
        'aria-label': `${n.name}: Enter = take me here, Shift+Enter = I am here` }, svg);
      el('rect', { x: x - w / 2, y: y - h / 2, width: w, height: h, rx: 1, class: cls }, g);
      el('text', { x, y }, g).textContent = label;
      bindTile(g, n.id);
    }
    const pts = path.map((id) => graph.byId.get(id)).filter((n) => n && lvKey(n) === mapLevel).map(P);
    if (pts.length > 1) {
      const d = 'M' + pts.map((p) => p.join(',')).join(' L');
      el('path', { d, class: 'route' }, svg);
      const dot = el('circle', { r: 1.4, class: 'dot' }, svg);
      if (!matchMedia('(prefers-reduced-motion: reduce)').matches) {
        el('animateMotion', { dur: `${Math.max(2, pts.length * 0.8)}s`, repeatCount: 'indefinite', path: d }, dot);
      } else {
        dot.setAttribute('cx', pts[pts.length - 1][0]); dot.setAttribute('cy', pts[pts.length - 1][1]);
      }
    }
    if (ripple && ids.has(ripple)) {  // "you are here" ripple after setting the origin
      const [rx, ry] = P(graph.byId.get(ripple));
      el('circle', { cx: rx, cy: ry, r: 2, class: 'ripple' }, svg);
      ripple = null;
    }
    const box = $('route-map');
    box.innerHTML = '';
    box.appendChild(svg);
  }
  $('route-form').onsubmit = (e) => { e.preventDefault(); saveWhere(); route(); };

  $('speak').onclick = () => {
    if (!lastRoute || !('speechSynthesis' in window)) return;
    speechSynthesis.cancel();
    const text = [$('route-summary').textContent, ...lastRoute.steps.map((s, i) => `Step ${i + 1}. ${s.text}`)].join('. ');
    speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  };

  // nearest quiet room / first aid / all-gender restroom
  document.querySelectorAll('[data-nearest]').forEach((b) => {
    b.onclick = async () => {
      const from = idFromInput($('where')) || 'north-foyer';
      try {
        const r = await fetch(`/api/venue/nearest?kind=${encodeURIComponent(b.dataset.nearest)}&from=${encodeURIComponent(from)}&step_free=${$('stepfree').checked}&${vq()}`);
        if (!r.ok) return;
        const n = await r.json();
        setInput($('dest'), n.node);
        route();
      } catch {}
    };
  });

  // sign photo -> where am I (rear camera; the image is sent once and never stored)
  let camStream = null;
  async function openCamera() {
    camStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false });
    const v = $('cam');
    v.srcObject = camStream; v.hidden = false; await v.play();
    $('snap').hidden = false; $('locate-status').textContent = 'Point at the room sign, then tap Read sign.';
  }
  function closeCamera() {
    if (camStream) camStream.getTracks().forEach((t) => t.stop());
    camStream = null; $('cam').hidden = true; $('snap').hidden = true;
  }
  $('camera').onclick = () => (camStream ? closeCamera() : openCamera().catch((e) => {
    $('locate-status').textContent = 'Camera unavailable: ' + e.name + ' — pick from the list instead.';
  }));
  $('snap').onclick = async () => {
    const v = $('cam'), c = document.createElement('canvas');
    const scale = Math.min(1, 1280 / Math.max(v.videoWidth, v.videoHeight));
    c.width = Math.round(v.videoWidth * scale); c.height = Math.round(v.videoHeight * scale);
    c.getContext('2d').drawImage(v, 0, 0, c.width, c.height);
    closeCamera();
    $('locate-status').textContent = 'reading sign…';
    const blob = await new Promise((res) => c.toBlob(res, 'image/jpeg', 0.85));
    try {
      // raw JPEG body (not multipart) so the server never spools the photo to disk
      const from = idFromInput($('where'));
      const q = [vq(), from ? `from=${encodeURIComponent(from)}` : ''].filter(Boolean).join('&');
      const r = await fetch(`${sparkHttp}/api/locate?${q}`, {
        method: 'POST', headers: { 'content-type': 'image/jpeg' }, body: blob,
      });
      const j = await r.json();
      if (j.node) {
        setInput($('where'), j.node); saveWhere();
        $('locate-status').textContent = `You're at ${byId.get(j.node) ? byId.get(j.node).name : j.node} (${Math.round(j.confidence * 100)}% match).`
          + (j.matched ? `\n${j.matched}` : '');
        $('locate-status').style.whiteSpace = 'pre-line';
      } else {
        $('locate-status').textContent = 'Couldn\'t read a room sign — pick from the list.';
      }
    } catch { $('locate-status').textContent = 'Locate unavailable — pick from the list.'; }
  };

  // venue toggle: The Shop (demo) / KubeCon · Salt Palace
  const pills = document.createElement('div');
  pills.className = 'level-tabs venue-pills'; pills.setAttribute('role', 'group'); pills.setAttribute('aria-label', 'Venue');
  const VENUES = [['theshop', 'The Shop'], ['saltpalace', 'KubeCon · Salt Palace']];
  function drawPills() {
    pills.innerHTML = '';
    for (const [id, name] of VENUES) {
      const b = document.createElement('button');
      b.type = 'button'; b.textContent = name; b.setAttribute('aria-pressed', String((venue || 'theshop') === id));
      b.setAttribute('aria-selected', String((venue || 'theshop') === id));
      b.onclick = async () => {
        if ((venue || 'theshop') === id) return;
        venue = id; graph = null; mapLevel = null; lastRoute = null;
        $('where').value = ''; $('dest').value = ''; $('route-steps').innerHTML = ''; $('route-summary').textContent = '';
        params.set('venue', id); params.delete('to'); params.delete('from');
        history.replaceState(null, '', location.pathname + '?' + params.toString());
        drawPills(); await loadNodes(); drawMap(null); pickedDest = null; buildPicker(); renderTalks();
      };
      pills.appendChild(b);
    }
    if ((venue || 'theshop') === 'saltpalace') {
      const sb = document.createElement('button');
      sb.type = 'button'; sb.textContent = schematic ? 'Venue map' : 'Schematic';
      sb.onclick = () => { schematic = !schematic; drawPills(); drawMap(lastRoute, true); };
      pills.appendChild(sb);
    }
  }
  $('level-tabs').before(pills);
  drawPills();
  // ---- destination picker: accordion by level, chips per room/booth/POI; the text box filters
  const PICK_KINDS = new Set(['room', 'booth', 'poi']);
  let pickedDest = null;
  const openKey = () => `tower.pickerLevel.${venue || 'default'}`;
  function getOpen() { try { return localStorage.getItem(openKey()); } catch { return null; } }
  function setOpen(lv) { try { lv ? localStorage.setItem(openKey(), lv) : localStorage.removeItem(openKey()); } catch {} }
  async function buildPicker() {
    const box = $('dest-picker');
    try { await loadGraph(); } catch { box.innerHTML = ''; return; }
    const q = $('dest').value.trim().toLowerCase();
    const filtering = q.length > 0 && !idFromInput($('dest'));
    const open = getOpen();
    box.innerHTML = '';
    for (const lv of graph.levels) {
      let items = graph.nodes.filter((n) => lvKey(n) === lv && PICK_KINDS.has(n.kind));
      if (filtering) items = items.filter((n) => (n.name + ' ' + (n.short || '') + ' ' + (n.aliases || []).join(' ')).toLowerCase().includes(q));
      if (!items.length) continue;
      const expanded = filtering || open === lv;
      const sec = document.createElement('div'); sec.className = 'pick-level';
      const h = document.createElement('button');
      h.type = 'button'; h.className = 'pick-head'; h.setAttribute('aria-expanded', String(expanded));
      h.textContent = `${/^\d+$/.test(lv) ? 'L' + lv : lv} · ${items.length}`;
      h.onclick = () => { setOpen(open === lv ? null : lv); buildPicker(); };
      sec.appendChild(h);
      if (expanded) {  // chips only for open levels: Salt Palace stays fast
        const chips = document.createElement('div'); chips.className = 'pick-chips';
        for (const n of items.sort((a, b) => (a.short || a.name).localeCompare(b.short || b.name))) {
          const c = document.createElement('button');
          c.type = 'button'; c.className = 'chip'; c.textContent = n.short || n.name; c.title = n.name;
          c.setAttribute('aria-pressed', String(n.id === pickedDest));
          c.onclick = () => {
            pickedDest = n.id; setOpen(lv); setInput($('dest'), n.id);
            mapLevel = null;  // route() redraws on the route's start level
            if (idFromInput($('where'))) route(); else { $('route-summary').textContent = 'Pick where you are first.'; }
            buildPicker();
          };
          chips.appendChild(c);
        }
        sec.appendChild(chips);
      }
      box.appendChild(sec);
    }
  }
  $('dest').addEventListener('input', () => buildPicker());

  // ---- KubeCon talks: day tabs, time-grouped list, tap = go to that room; slides & moments per talk
  const DAYS = [['2026-11-09', 'Mon 9'], ['2026-11-10', 'Tue 10'], ['2026-11-11', 'Wed 11'], ['2026-11-12', 'Thu 12']];
  const todayMT = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Denver' }).format(new Date());
  let talkDay = DAYS.some(([d]) => d === todayMT) ? todayMT : DAYS[0][0];
  const talkCache = new Map();
  const txt = (tag, cls, t) => { const e = document.createElement(tag); if (cls) e.className = cls; e.textContent = t; return e; };
  async function renderTalks() {
    const panel = $('talks');
    if (venue !== 'saltpalace') { panel.hidden = true; return; }
    panel.hidden = false;
    const days = $('talk-days'); days.innerHTML = '';
    for (const [d, name] of DAYS) {
      const b = txt('button', '', name); b.type = 'button'; b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', String(d === talkDay));
      b.onclick = () => { talkDay = d; renderTalks(); };
      days.appendChild(b);
    }
    const list = $('talk-list'); list.textContent = 'loading talks…';
    let talks = talkCache.get(talkDay);
    if (!talks) {
      try { const r = await fetch(`/api/talks?day=${talkDay}`); talks = (await r.json()).talks; talkCache.set(talkDay, talks); }
      catch { list.textContent = 'schedule unavailable'; return; }
    }
    list.innerHTML = '';
    let slot = null;
    for (const t of talks) {
      if (t.starts_mt !== slot) { slot = t.starts_mt; list.appendChild(txt('h4', 'talk-slot', slot)); }
      const b = document.createElement('button'); b.type = 'button'; b.className = 'talk';
      b.appendChild(txt('span', 'talk-title', t.title));
      b.appendChild(txt('span', 'chip talk-room', t.room_name || t.room));
      b.onclick = () => openTalk(t);
      list.appendChild(b);
    }
    if (!talks.length) list.textContent = 'No talks that day.';
  }
  function openTalk(t) {
    const box = $('talk-detail'); box.hidden = false; box.innerHTML = '';
    box.appendChild(txt('strong', '', t.title));
    box.appendChild(txt('p', 'hint', `${t.starts_mt}–${t.ends_mt} MT · ${t.room_name || t.room}${(t.speakers || []).length ? ' · ' + t.speakers.join(', ') : ''}`));
    const sm = txt('button', 'chip', 'Slides & moments'); sm.type = 'button';
    const out = document.createElement('ul'); out.className = 'results';
    sm.onclick = async () => {
      out.innerHTML = '<li>searching…</li>';
      try {
        const r = await fetch('/api/search', { method: 'POST', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ q: t.title.slice(0, 200), talk_id: t.talk_id }) });
        const { hits = [], slides = [] } = await r.json();
        out.innerHTML = hits.length || slides.length ? '' : '<li>No slides or moments for this talk yet.</li>';
        for (const p of slides) {
          const li = document.createElement('li'); const a = document.createElement('a');
          a.href = `${p.url}#page=${p.page}`; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.className = 'slide-hit';
          a.textContent = `slides p.${p.page}: ${p.text.slice(0, 120)}…`; li.appendChild(a); out.appendChild(li);
        }
        for (const h of hits) { const li = txt('li', '', `${Math.floor(h.t_start / 60)}:${String(Math.floor(h.t_start % 60)).padStart(2, '0')} ${h.text}`); out.appendChild(li); }
      } catch { out.innerHTML = '<li>search unavailable</li>'; }
    };
    box.appendChild(sm); box.appendChild(out);
    if (byId.has(t.room)) {
      setInput($('dest'), t.room); pickedDest = t.room; mapLevel = null;
      if (idFromInput($('where'))) route(); else $('route-summary').textContent = 'Pick where you are to get a route.';
    }
    box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
  loadNodes().then(() => { drawPills(); drawMap(null); buildPicker(); renderTalks(); });
})();
