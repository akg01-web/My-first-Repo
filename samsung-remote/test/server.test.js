'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');

const { createApp, resolveStaticPath } = require('../server');
const { FakeTv } = require('./fake-tv');

// Boot the real server against the fake TV, on throwaway ports and a
// throwaway config file.
async function boot(t, configOverrides = {}) {
  const fake = await new FakeTv().start();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'remote-test-'));
  const configFile = path.join(dir, 'config.json');
  fs.writeFileSync(
    configFile,
    JSON.stringify({ host: '127.0.0.1', port: fake.port, secure: false, name: 'Test Remote', ...configOverrides }),
  );

  const { server, getConfig } = createApp({ configFile });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;

  t.after(async () => {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
    await fake.stop();
    fs.rmSync(dir, { recursive: true, force: true });
  });

  return { fake, base, configFile, getConfig, port: server.address().port };
}

const postJson = (base, path, body = {}, headers = {}) =>
  fetch(`${base}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
  });

test('the remote page is served', async (t) => {
  const { base } = await boot(t);
  const response = await fetch(`${base}/`);
  const html = await response.text();

  assert.equal(response.status, 200);
  assert.match(response.headers.get('content-type'), /text\/html/);
  assert.match(html, /<title>TV Remote<\/title>/);
});

test('state reports what is configured and whether we are paired', async (t) => {
  const { base } = await boot(t);
  const state = await (await fetch(`${base}/api/state`)).json();

  assert.equal(state.configured, true);
  assert.equal(state.host, '127.0.0.1');
  assert.equal(state.paired, false);
  assert.equal(state.connection, 'offline');
});

test('a key press reaches the TV', async (t) => {
  const { base, fake } = await boot(t);
  const response = await postJson(base, '/api/key', { key: 'KEY_VOLUP' });

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true, key: 'KEY_VOLUP' });
  assert.equal(fake.received.at(-1).params.DataOfCmd, 'KEY_VOLUP');
});

test('a held key becomes a press and a release', async (t) => {
  const { base, fake } = await boot(t);
  const response = await postJson(base, '/api/key', { key: 'KEY_VOLDOWN', hold: 60 });

  assert.equal(response.status, 200);
  assert.deepEqual(fake.received.map((message) => message.params.Cmd), ['Press', 'Release']);
  assert.equal(fake.received[0].params.DataOfCmd, 'KEY_VOLDOWN');
});

test('an unknown key is rejected before it reaches the TV', async (t) => {
  const { base, fake } = await boot(t);
  const response = await postJson(base, '/api/key', { key: 'KEY_LAUNCH_MISSILES' });

  assert.equal(response.status, 400);
  assert.match((await response.json()).error, /unknown key/);
  assert.equal(fake.received.length, 0);
});

test('the pairing token is written to disk as soon as the TV issues it', async (t) => {
  const { base, configFile } = await boot(t);
  await postJson(base, '/api/pair');

  const saved = JSON.parse(fs.readFileSync(configFile, 'utf8'));
  assert.equal(saved.token, 'FAKE-TOKEN-1234');

  const state = await (await fetch(`${base}/api/state`)).json();
  assert.equal(state.paired, true);
});

test('forgetting the pairing clears the stored token', async (t) => {
  const { base, configFile } = await boot(t);
  await postJson(base, '/api/pair');
  await postJson(base, '/api/forget');

  assert.equal(JSON.parse(fs.readFileSync(configFile, 'utf8')).token, null);
});

test('pointing the remote at a different TV drops the old token', async (t) => {
  const { base, configFile } = await boot(t);
  await postJson(base, '/api/pair');
  assert.ok(JSON.parse(fs.readFileSync(configFile, 'utf8')).token);

  await postJson(base, '/api/config', { host: '192.168.1.99', mac: 'aa:bb:cc:dd:ee:ff' });
  const saved = JSON.parse(fs.readFileSync(configFile, 'utf8'));

  assert.equal(saved.host, '192.168.1.99');
  assert.equal(saved.mac, 'aa:bb:cc:dd:ee:ff');
  assert.equal(saved.token, null, 'a token from one TV is useless on another');
});

test('a nonsense address is refused', async (t) => {
  const { base } = await boot(t);
  const response = await postJson(base, '/api/config', { host: 'http://192.168.1.5:8002/' });

  assert.equal(response.status, 400);
  assert.match((await response.json()).error, /does not look like/);
});

test('text is forwarded, and empty text is not', async (t) => {
  const { base, fake } = await boot(t);

  assert.equal((await postJson(base, '/api/text', { text: 'stranger things' })).status, 200);
  assert.equal(
    Buffer.from(fake.received.at(-1).params.Cmd, 'base64').toString('utf8'),
    'stranger things',
  );
  assert.equal((await postJson(base, '/api/text', { text: '' })).status, 400);
  assert.equal((await postJson(base, '/api/text', { text: 'x'.repeat(300) })).status, 400);
});

test('app launches are restricted to plausible app ids', async (t) => {
  const { base, fake } = await boot(t);

  assert.equal((await postJson(base, '/api/app', { appId: '3201907018807' })).status, 200);
  assert.equal(fake.received.at(-1).params.data.appId, '3201907018807');
  assert.equal((await postJson(base, '/api/app', { appId: '../../etc/passwd' })).status, 400);
});

test('waking the TV needs a MAC address, and says so', async (t) => {
  const { base } = await boot(t);
  const response = await postJson(base, '/api/power-on');

  assert.equal(response.status, 400);
  assert.match((await response.json()).error, /MAC address/);
});

test('a request from another website is refused', async (t) => {
  const { base, fake } = await boot(t);
  const response = await postJson(base, '/api/key', { key: 'KEY_POWER' }, { Origin: 'http://evil.example' });

  assert.equal(response.status, 403);
  assert.equal(fake.received.length, 0, 'nothing reached the TV');
});

test('a request from the remote page itself is allowed', async (t) => {
  const { base, port } = await boot(t);
  const response = await postJson(base, '/api/key', { key: 'KEY_HOME' }, { Origin: `http://127.0.0.1:${port}` });

  assert.equal(response.status, 200);
});

test('a form-encoded post is refused, so it cannot dodge the preflight', async (t) => {
  const { base, fake } = await boot(t);
  const response = await fetch(`${base}/api/key`, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain' },
    body: JSON.stringify({ key: 'KEY_POWER' }),
  });

  assert.equal(response.status, 400);
  assert.equal(fake.received.length, 0);
});

test('malformed JSON is a bad request, not a crash', async (t) => {
  const { base } = await boot(t);
  const response = await fetch(`${base}/api/key`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{not json',
  });

  assert.equal(response.status, 400);
});

test('the static path guard refuses anything outside public/', () => {
  assert.ok(resolveStaticPath('/').endsWith(path.join('public', 'index.html')));
  assert.ok(resolveStaticPath('/app.js').endsWith(path.join('public', 'app.js')));

  for (const attempt of [
    '/../server.js',
    '/..%2fserver.js',
    '/%2e%2e/%2e%2e/server.js',
    '/a/../../../etc/passwd',
    '/%00.js',
  ]) {
    assert.equal(resolveStaticPath(attempt), null, `${attempt} should be refused`);
  }
});

test('a raw traversal request over the wire leaks nothing', async (t) => {
  const { port } = await boot(t);

  // fetch() would normalise the path away, so speak HTTP directly.
  const request = (target) =>
    new Promise((resolve, reject) => {
      const socket = net.connect(port, '127.0.0.1', () => {
        socket.write(`GET ${target} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n`);
      });
      const chunks = [];
      socket.on('data', (chunk) => chunks.push(chunk));
      socket.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
      socket.on('error', reject);
    });

  for (const target of ['/../server.js', '/..%2fserver.js', '/%2e%2e/server.js']) {
    const raw = await request(target);
    assert.match(raw, /^HTTP\/1\.1 (403|404)/, `${target} should not be served`);
    assert.doesNotMatch(raw, /createApp/, `${target} leaked server source`);
  }
});

test('unknown endpoints and methods are answered cleanly', async (t) => {
  const { base } = await boot(t);

  assert.equal((await fetch(`${base}/api/nope`)).status, 404);
  assert.equal((await fetch(`${base}/nope.html`)).status, 404);
  assert.equal((await postJson(base, '/index.html')).status, 405);
});

test('the event stream opens with the current connection state', async (t) => {
  const { base } = await boot(t);
  const response = await fetch(`${base}/api/events`);

  assert.match(response.headers.get('content-type'), /text\/event-stream/);
  const reader = response.body.getReader();
  const { value } = await reader.read();
  const frame = new TextDecoder().decode(value);

  assert.match(frame, /^data: /);
  assert.equal(JSON.parse(frame.slice(6).trim()).type, 'state');
  await reader.cancel();
});
