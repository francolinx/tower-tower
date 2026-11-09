// Dash0 RUM: page views, errors, timings. Session replay is NOT enabled (the
// session-recording bundle is never loaded and startSessionRecording is never called).
import { init } from '/vendor/dash0.js';

const cfg = window.TOWER_CONFIG || {};
if (cfg.rum && cfg.rum.token) {
  init({
    serviceName: 'tower-web',
    serviceVersion: cfg.version,
    endpoint: { url: cfg.rum.endpoint, authToken: cfg.rum.token },
    urlAttributeScrubber: (attrs) => {
      for (const k of Object.keys(attrs)) if (k === 'url.query' || k === 'url.fragment') delete attrs[k];
      if (attrs['url.full']) attrs['url.full'] = String(attrs['url.full']).split(/[?#]/)[0];
      return attrs;
    },
  });
}
