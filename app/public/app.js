// TOWER caption page. Captions come straight from the Spark over WebSocket; /api/* goes via the gateway.
(() => {
  const cfg = window.TOWER_CONFIG || { sparkWs: 'wss://spark-6771.tail626e79.ts.net' };
  const $ = (id) => document.getElementById(id);
  const roomEl = $('room'), statusEl = $('status'), capText = $('captext');
  const MAX_CHARS = 400;
  let capWs = null, micWs = null, micCtx = null, micStream = null, lang = 'orig', retry = 0;

  $('ver').textContent = 'v' + (cfg.version || 'dev');
  const params = new URLSearchParams(location.search);
  if (params.get('room')) roomEl.value = params.get('room');

  // ---- text size (user-resizable, persisted per device)
  const sizeKey = 'tower.capSize';
  let size = 34;
  try { size = Number(localStorage.getItem(sizeKey)) || 34; } catch {}
  const applySize = () => document.documentElement.style.setProperty('--cap-size', size + 'px');
  applySize();
  const resize = (d) => { size = Math.max(28, Math.min(72, size + d)); applySize();
    try { localStorage.setItem(sizeKey, String(size)); } catch {} };
  $('smaller').onclick = () => resize(-4);
  $('bigger').onclick = () => resize(4);

  // ---- live captions
  const room = () => roomEl.value.trim().toLowerCase().replace(/[^a-z0-9-]/g, '-') || 'main';
  function setStatus(text, live) { statusEl.textContent = text; statusEl.classList.toggle('live', !!live); }
  function appendCaption(t) {
    let s = (capText.textContent ? capText.textContent + ' ' : '') + t;
    if (s.length > MAX_CHARS) s = s.slice(s.length - MAX_CHARS);
    capText.textContent = s;
  }
  function connectCaptions() {
    if (capWs) { capWs.onclose = null; capWs.close(); }
    capText.textContent = '';
    const url = `${cfg.sparkWs}/ws/captions?room=${encodeURIComponent(room())}&lang=${lang}`;
    capWs = new WebSocket(url);
    capWs.onopen = () => { retry = 0; setStatus(`connected · ${room()}`, true); };
    capWs.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.type === 'caption') appendCaption(m.text);
    };
    capWs.onclose = () => {
      setStatus('reconnecting…');
      setTimeout(connectCaptions, Math.min(10000, 500 * 2 ** retry++));
    };
  }
  const ping = setInterval(() => capWs && capWs.readyState === 1 && capWs.send('ping'), 20000);
  roomEl.addEventListener('change', () => { connectCaptions(); if (micWs) { stopMic(); } });

  async function loadRooms() {
    try {
      const r = await fetch('/api/rooms');
      const { rooms } = await r.json();
      $('rooms').innerHTML = '';
      for (const x of rooms) {
        const o = document.createElement('option');
        o.value = x.room; o.label = x.title ? `${x.room} · ${x.title}` : x.room;
        $('rooms').appendChild(o);
      }
    } catch {}
  }

  // ---- language toggle
  $('lang').onclick = () => {
    lang = lang === 'orig' ? 'en' : 'orig';
    $('lang').setAttribute('aria-pressed', String(lang === 'en'));
    $('lang').textContent = lang === 'en' ? 'English' : 'Original';
    connectCaptions();
  };

  // ---- mic mode: this device becomes the room's audio source
  function roomKey() {
    let k = '';
    try { k = localStorage.getItem('tower.audioKey') || ''; } catch {}
    if (!k) {
      k = (prompt('Room device key (from the TOWER operator):') || '').trim();
      if (k) { try { localStorage.setItem('tower.audioKey', k); } catch {} }
    }
    return k;
  }
  async function startMic() {
    const key = roomKey();
    if (!key) throw { name: 'NoKey' };
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    micCtx = new AudioContext({ sampleRate: 16000 });
    await micCtx.audioWorklet.addModule('/pcm-worklet.js');
    const src = micCtx.createMediaStreamSource(micStream);
    const node = new AudioWorkletNode(micCtx, 'pcm-worklet');
    micWs = new WebSocket(`${cfg.sparkWs}/ws/audio?room=${encodeURIComponent(room())}&key=${encodeURIComponent(key)}`);
    micWs.binaryType = 'arraybuffer';
    node.port.onmessage = (ev) => { if (micWs && micWs.readyState === 1) micWs.send(ev.data); };
    src.connect(node);
    micWs.onclose = (ev) => {
      if (ev.code === 4401) { try { localStorage.removeItem('tower.audioKey'); } catch {} setStatus('wrong room key'); }
      if (ev.code === 4429) setStatus('room already has 2 audio sources');
      stopMic();
    };
    $('mic').setAttribute('aria-pressed', 'true');
    $('mic').textContent = '■ Stop captioning';
  }
  function stopMic() {
    if (micWs) { micWs.onclose = null; micWs.close(); micWs = null; }
    if (micStream) { micStream.getTracks().forEach((t) => t.stop()); micStream = null; }
    if (micCtx) { micCtx.close(); micCtx = null; }
    $('mic').setAttribute('aria-pressed', 'false');
    $('mic').textContent = '🎙 Caption this room';
  }
  $('mic').onclick = () => (micWs ? stopMic() : startMic().catch((e) => {
    stopMic(); setStatus('mic unavailable: ' + e.name);
  }));

  // ---- search + jump to moment
  const fmt = (t) => { t = Math.floor(t); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`; };
  async function showMoment(talkId, t) {
    const box = $('moment');
    box.hidden = false; box.textContent = 'loading…';
    try {
      const r = await fetch(`/api/moments?talk_id=${encodeURIComponent(talkId)}&t=${t}`);
      const { moments, talk } = await r.json();
      box.textContent = '';
      const h = document.createElement('p');
      h.className = 'hint';
      h.textContent = `${talk && talk.title ? talk.title + ' · ' : ''}${moments[0] ? moments[0].room : ''} · at ${fmt(t)}`;
      box.appendChild(h);
      for (const m of moments) {
        const el = document.createElement(Math.abs(m.t_start - t) < 0.01 ? 'mark' : 'span');
        el.textContent = m.text + ' ';
        box.appendChild(el);
      }
      box.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch { box.textContent = 'moment unavailable'; }
  }
  $('search-form').onsubmit = async (e) => {
    e.preventDefault();
    const q = $('q').value.trim();
    if (!q) return;
    const list = $('results');
    list.innerHTML = '<li>searching…</li>';
    try {
      const r = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
      const { hits } = await r.json();
      list.innerHTML = hits.length ? '' : '<li>no moments yet</li>';
      for (const h of hits) {
        const li = document.createElement('li');
        const b = document.createElement('button');
        const meta = document.createElement('span');
        meta.className = 'meta';
        meta.textContent = `${h.room} · ${h.talk_title || h.talk_id} · ${fmt(h.t_start)}`;
        b.appendChild(meta);
        b.appendChild(document.createTextNode(h.text));
        b.onclick = () => showMoment(h.talk_id, h.t_start);
        li.appendChild(b); list.appendChild(li);
      }
    } catch { list.innerHTML = '<li>search unavailable</li>'; }
  };
  // deep link from Telegram alerts: /#moment=<talk_id>@<t>
  const deep = /moment=([^@&]+)@([\d.]+)/.exec(location.hash);
  if (deep) showMoment(decodeURIComponent(deep[1]), Number(deep[2]));

  // ---- interests
  $('interest-form').onsubmit = async (e) => {
    e.preventDefault();
    const query = $('interest').value.trim(), chat_ref = $('chatref').value.trim();
    if (!query || !chat_ref) { $('interest-status').textContent = 'Need a topic and your Telegram code.'; return; }
    try {
      const r = await fetch('/api/interests', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ chat_ref, query }),
      });
      $('interest-status').textContent = r.ok ? 'Saved. We\'ll ping you on Telegram.' : 'Could not save.';
      if (r.ok) $('interest').value = '';
    } catch { $('interest-status').textContent = 'Could not save.'; }
  };
  if (cfg.tgBot) $('botlink').href = `https://t.me/${cfg.tgBot}`;

  connectCaptions();
  loadRooms();
  setInterval(loadRooms, 30000);
  window.addEventListener('beforeunload', () => { clearInterval(ping); stopMic(); });
})();
