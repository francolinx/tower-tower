// TOWER wayfinding: "Where am I" / "Take me to" pickers, step-free routing, Speak, sign-photo locate.
(() => {
  const cfg = window.TOWER_CONFIG || {};
  const sparkHttp = (cfg.sparkWs || 'wss://spark-6771.tail626e79.ts.net').replace(/^ws/, 'http');
  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  let nodes = [], byName = new Map(), byId = new Map(), lastRoute = null;

  const label = (n) => `${n.name} · L${n.level}`;
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
      const r = await fetch('/api/venue/nodes');
      nodes = (await r.json()).nodes;
    } catch { return; }
    const dl = $('venue-nodes');
    dl.innerHTML = '';
    for (const n of nodes) {
      byName.set(label(n), n.id); byId.set(n.id, n);
      const o = document.createElement('option'); o.value = label(n); dl.appendChild(o);
    }
    let saved = '';
    try { saved = localStorage.getItem('tower.where') || ''; } catch {}
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
    try { localStorage.setItem('tower.where', id); } catch {}
    const chat_ref = ($('chatref') && $('chatref').value.trim()) || '';
    if (chat_ref) {
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
        body: JSON.stringify({ from, to, step_free: $('stepfree').checked }),
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
    } catch { sum.textContent = 'Routing unavailable.'; }
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
        const r = await fetch(`/api/venue/nearest?kind=${encodeURIComponent(b.dataset.nearest)}&from=${encodeURIComponent(from)}&step_free=${$('stepfree').checked}`);
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
      const r = await fetch(`${sparkHttp}/api/locate`, {
        method: 'POST', headers: { 'content-type': blob.type }, body: blob,
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

  loadNodes();
})();
