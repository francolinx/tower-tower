// TOWER gateway: serves the caption page and proxies /api/* to the Spark (tower-core).
// Keeps the deployment contract: listens on $PORT (8080), serves /healthz and /readyz.
// Privacy: request/response bodies are never logged (they can carry captions and interests).
const path = require('node:path');
const express = require('express');

const port = Number(process.env.PORT || 8080);
const version = process.env.APP_VERSION || 'dev';
const sparkUrl = (process.env.SPARK_URL || 'https://spark-6771.tail626e79.ts.net').replace(/\/$/, '');
const sparkWs = sparkUrl.replace(/^http/, 'ws');
const rumToken = process.env.DASH0_RUM_TOKEN || '';
const rumEndpoint = process.env.DASH0_RUM_ENDPOINT || 'https://ingress.us-west-2.aws.dash0.com';

const app = express();
app.disable('x-powered-by');

app.get(['/healthz', '/readyz'], (_req, res) => res.type('text/plain').send('ok\n'));

app.get('/version', (_req, res) => res.json({ version }));

// Runtime config for the page. The RUM token is a browser (ingest-only) token by design.
app.get('/config.js', (_req, res) => {
  const cfg = {
    version,
    sparkWs,
    rum: rumToken ? { token: rumToken, endpoint: rumEndpoint } : null,
  };
  res.type('application/javascript').set('Cache-Control', 'no-store');
  res.send(`window.TOWER_CONFIG = ${JSON.stringify(cfg)};\n`);
});

app.use(express.json({ limit: '16kb' }));

// /api/* -> SPARK_URL/api/*
app.all('/api/{*rest}', async (req, res) => {
  const target = sparkUrl + req.originalUrl;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 8000);
  try {
    const init = { method: req.method, signal: ctrl.signal, headers: { accept: 'application/json' } };
    if (req.method !== 'GET' && req.method !== 'HEAD') {
      init.headers['content-type'] = 'application/json';
      init.body = JSON.stringify(req.body ?? {});
    }
    const r = await fetch(target, init);
    const body = await r.text();
    res.status(r.status).type(r.headers.get('content-type') || 'application/json').send(body);
  } catch (err) {
    console.warn(`proxy error path=${req.path} type=${err.name}`);
    res.status(502).json({ error: 'spark unavailable' });
  } finally {
    clearTimeout(timer);
  }
});

app.get('/vendor/dash0.js', (_req, res) =>
  res.sendFile(path.join(__dirname, 'node_modules/@dash0/sdk-web/dist/dash0.js')),
);

app.use(express.static(path.join(__dirname, 'public'), { maxAge: '5m' }));

const server = app.listen(port, () => console.log(`listening on :${port}, version ${version}`));

// Exit cleanly when Kubernetes stops the pod, so rollouts don't drop requests.
process.on('SIGTERM', () => server.close(() => process.exit(0)));
