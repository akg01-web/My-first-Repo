'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { load, save, DEFAULTS } = require('../lib/config');

function tempFile(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'remote-config-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return path.join(dir, 'config.json');
}

test('a missing file reads as the defaults', (t) => {
  assert.deepEqual(load(tempFile(t)), DEFAULTS);
});

test('what is saved is what comes back', (t) => {
  const file = tempFile(t);
  save({ host: '192.168.1.42', mac: 'a1:b2:c3:d4:e5:f6', token: 'TOK' }, file);

  assert.deepEqual(load(file), { ...DEFAULTS, host: '192.168.1.42', mac: 'a1:b2:c3:d4:e5:f6', token: 'TOK' });
});

test('a corrupt file falls back to defaults rather than crashing the server', (t) => {
  const file = tempFile(t);
  fs.writeFileSync(file, '{ this is not json');

  assert.deepEqual(load(file), DEFAULTS);
});

test('saving leaves no temporary files behind', (t) => {
  const file = tempFile(t);
  save({ host: '10.0.0.1' }, file);

  assert.deepEqual(fs.readdirSync(path.dirname(file)), ['config.json']);
});

test('the file holding the pairing token is not world-readable', (t) => {
  const file = tempFile(t);
  save({ token: 'secret' }, file);

  assert.equal(fs.statSync(file).mode & 0o077, 0, 'no group or other access');
});

test('fields absent from an older file get their defaults back', (t) => {
  const file = tempFile(t);
  fs.writeFileSync(file, JSON.stringify({ host: '10.0.0.9' }));

  const config = load(file);
  assert.equal(config.host, '10.0.0.9');
  assert.equal(config.port, 8002);
  assert.equal(config.secure, true);
});
