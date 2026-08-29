'use strict';

// The phone talks HTTP to this process; this process talks the TV's protocol.
// The indirection is the whole point: a browser can't open a `wss` connection
// to a self-signed certificate, and can't keep the pairing token, so the page
// stays dumb and everything that needs to be careful happens here.

const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

const configStore = require('./lib/config');
const { SamsungTv, fetchDeviceInfo } = require('./lib/tv');
const { discover } = require('./lib/discover');
const { wake } = require('./lib/wol');
const { GROUPS, APPS, isKnownKey } = require('./lib/keys');

const PUBLIC_DIR = path.join(__dirname, 'public');
const MAX_BODY_BYTES = 64 * 1024;
const POWER_CACHE_MS = 4_000;

const CONTENT_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
};

function createApp({ configFile = configStore.DEFAULT_PATH } = {}) {
  let config = configStore.load(configFile);
  const tv = new SamsungTv({
    host: config.host,
    port: config.port,
    secure: config.secure,
    name: config.name,
    token: config.token,
  });

  const listeners = new Set();
  let powerCache = { at: 0, value: null };

  // A token only arrives once, on the connection the user approves. Losing it
  // means another prompt on the TV, so write it out the moment it shows up.
  tv.on('token', (token) => {
    config = configStore.save({ ...config, token }, configFile);
    console.log('[remote] paired with the TV; token saved');
  });

  tv.on('state', (event) => {
    broadcast({ type: 'state', ...event });
  });

  function broadcast(payload) {
    const frame = `data: ${JSON.stringify(payload)}\n\n`;
    for (const response of listeners) {
      response.write(frame);
    }
  }

  async function powerState() {
    if (!config.host) return null;
    const now = Date.now();
    if (now - powerCache.at < POWER_CACHE_MS) return powerCache.value;
    const info = await fetchDeviceInfo(config.host, 1_500);
    const value = info ? (info.device?.PowerState ?? 'on') : 'unreachable';
    powerCache = { at: Date.now(), value };
    return value;
  }

  const routes = {
    'GET /api/state': async () => ({
      configured: Boolean(config.host),
      host: config.host,
      mac: config.mac,
      name: config.name,
      paired: Boolean(config.token),
      connection: tv.state,
      error: tv.lastError,
      power: await powerState(),
    }),

    'GET /api/keys': async () => ({ groups: GROUPS, apps: APPS }),

    'GET /api/discover': async () => ({ found: await discover({ probeTimeoutMs: 1_500 }) }),

    'POST /api/config': async (body) => {
      const host = typeof body.host === 'string' ? body.host.trim() : '';
      if (!/^[a-zA-Z0-9.\-]{1,253}$/.test(host)) {
        throw badRequest('that does not look like an IP address or hostname');
      }
      const mac = typeof body.mac === 'string' && body.mac.trim() ? body.mac.trim() : null;
      // A different TV means the old token is worthless.
      const token = host === config.host ? config.token : null;
      config = configStore.save({ ...config, host, mac, token }, configFile);
      powerCache = { at: 0, value: null };
      tv.configure({ host, token });
      return { ok: true, host, mac };
    },

    'POST /api/pair': async () => {
      await tv.connect();
      return { ok: true, paired: Boolean(config.token) };
    },

    'POST /api/forget': async () => {
      config = configStore.save({ ...config, token: null }, configFile);
      tv.configure({ token: null });
      tv.disconnect();
      return { ok: true };
    },

    'POST /api/key': async (body) => {
      const key = String(body.key ?? '');
      if (!isKnownKey(key)) throw badRequest(`unknown key: ${key}`);
      if (body.hold) {
        const ms = Number.isFinite(body.hold) ? Number(body.hold) : 800;
        await tv.holdKey(key, ms);
      } else {
        await tv.sendKey(key);
      }
      return { ok: true, key };
    },

    'POST /api/text': async (body) => {
      const text = String(body.text ?? '');
      if (!text) throw badRequest('nothing to type');
      if (text.length > 256) throw badRequest('that is more text than the TV will take at once');
      await tv.sendText(text);
      return { ok: true };
    },

    'POST /api/app': async (body) => {
      const appId = String(body.appId ?? '');
      if (!/^[0-9A-Za-z._-]{1,64}$/.test(appId)) throw badRequest(`unknown app: ${appId}`);
      await tv.launchApp(appId);
      return { ok: true, appId };
    },

    'POST /api/power-on': async () => {
      if (!config.mac) {
        throw badRequest('no MAC address saved for this TV, so it cannot be woken over the network');
      }
      const result = await wake(config.mac);
      powerCache = { at: 0, value: null };
      return { ok: true, ...result };
    },
  };

  const server = http.createServer((request, response) => {
    handle(request, response).catch((err) => {
      console.error('[remote] unhandled error:', err);
      if (!response.headersSent) sendJson(response, 500, { error: 'internal error' });
      else response.end();
    });
  });

  async function handle(request, response) {
    const url = new URL(request.url, `http://${request.headers.host ?? 'localhost'}`);

    if (!sameOriginOk(request)) {
      return sendJson(response, 403, { error: 'cross-origin requests are not accepted' });
    }

    if (url.pathname === '/api/events' && request.method === 'GET') {
      return streamEvents(request, response);
    }

    const route = routes[`${request.method} ${url.pathname}`];
    if (route) {
      let body = {};
      if (request.method === 'POST') {
        try {
          body = await readJsonBody(request);
        } catch (err) {
          return sendJson(response, err.status ?? 400, { error: err.message });
        }
      }
      try {
        return sendJson(response, 200, await route(body));
      } catch (err) {
        const status = err.status ?? 502;
        return sendJson(response, status, { error: err.message });
      }
    }

    if (url.pathname.startsWith('/api/')) {
      return sendJson(response, 404, { error: 'no such endpoint' });
    }
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return sendJson(response, 405, { error: 'method not allowed' });
    }
    return sendStatic(url.pathname, request, response);
  }

  function streamEvents(request, response) {
    response.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    });
    response.write(`data: ${JSON.stringify({ type: 'state', state: tv.state, error: tv.lastError })}\n\n`);
    listeners.add(response);
    // Proxies and phone radios drop idle connections; a comment every 20s
    // keeps the stream alive without waking anything up.
    const heartbeat = setInterval(() => response.write(': ping\n\n'), 20_000);
    request.on('close', () => {
      clearInterval(heartbeat);
      listeners.delete(response);
    });
  }

  server.on('close', () => {
    for (const response of listeners) response.end();
    listeners.clear();
    tv.disconnect();
  });

  return { server, tv, getConfig: () => ({ ...config }) };
}

// A page on some other site should not be able to drive the TV just because
// the phone is on the same Wi-Fi. Requests carrying a foreign Origin are
// refused, and the JSON content type the API requires forces a preflight that
// never gets an allow.
function sameOriginOk(request) {
  const origin = request.headers.origin;
  if (!origin) return true; // Same-origin GETs and non-browser clients.
  try {
    return new URL(origin).host === request.headers.host;
  } catch {
    return false;
  }
}

function badRequest(message) {
  const err = new Error(message);
  err.status = 400;
  return err;
}

function readJsonBody(request) {
  return new Promise((resolve, reject) => {
    const type = String(request.headers['content-type'] ?? '');
    if (!type.startsWith('application/json')) {
      return reject(badRequest('expected a JSON body'));
    }
    const chunks = [];
    let size = 0;
    request.on('data', (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        request.destroy();
        return reject(badRequest('request body too large'));
      }
      chunks.push(chunk);
    });
    request.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8').trim();
      if (!raw) return resolve({});
      try {
        const parsed = JSON.parse(raw);
        resolve(parsed && typeof parsed === 'object' ? parsed : {});
      } catch {
        reject(badRequest('body was not valid JSON'));
      }
    });
    request.on('error', reject);
  });
}

function sendJson(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'no-store',
  });
  response.end(body);
}

// Map a request path to a file under public/, or null if it would escape.
// URL parsing already collapses `..`, but nothing here should depend on that.
function resolveStaticPath(pathname) {
  const relative = pathname === '/' ? 'index.html' : decodeURIComponent(pathname).replace(/^\/+/, '');
  if (relative.includes('\0')) return null;
  const file = path.resolve(PUBLIC_DIR, relative);
  return file.startsWith(PUBLIC_DIR + path.sep) ? file : null;
}

function sendStatic(pathname, request, response) {
  let file;
  try {
    file = resolveStaticPath(pathname);
  } catch {
    file = null; // Malformed percent-encoding.
  }
  if (!file) {
    return sendJson(response, 403, { error: 'forbidden' });
  }

  fs.readFile(file, (err, contents) => {
    if (err) {
      response.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      return response.end('not found');
    }
    response.writeHead(200, {
      'Content-Type': CONTENT_TYPES[path.extname(file)] ?? 'application/octet-stream',
      'Content-Length': contents.length,
      'Cache-Control': 'no-cache',
    });
    response.end(request.method === 'HEAD' ? undefined : contents);
  });
}

function lanUrls(port) {
  const urls = [];
  for (const entries of Object.values(os.networkInterfaces())) {
    for (const entry of entries ?? []) {
      if (entry.family === 'IPv4' && !entry.internal) urls.push(`http://${entry.address}:${port}`);
    }
  }
  return urls.length ? urls : [`http://localhost:${port}`];
}

if (require.main === module) {
  const port = Number(process.env.PORT ?? 8099);
  const { server, getConfig } = createApp();
  server.listen(port, '0.0.0.0', () => {
    const config = getConfig();
    console.log('Samsung TV remote is running.');
    console.log('Open one of these on your phone (same Wi-Fi):');
    for (const url of lanUrls(port)) console.log(`  ${url}`);
    console.log(config.host ? `TV: ${config.host}${config.token ? ' (paired)' : ' (not paired yet)'}` : 'No TV set up yet — the page will help you find it.');
  });
}

module.exports = { createApp, lanUrls, resolveStaticPath, sameOriginOk };
