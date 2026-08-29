'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const dgram = require('node:dgram');

const { wake, magicPacket, parseMac, broadcastAddresses } = require('../lib/wol');

test('a magic packet is six 0xff bytes then the MAC sixteen times', () => {
  const packet = magicPacket('a1:b2:c3:d4:e5:f6');
  const mac = Buffer.from([0xa1, 0xb2, 0xc3, 0xd4, 0xe5, 0xf6]);

  assert.equal(packet.length, 102);
  assert.deepEqual(packet.subarray(0, 6), Buffer.alloc(6, 0xff));
  for (let i = 0; i < 16; i++) {
    assert.deepEqual(packet.subarray(6 + i * 6, 12 + i * 6), mac, `repetition ${i}`);
  }
});

test('MAC addresses are accepted in the formats people actually paste', () => {
  const expected = Buffer.from([0xa1, 0xb2, 0xc3, 0xd4, 0xe5, 0xf6]);
  for (const form of ['a1:b2:c3:d4:e5:f6', 'A1-B2-C3-D4-E5-F6', 'a1b2c3d4e5f6', '  a1:B2:c3:D4:e5:F6  ']) {
    assert.deepEqual(parseMac(form), expected, form);
  }
});

test('anything that is not a MAC address is refused', () => {
  for (const junk of ['', 'not a mac', 'a1:b2:c3:d4:e5', 'a1:b2:c3:d4:e5:f6:07', 'zz:b2:c3:d4:e5:f6']) {
    assert.throws(() => parseMac(junk), /not a MAC address/, JSON.stringify(junk));
  }
});

test('the wake-up packet is actually put on the wire', async () => {
  const listener = dgram.createSocket('udp4');
  const received = new Promise((resolve) => listener.once('message', resolve));
  await new Promise((resolve) => listener.bind(0, '127.0.0.1', resolve));

  const port = listener.address().port;
  const result = await wake('a1:b2:c3:d4:e5:f6', { ports: [port], targets: ['127.0.0.1'] });

  assert.equal(result.sent, 1);
  assert.deepEqual(await received, magicPacket('a1:b2:c3:d4:e5:f6'));
  listener.close();
});

test('the broadcast list always includes the global broadcast address', () => {
  assert.ok(broadcastAddresses().includes('255.255.255.255'));
});
