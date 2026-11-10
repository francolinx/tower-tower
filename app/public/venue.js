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
    dl.innerHTML = '';
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
    graph.levels = [...new Set(graph.nodes.map((n) => String(n.level)))];
    return graph;
  }
  function drawTabs(route) {
    const tabs = $('level-tabs');
    tabs.innerHTML = '';
    const onRoute = new Set((route ? route.path : []).map((id) => String(graph.byId.get(id)?.level)));
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

  async function drawMap(route, keepLevel) {
    try { await loadGraph(); } catch { return; }
    const path = route ? route.path : [];
    if (!keepLevel || mapLevel === null) {
      const start = graph.byId.get(path[0]) || graph.byId.get(idFromInput($('where')) || '');
      mapLevel = start ? String(start.level) : graph.levels[0];
    }
    drawTabs(route);
    const nodes = graph.nodes.filter((n) => String(n.level) === mapLevel);
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
    const pts = path.map((id) => graph.byId.get(id)).filter((n) => n && String(n.level) === mapLevel).map(P);
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
        $('locate-status').textContent = `You're at ${byId.get(j.node) ? byId.get(j.node).name : j.node} (${Math.round(j.confidence * 100)}% match).`;
      } else {
        $('locate-status').textContent = 'Couldn\'t read a room sign — pick from the list.';
      }
    } catch { $('locate-status').textContent = 'Locate unavailable — pick from the list.'; }
  };

  loadNodes().then(() => drawMap(null));
})();
