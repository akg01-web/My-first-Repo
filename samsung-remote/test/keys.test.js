'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const { GROUPS, APPS, isKnownKey } = require('../lib/keys');

test('no key is listed in two groups', () => {
  const seen = new Set();
  for (const [group, entries] of Object.entries(GROUPS)) {
    for (const { key } of entries) {
      assert.equal(seen.has(key), false, `${key} appears twice (again in ${group})`);
      seen.add(key);
    }
  }
});

test('every key looks like a Samsung key code', () => {
  for (const entries of Object.values(GROUPS)) {
    for (const { key, label } of entries) {
      assert.match(key, /^KEY_[A-Z0-9_]+$/, key);
      assert.ok(label && label.length > 0, `${key} needs a label`);
    }
  }
});

// The server rejects keys it does not recognise, so a typo in the markup would
// turn into a button that silently fails. Check the two agree.
test('every button in the page maps to a key the server will accept', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'public', 'index.html'), 'utf8');
  const used = [...html.matchAll(/data-key="([^"]+)"/g)].map((match) => match[1]);

  assert.ok(used.length > 20, `expected a full remote, found ${used.length} buttons`);
  for (const key of used) {
    assert.equal(isKnownKey(key), true, `the page uses ${key}, which the server would reject`);
  }
});

test('app ids pass the check the server applies to them', () => {
  for (const { id, name } of APPS) {
    assert.match(id, /^[0-9A-Za-z._-]{1,64}$/, `${name} has an id the server would reject`);
  }
});

test('unknown keys are not accepted', () => {
  for (const key of ['', 'KEY_', 'key_power', 'KEY_POWER; rm -rf /', 'POWER']) {
    assert.equal(isKnownKey(key), false, JSON.stringify(key));
  }
});
