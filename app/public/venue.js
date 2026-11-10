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
      $('speak').disabled = false;
      navStart(lastRoute);
    } catch { sum.textContent = 'Routing unavailable.'; }
  }

  // ---- turn-by-turn: nav card, step list, map follow
  const nav = { route: null, steps: [], slices: [], idx: -1, overview: false };
  const reduceMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const navActive = (route) => !!route && nav.route === route && nav.idx >= 0;
  const navSlice = () => (nav.slices[nav.idx] || []);
  const GLYPHS = {
    straight: '<path d="M24 42V8M13 19L24 8l11 11"/>',
    left: '<path d="M32 42V24a8 8 0 0 0-8-8H10M17 9l-7 7 7 7"/>',
    right: '<path d="M16 42V24a8 8 0 0 1 8-8h14M31 9l7 7-7 7"/>',
    up: '<path d="M6 42h8v-7h8v-7h8v-7h8"/><path d="M38 4v11M33 9l5-5 5 5"/>',
    down: '<path d="M6 21h8v7h8v7h8v7h8"/><path d="M10 4v11M5 10l5 5 5-5"/>',
    elevator: '<rect x="11" y="5" width="26" height="38" rx="3"/><path d="M24 12l6 7H18z M24 36l6-7H18z" fill="currentColor"/>',
    escalator: '<path d="M5 38h9l20-24h9"/><path d="M36 4h7v7"/>',
    arrive: '<path d="M14 44V5"/><path d="M14 7h22l-6 7 6 7H14z" fill="currentColor"/>',
  };
  function glyph(st, size) {
    const k = st.kind === 'arrive' ? 'arrive' : st.kind === 'elevator' ? 'elevator'
      : st.kind === 'escalator' ? 'escalator' : (st.turn || 'straight');
    return `<svg viewBox="0 0 48 48" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${GLYPHS[k] || GLYPHS.straight}</svg>`;
  }
  const lvName = (l) => (/^\d+$/.test(String(l)) ? 'L' + l : String(l));
  function navStart(route) {
    nav.route = route; nav.steps = route.steps || []; nav.overview = false;
    // path slice per step: from_node -> node, walking forward through route.path (corridors included)
    nav.slices = []; let k = 0;
    for (const st of nav.steps) {
      const i = route.path.indexOf(st.from_node, k);
      const j = route.path.indexOf(st.node, i < 0 ? k : i);
      if (i >= 0 && j >= i) { nav.slices.push(route.path.slice(i, j + 1)); k = j; } else nav.slices.push([st.node]);
    }
    $('nav').hidden = false;
    renderStepList();
    const want = Number(params.get('step')) || 1;  // ?step=N opens on that step (default 1)
    params.delete('step');
    navGo(want - 1);
  }
  function navGo(i) {
    if (!nav.steps.length) return;
    nav.idx = Math.max(0, Math.min(nav.steps.length - 1, i));
    const st = nav.steps[nav.idx], n = graph && graph.byId.get(st.node);
    if (n) mapLevel = lvKey(n);
    renderCard();
    drawMap(nav.route, true);
  }
  function renderCard() {
    const st = nav.steps[nav.idx], total = nav.steps.length;
    const left = nav.steps.slice(nav.idx).reduce((a, s) => a + (s.seconds || 0), 0);
    $('nav-glyph').innerHTML = glyph(st, 72);
    $('nav-title').textContent = st.title || st.text;
    $('nav-sub').textContent = `${st.seconds || 0} s · Floor ${lvName(st.level)} · ${st.detail || ''}`;
    $('nav-prog').textContent = `Step ${nav.idx + 1} of ${total} · ${mins(left)} left`;
    $('nav-bar-fill').style.width = `${Math.round(((nav.idx + 1) / total) * 100)}%`;
    $('nav-prev').disabled = nav.idx === 0;
    const last = nav.idx === total - 1;
    $('nav-next').textContent = last ? 'Done ✓' : 'Next ▶';
    $('nav-next').setAttribute('aria-label', last ? 'Finish navigation' : 'Next step');
    $('nav-overview').setAttribute('aria-pressed', String(nav.overview));
    document.querySelectorAll('#nav-steps li').forEach((li, k) => li.classList.toggle('active', k === nav.idx));
  }
  function renderStepList() {
    const ol = $('nav-steps'); ol.innerHTML = '';
    nav.steps.forEach((st, k) => {
      const li = document.createElement('li');
      const b = document.createElement('button'); b.type = 'button';
      b.innerHTML = glyph(st, 22);
      b.appendChild(Object.assign(document.createElement('span'), { className: 'ns-title', textContent: st.title || st.text }));
      b.appendChild(Object.assign(document.createElement('span'), { className: 'ns-secs', textContent: st.seconds ? `${st.seconds} s` : '' }));
      b.onclick = () => navGo(k);
      li.appendChild(b); ol.appendChild(li);
    });
  }
  function speakStep() {
    if (!('speechSynthesis' in window) || nav.idx < 0) return;
    const st = nav.steps[nav.idx];
    speechSynthesis.cancel();
    speechSynthesis.speak(new SpeechSynthesisUtterance(`${st.title}. ${st.detail || ''}`));
  }
  function navNext() {
    if (nav.idx >= nav.steps.length - 1) { nav.idx = -1; $('nav').hidden = true; drawMap(nav.route, true); return; }
    navGo(nav.idx + 1);
    if ($('nav-auto').checked) speakStep();
  }
  $('nav-next').onclick = navNext;
  $('nav-prev').onclick = () => navGo(nav.idx - 1);
  $('nav-start').onclick = () => { if (nav.route) { $('nav').hidden = false; navGo(0); if ($('nav-auto').checked) speakStep(); } };
  $('nav-overview').onclick = () => { nav.overview = !nav.overview; renderCard(); drawMap(nav.route, true); };
  document.addEventListener('keydown', (e) => {
    if ($('nav').hidden || nav.idx < 0 || /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '')) return;
    if (e.key === 'ArrowRight') { e.preventDefault(); navNext(); }
    if (e.key === 'ArrowLeft') { e.preventDefault(); navGo(nav.idx - 1); }
  });
  (() => {  // swipe on the card: left = next, right = prev
    let x0 = null;
    $('nav').addEventListener('pointerdown', (e) => { x0 = e.clientX; });
    $('nav').addEventListener('pointerup', (e) => {
      if (x0 === null) return;
      const dx = e.clientX - x0; x0 = null;
      if (Math.abs(dx) > 50) { if (dx < 0) navNext(); else navGo(nav.idx - 1); }
    });
  })();
  // full route dimmed; active segment bright with the moving dot
  function drawRouteLayers(svg, pts, active, r, extra) {
    const line = (p, cls) => { if (p.length < 2) return null; const d = 'M' + p.map((q) => q.join(',')).join(' L'); el('path', { d, class: cls }, svg); return d; };
    if (!active) {
      const d = line(pts, `route ${extra}`);
      if (d) { const dot = el('circle', { r, class: 'dot' }, svg); if (!reduceMotion()) el('animateMotion', { dur: `${Math.max(2, pts.length * 0.8)}s`, repeatCount: 'indefinite', path: d }, dot); }
      return;
    }
    line(pts, `route dim ${extra}`);
    if (!active.length) return;
    const d = line(active, `route active ${extra}`);
    const dot = el('circle', { r, class: 'dot' }, svg);
    if (d && !reduceMotion()) el('animateMotion', { dur: `${Math.max(1.5, active.length * 0.6)}s`, repeatCount: 'indefinite', path: d }, dot);
    else if (active.length) { dot.setAttribute('cx', active[active.length - 1][0]); dot.setAttribute('cy', active[active.length - 1][1]); }
  }
  // zoom the schematic to the active segment by animating viewBox (rAF, ease-out, ~400 ms)
  let curVB = null, curVBLevel = null;
  function fitBox(pts, bounds, minSpan) {
    if (!pts || !pts.length || nav.overview) return bounds;
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    let w = Math.max(x1 - x0, minSpan), h = Math.max(y1 - y0, minSpan * 0.75);
    w *= 1.5; h *= 1.5;  // ~25% padding each side
    const ratio = bounds[2] / bounds[3];
    if (w / h < ratio) w = h * ratio; else h = w / ratio;
    w = Math.min(w, bounds[2]); h = Math.min(h, bounds[3]);
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const x = Math.max(bounds[0], Math.min(bounds[0] + bounds[2] - w, cx - w / 2));
    const y = Math.max(bounds[1], Math.min(bounds[1] + bounds[3] - h, cy - h / 2));
    return [x, y, w, h];
  }
  function svgFollow(svg, active, bounds) {
    const target = active ? fitBox(active, bounds, bounds[2] * 0.3) : bounds;
    const from = curVB && curVBLevel === mapLevel ? curVB : bounds;
    curVB = target; curVBLevel = mapLevel;
    if (reduceMotion()) { svg.setAttribute('viewBox', target.join(' ')); return; }
    const t0 = performance.now();
    const step = (t) => {
      const k = Math.min(1, (t - t0) / 400), e = 1 - Math.pow(1 - k, 3);
      svg.setAttribute('viewBox', from.map((v, i) => v + (target[i] - v) * e).join(' '));
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  // photo map: scale/translate the image+overlay together (CSS transition, ~400 ms)
  function photoFollow(inner, active, H) {
    inner.style.transformOrigin = '0 0';
    if (!active || !active.length || nav.overview) { inner.style.transform = ''; inner.parentElement.style.overflow = ''; return; }
    const [x, y, w, h] = fitBox(active.map((p) => [p[0], p[1] / H * 100]), [0, 0, 100, 100], 18);
    const sc = Math.max(1, Math.min(4, 100 / Math.max(w, h)));
    const cx = x + w / 2, cy = y + h / 2;
    const tx = Math.max(100 - 100 * sc, Math.min(0, 50 - cx * sc)), ty = Math.max(100 - 100 * sc, Math.min(0, 50 - cy * sc));
    inner.style.transition = reduceMotion() ? '' : 'transform 400ms cubic-bezier(.2,.7,.3,1)';
    inner.style.transform = `translate(${tx}%, ${ty}%) scale(${sc})`;
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
    const wps = pinsData.waypoints || {};
    const at = (id) => { const p = pins[id] || wps[id]; return p ? [p[0], p[1] * H / 100] : null; };
    const pts = path.map(at).filter(Boolean);  // route through the pinned nodes it passes
    const active = navActive(route) ? navSlice().map(at).filter(Boolean) : null;
    drawRouteLayers(svg, pts, active, 0.9, 'photo-route');
    const navStep = navActive(route) ? nav.steps[nav.idx] : null;
    const here = navStep ? navStep.from_node : idFromInput($('where')), dest = idFromInput($('dest'));
    for (const [id] of Object.entries(pins)) {
      const n = graph.byId.get(id);
      const special = id === here || id === dest || (route && path.includes(id));
      if (!n || (lvKey(n) !== mapLevel && !special)) continue;  // level tabs filter pins
      const [x, y] = at(id);
      const g = el('g', { class: 'tile pin', tabindex: '0', role: 'button',
        'aria-label': `${n.name}: Enter = take me here, Shift+Enter = I am here` }, svg);
      const cls = id === here ? 'pin-dot from' : id === dest ? 'pin-dot to' : 'pin-dot';
      el('circle', { cx: x, cy: y, r: id === here || id === dest ? 1.3 : 0.8, class: cls }, g);
      if (id === here || id === dest) el('text', { x, y: y - 2.2, class: 'pin-label' }, g).textContent = n.short || n.name;
      if (id === here) el('circle', { cx: x, cy: y, r: 1.3, class: 'pulse' }, g);  // you are here
      if (id === dest) {  // destination flag
        el('line', { x1: x, y1: y, x2: x, y2: y - 4, class: 'flag-pole' }, g);
        el('path', { d: `M${x},${y - 4} l2.6,0.9 l-2.6,0.9 z`, class: 'flag' }, g);
      }
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
    box.appendChild(zoom); box.appendChild(wrap);
    void inner.offsetWidth;
    photoFollow(inner, active, H);
    box.appendChild(cap);
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
      if (n.kind === 'corridor') continue;
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
    const onLv = (id) => { const n = graph.byId.get(id); return n && lvKey(n) === mapLevel ? n : null; };
    const pts = path.map(onLv).filter(Boolean).map(P);
    let active = null;
    if (navActive(route)) {
      const st = nav.steps[nav.idx];
      active = navSlice().map(onLv).filter(Boolean).map(P);
      const from = onLv(st.from_node), dst = onLv(path[path.length - 1]);
      if (from) el('circle', { cx: P(from)[0], cy: P(from)[1], r: 2, class: 'pulse' }, svg);
      if (dst) {
        const [fx, fy] = P(dst);
        el('line', { x1: fx, y1: fy, x2: fx, y2: fy - 6, class: 'flag-pole' }, svg);
        el('path', { d: `M${fx},${fy - 6} l4,1.4 l-4,1.4 z`, class: 'flag' }, svg);
      }
    }
    drawRouteLayers(svg, pts, active, 1.4, '');
    if (ripple && ids.has(ripple)) {  // "you are here" ripple after setting the origin
      const [rx, ry] = P(graph.byId.get(ripple));
      el('circle', { cx: rx, cy: ry, r: 2, class: 'ripple' }, svg);
      ripple = null;
    }
    const box = $('route-map');
    box.innerHTML = '';
    box.appendChild(svg);
    svgFollow(svg, active, [0, 0, maxX - minX, maxY - minY]);
  }
  $('route-form').onsubmit = (e) => { e.preventDefault(); saveWhere(); route(); };

  $('speak').onclick = () => {
    if (!lastRoute || !('speechSynthesis' in window)) return;
    if (navActive(lastRoute)) { speakStep(); return; }
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
        venue = id; graph = null; mapLevel = null; lastRoute = null; nav.idx = -1; nav.route = null; $('nav').hidden = true;
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
