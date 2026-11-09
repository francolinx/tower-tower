// TOWER wayfinding: "Where am I" / "Take me to" pickers, step-free routing, Speak.
(() => {
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

  loadNodes();
})();
