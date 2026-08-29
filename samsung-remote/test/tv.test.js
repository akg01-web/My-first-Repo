'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const { SamsungTv } = require('../lib/tv');
const { FakeTv } = require('./fake-tv');

function connectTo(tv, { secure = false, ...rest } = {}) {
  return new SamsungTv({ host: '127.0.0.1', port: tv.port, secure, name: 'Phone Remote', ...rest });
}

test('first connection pairs and captures the token the TV hands back', async (t) => {
  const fake = await new FakeTv({ token: 'TOK-9876' }).start();
  t.after(() => fake.stop());

  const tv = connectTo(fake);
  const tokens = [];
  tv.on('token', (token) => tokens.push(token));

  await tv.connect();

  assert.equal(tv.state, 'connected');
  assert.deepEqual(tokens, ['TOK-9876']);
  assert.equal(tv.token, 'TOK-9876');
  assert.equal(fake.connections[0].name, 'Phone Remote', 'the client name is base64 in the query string');
  assert.equal(fake.connections[0].path, '/api/v2/channels/samsung.remote.control');
  assert.equal(fake.connections[0].token, null, 'nothing to present on the first connection');

  tv.disconnect();
});

test('a saved token is presented on later connections and no new one is issued', async (t) => {
  const fake = await new FakeTv({ token: 'TOK-9876' }).start();
  t.after(() => fake.stop());

  const tv = connectTo(fake, { token: 'TOK-9876' });
  const tokens = [];
  tv.on('token', (token) => tokens.push(token));

  await tv.connect();

  assert.equal(fake.connections[0].token, 'TOK-9876');
  assert.deepEqual(tokens, [], 'an already-paired connection issues no new token');
  tv.disconnect();
});

test('a key press is sent in the shape the TV expects', async (t) => {
  const fake = await new FakeTv().start();
  t.after(() => fake.stop());

  const tv = connectTo(fake);
  await tv.connect();
  await tv.sendKey('KEY_VOLUP');
  await once(fake, 'command');

  assert.deepEqual(fake.received[0], {
    method: 'ms.remote.control',
    params: { Cmd: 'Click', DataOfCmd: 'KEY_VOLUP', Option: 'false', TypeOfRemote: 'SendRemoteKey' },
  });
  tv.disconnect();
});

test('holding a key sends a press and a matching release', async (t) => {
  const fake = await new FakeTv().start();
  t.after(() => fake.stop());

  const tv = connectTo(fake);
  await tv.connect();
  await tv.holdKey('KEY_RIGHT', 60);

  await waitFor(() => fake.received.length === 2);
  assert.deepEqual(
    fake.received.map((message) => message.params.Cmd),
    ['Press', 'Release'],
  );
  assert.equal(fake.received[0].params.DataOfCmd, 'KEY_RIGHT');
  assert.equal(fake.received[1].params.DataOfCmd, 'KEY_RIGHT');
  tv.disconnect();
});

test('text is base64-encoded for the on-screen keyboard', async (t) => {
  const fake = await new FakeTv().start();
  t.after(() => fake.stop());

  const tv = connectTo(fake);
  await tv.connect();
  await tv.sendText('the office');
  await waitFor(() => fake.received.length === 1);

  const { params } = fake.received[0];
  assert.equal(params.TypeOfRemote, 'SendInputString');
  assert.equal(params.DataOfCmd, 'base64');
  assert.equal(Buffer.from(params.Cmd, 'base64').toString('utf8'), 'the office');
  tv.disconnect();
});

test('launching an app uses the channel-emit form', async (t) => {
  const fake = await new FakeTv().start();
  t.after(() => fake.stop());

  const tv = connectTo(fake);
  await tv.connect();
  await tv.launchApp('3201907018807');
  await waitFor(() => fake.received.length === 1);

  assert.deepEqual(fake.received[0], {
    method: 'ms.channel.emit',
    params: {
      event: 'ed.apps.launch',
      to: 'host',
      data: { appId: '3201907018807', action_type: 'DEEP_LINK' },
    },
  });
  tv.disconnect();
});

test('a refused pairing is reported, not retried silently', async (t) => {
  const fake = await new FakeTv({ denyPairing: true }).start();
  t.after(() => fake.stop());

  const tv = connectTo(fake);
  await assert.rejects(() => tv.connect(), /refused this device/);
  assert.equal(tv.state, 'unauthorized');
});

test('a TV that never answers times out with advice rather than hanging', async (t) => {
  const fake = await new FakeTv({ silent: true }).start();
  t.after(() => fake.stop());

  const tv = connectTo(fake, { pairTimeoutMs: 400 });
  await assert.rejects(() => tv.connect(), /accept the prompt on screen/);
  assert.equal(tv.state, 'offline');
});

test('a dropped connection is re-established on the next key press', async (t) => {
  const fake = await new FakeTv({ token: 'TOK-1' }).start();
  t.after(() => fake.stop());

  const tv = connectTo(fake);
  await tv.connect();
  await tv.sendKey('KEY_HOME');
  await waitFor(() => fake.received.length === 1);

  fake.dropConnections();
  await waitFor(() => tv.state === 'offline');

  await tv.sendKey('KEY_HOME');
  await waitFor(() => fake.received.length === 2);

  assert.equal(fake.connections.length, 2, 'reconnected');
  assert.equal(fake.connections[1].token, 'TOK-1', 'and reused the token, so no second prompt on the TV');
  tv.disconnect();
});

test('concurrent commands share one connection instead of racing to open several', async (t) => {
  const fake = await new FakeTv().start();
  t.after(() => fake.stop());

  const tv = connectTo(fake);
  await Promise.all([tv.sendKey('KEY_1'), tv.sendKey('KEY_2'), tv.sendKey('KEY_3')]);
  await waitFor(() => fake.received.length === 3);

  assert.equal(fake.connections.length, 1);
  tv.disconnect();
});

test('the self-signed certificate a real TV presents is accepted', async (t) => {
  const certificate = selfSignedCertificate();
  if (!certificate) return t.skip('openssl is not available to make a test certificate');

  const fake = await new FakeTv({ tls: certificate }).start();
  t.after(() => fake.stop());

  const tv = connectTo(fake, { secure: true });
  await tv.connect();

  assert.equal(tv.state, 'connected');
  tv.disconnect();
});

/* helpers */

function once(emitter, event) {
  return new Promise((resolve) => emitter.once(event, resolve));
}

async function waitFor(predicate, timeoutMs = 3_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error('timed out waiting for a condition');
}

function selfSignedCertificate() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fake-tv-'));
  const key = path.join(dir, 'key.pem');
  const cert = path.join(dir, 'cert.pem');
  try {
    execFileSync('openssl', [
      'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
      '-keyout', key, '-out', cert, '-days', '1', '-subj', '/CN=fake-tv',
    ], { stdio: 'ignore' });
    return { key: fs.readFileSync(key), cert: fs.readFileSync(cert) };
  } catch {
    return null; // No openssl here; the caller skips.
  } finally {
    process.on('exit', () => fs.rmSync(dir, { recursive: true, force: true }));
  }
}
