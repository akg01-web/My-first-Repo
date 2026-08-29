'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');

const { fetchDeviceInfo } = require('../lib/tv');
const { candidateAddresses, looksLikeSamsungTv, summarise, ipToInt, intToIp } = require('../lib/discover');

// What a 2019 N-series actually returns from http://<tv>:8001/api/v2/.
const DEVICE_DOCUMENT = {
  device: {
    FrameTVSupport: 'false',
    OS: 'Tizen',
    PowerState: 'on',
    TokenAuthSupport: 'true',
    countryCode: 'IN',
    id: 'uuid:1234',
    modelName: 'UA40N5200',
    name: '[TV] Samsung 5 Series (40)',
    networkType: 'wireless',
    resolution: '1920x1080',
    type: 'Samsung SmartTV',
    wifiMac: 'a1:b2:c3:d4:e5:f6',
  },
  id: 'uuid:1234',
  name: '[TV] Samsung 5 Series (40)',
  remote: '1.0',
  type: 'Samsung SmartTV',
  version: '2.0.25',
};

test('addresses round-trip through the integer form', () => {
  for (const ip of ['0.0.0.0', '127.0.0.1', '192.168.1.42', '255.255.255.255']) {
    assert.equal(intToIp(ipToInt(ip)), ip);
  }
});

test('the sweep stays small enough to finish', () => {
  const candidates = candidateAddresses();
  assert.ok(candidates.length <= 4096, `sweeping ${candidates.length} addresses would take too long`);
  for (const address of candidates) {
    assert.match(address, /^\d+\.\d+\.\d+\.\d+$/);
  }
});

test('a Samsung set is recognised, other devices are not', () => {
  assert.equal(looksLikeSamsungTv(DEVICE_DOCUMENT), true);
  assert.equal(looksLikeSamsungTv({ device: { OS: 'Tizen' } }), true, 'Tizen alone is enough');
  assert.equal(looksLikeSamsungTv({ type: 'Roku', device: { OS: 'RokuOS' } }), false);
  assert.equal(looksLikeSamsungTv(null), false);
  assert.equal(looksLikeSamsungTv('a string'), false);
});

test('the summary pulls out what the setup screen needs', () => {
  assert.deepEqual(summarise('192.168.1.42', DEVICE_DOCUMENT), {
    ip: '192.168.1.42',
    name: '[TV] Samsung 5 Series (40)',
    model: 'UA40N5200',
    mac: 'a1:b2:c3:d4:e5:f6',
    powerState: 'on',
    tokenAuth: true,
    frameTv: false,
  });
});

test('the device document is fetched and parsed', async (t) => {
  const server = http.createServer((request, response) => {
    if (request.url !== '/api/v2/') {
      response.writeHead(404).end();
      return;
    }
    response.writeHead(200, { 'Content-Type': 'application/json' });
    response.end(JSON.stringify(DEVICE_DOCUMENT));
  });

  // fetchDeviceInfo always asks for port 8001, which is where TVs answer.
  const listening = await new Promise((resolve) => {
    server.once('error', () => resolve(false));
    server.listen(8001, '127.0.0.1', () => resolve(true));
  });
  if (!listening) return t.skip('port 8001 is already in use here');
  t.after(() => new Promise((resolve) => server.close(resolve)));

  const info = await fetchDeviceInfo('127.0.0.1');
  assert.equal(info.device.modelName, 'UA40N5200');
  assert.equal(summarise('127.0.0.1', info).mac, 'a1:b2:c3:d4:e5:f6');
});

test('an address with nothing listening resolves to null instead of throwing', async () => {
  assert.equal(await fetchDeviceInfo('127.0.0.1', 300), null);
});

test('a bad host resolves to null rather than rejecting', async () => {
  assert.equal(await fetchDeviceInfo('no-such-host.invalid', 300), null);
  assert.equal(await fetchDeviceInfo('', 300), null);
});
