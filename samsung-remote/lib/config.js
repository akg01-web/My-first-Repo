'use strict';

// Where the TV's address and the pairing token live between runs. Pairing is a
// once-ever thing as long as the token survives, so this file is worth keeping.

const fs = require('node:fs');
const path = require('node:path');

const DEFAULT_PATH = process.env.SAMSUNG_REMOTE_CONFIG
  ? path.resolve(process.env.SAMSUNG_REMOTE_CONFIG)
  : path.join(__dirname, '..', 'data', 'config.json');

const DEFAULTS = {
  host: null,
  mac: null,
  token: null,
  port: 8002,
  secure: true,
  name: 'Phone Remote',
};

function load(file = DEFAULT_PATH) {
  try {
    const parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
    return { ...DEFAULTS, ...parsed };
  } catch (err) {
    if (err.code !== 'ENOENT') {
      console.warn(`[config] ignoring unreadable ${file}: ${err.message}`);
    }
    return { ...DEFAULTS };
  }
}

function save(config, file = DEFAULT_PATH) {
  const merged = { ...DEFAULTS, ...config };
  fs.mkdirSync(path.dirname(file), { recursive: true });
  // Write-then-rename so a crash mid-write can't leave a truncated file
  // (and take the pairing token with it).
  const temporary = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(merged, null, 2)}\n`, { mode: 0o600 });
  fs.renameSync(temporary, file);
  return merged;
}

module.exports = { load, save, DEFAULTS, DEFAULT_PATH };
