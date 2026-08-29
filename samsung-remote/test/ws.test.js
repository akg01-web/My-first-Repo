'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { encodeFrame, decodeFrames, acceptValueFor, OPCODE, WebSocketClient } = require('../lib/ws');
const { readClientFrames, writeServerFrame } = require('./fake-tv');

test('handshake accept matches the RFC 6455 worked example', () => {
  assert.equal(acceptValueFor('dGhlIHNhbXBsZSBub25jZQ=='), 's3pPLMBiTxaQ9kYGzzhZRbK+xOo=');
});

test('client frames are masked and decode back to the original text', () => {
  for (const length of [0, 1, 125, 126, 127, 65_535, 65_536]) {
    const text = 'x'.repeat(length);
    const frame = encodeFrame(OPCODE.TEXT, text, true);
    assert.equal((frame[1] & 0x80) !== 0, true, `frame of ${length} bytes should be masked`);

    const { frames, rest } = readClientFrames(frame);
    assert.equal(rest.length, 0);
    assert.equal(frames.length, 1);
    assert.equal(frames[0].payload.toString('utf8'), text);
  }
});

test('masking uses a fresh key each time', () => {
  const a = encodeFrame(OPCODE.TEXT, 'same payload', true);
  const b = encodeFrame(OPCODE.TEXT, 'same payload', true);
  assert.notDeepEqual(a.subarray(2, 6), b.subarray(2, 6));
});

test('server frames decode, including multi-byte UTF-8 and long payloads', () => {
  for (const text of ['ok', '日本語テスト', 'y'.repeat(70_000)]) {
    const chunks = [];
    writeServerFrame({ write: (buffer) => chunks.push(buffer) }, 0x1, text);
    const { frames, rest } = decodeFrames(Buffer.concat(chunks));
    assert.equal(rest.length, 0);
    assert.equal(frames[0].payload.toString('utf8'), text);
  }
});

test('a frame split across TCP reads is held back until it is whole', () => {
  const chunks = [];
  writeServerFrame({ write: (buffer) => chunks.push(buffer) }, 0x1, 'hello there');
  const full = Buffer.concat(chunks);

  for (let split = 1; split < full.length; split++) {
    const first = decodeFrames(full.subarray(0, split));
    assert.equal(first.frames.length, 0, `no frame should decode from ${split} of ${full.length} bytes`);
    const second = decodeFrames(Buffer.concat([first.rest, full.subarray(split)]));
    assert.equal(second.frames[0].payload.toString('utf8'), 'hello there');
  }
});

test('several frames in one read all come out', () => {
  const chunks = [];
  const sink = { write: (buffer) => chunks.push(buffer) };
  writeServerFrame(sink, 0x1, 'one');
  writeServerFrame(sink, 0x1, 'two');
  writeServerFrame(sink, 0x1, 'three');

  const { frames, rest } = decodeFrames(Buffer.concat(chunks));
  assert.equal(rest.length, 0);
  assert.deepEqual(frames.map((frame) => frame.payload.toString('utf8')), ['one', 'two', 'three']);
});

test('an over-long frame is refused rather than buffered', () => {
  const header = Buffer.alloc(10);
  header[0] = 0x81;
  header[1] = 127;
  header.writeBigUInt64BE(64n * 1024n * 1024n, 2);
  assert.throws(() => decodeFrames(header, 4 * 1024 * 1024), /too large/);
});

// net.Server, unlike http.Server, has no closeAllConnections, so track the
// sockets here and tear them down explicitly.
async function rawServer(onSocket) {
  const net = require('node:net');
  const sockets = new Set();
  const server = net.createServer((socket) => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
    socket.on('error', () => {});
    onSocket(socket);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  return {
    port: server.address().port,
    async close() {
      for (const socket of sockets) socket.destroy();
      await new Promise((resolve) => server.close(resolve));
    },
  };
}

function respondWithUpgrade(socket, head, { accept } = {}) {
  const crypto = require('node:crypto');
  const key = /sec-websocket-key: (.+)/i.exec(head)[1].trim();
  const value = accept ?? crypto.createHash('sha1').update(key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
  socket.write(
    `HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${value}\r\n\r\n`,
  );
}

test('fragmented server messages are reassembled', async () => {
  const server = await rawServer((socket) => {
    socket.once('data', (chunk) => {
      respondWithUpgrade(socket, chunk.toString('latin1'));
      // "Sam" / "sung" / " TV" as a text frame plus two continuations.
      socket.write(Buffer.concat([Buffer.from([0x01, 3]), Buffer.from('Sam')]));
      socket.write(Buffer.concat([Buffer.from([0x00, 4]), Buffer.from('sung')]));
      socket.write(Buffer.concat([Buffer.from([0x80, 3]), Buffer.from(' TV')]));
    });
  });

  const client = new WebSocketClient(`ws://127.0.0.1:${server.port}/api/v2/channels/samsung.remote.control`);
  const message = await new Promise((resolve, reject) => {
    client.on('message', resolve);
    client.on('error', reject);
    client.connect();
  });

  assert.equal(message, 'Samsung TV');
  client.close();
  await server.close();
});

test('a ping from the server is answered with a pong', async () => {
  let fromClient = Buffer.alloc(0);
  const server = await rawServer((socket) => {
    socket.once('data', (chunk) => {
      respondWithUpgrade(socket, chunk.toString('latin1'));
      socket.write(Buffer.from([0x89, 0x04, ...Buffer.from('ping')])); // opcode 0x9
      socket.on('data', (later) => {
        fromClient = Buffer.concat([fromClient, later]);
      });
    });
  });

  const client = new WebSocketClient(`ws://127.0.0.1:${server.port}/`);
  await new Promise((resolve, reject) => {
    client.on('open', resolve);
    client.on('error', reject);
    client.connect();
  });
  await new Promise((resolve) => setTimeout(resolve, 150));

  const { frames } = readClientFrames(fromClient);
  assert.equal(frames.length, 1);
  assert.equal(frames[0].opcode, 0xa, 'should reply with a pong');
  assert.equal(frames[0].payload.toString('utf8'), 'ping', 'pong carries the ping payload back');

  client.close();
  await server.close();
});

test('a server that refuses the upgrade surfaces an error', async () => {
  const server = await rawServer((socket) => {
    socket.on('data', () => socket.write('HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n'));
  });

  const client = new WebSocketClient(`ws://127.0.0.1:${server.port}/`);
  const error = await new Promise((resolve) => {
    client.on('error', resolve);
    client.connect();
  });

  assert.match(error.message, /upgrade rejected: HTTP\/1\.1 403/);
  client.close();
  await server.close();
});

test('a bad Sec-WebSocket-Accept is rejected', async () => {
  const server = await rawServer((socket) => {
    socket.once('data', (chunk) => respondWithUpgrade(socket, chunk.toString('latin1'), { accept: 'wrong' }));
  });

  const client = new WebSocketClient(`ws://127.0.0.1:${server.port}/`);
  const error = await new Promise((resolve) => {
    client.on('error', resolve);
    client.connect();
  });

  assert.match(error.message, /bad Sec-WebSocket-Accept/);
  client.close();
  await server.close();
});

test('connecting to a port with nothing on it fails instead of hanging', async () => {
  const net = require('node:net');
  const probe = net.createServer();
  await new Promise((resolve) => probe.listen(0, '127.0.0.1', resolve));
  const deadPort = probe.address().port;
  await new Promise((resolve) => probe.close(resolve));

  const client = new WebSocketClient(`ws://127.0.0.1:${deadPort}/`, { connectTimeoutMs: 2_000 });
  const error = await new Promise((resolve) => {
    client.on('error', resolve);
    client.connect();
  });

  assert.ok(error, 'should report an error');
  assert.equal(client.readyState, 'closed');
});
