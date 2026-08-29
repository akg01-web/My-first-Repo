'use strict';

// A stand-in for the television: it performs the WebSocket server handshake,
// speaks the Samsung channel protocol, and records what it was told to do.
//
// The framing here is written independently of lib/ws.js on purpose. The two
// implementations check each other: this one masks nothing and demands masked
// input, which is exactly the opposite of what the client does.

const net = require('node:net');
const tls = require('node:tls');
const crypto = require('node:crypto');
const { EventEmitter } = require('node:events');

const GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';

function readClientFrames(buffer) {
  const frames = [];
  let offset = 0;

  while (buffer.length - offset >= 2) {
    const opcode = buffer[offset] & 0x0f;
    const masked = (buffer[offset + 1] & 0x80) !== 0;
    let length = buffer[offset + 1] & 0x7f;
    let cursor = offset + 2;

    if (length === 126) {
      if (buffer.length - cursor < 2) break;
      length = buffer.readUInt16BE(cursor);
      cursor += 2;
    } else if (length === 127) {
      if (buffer.length - cursor < 8) break;
      length = Number(buffer.readBigUInt64BE(cursor));
      cursor += 8;
    }

    // RFC 6455 §5.1: every frame from a client must be masked.
    if (!masked) throw new Error('client sent an unmasked frame');
    if (buffer.length - cursor < 4 + length) break;

    const key = buffer.subarray(cursor, cursor + 4);
    cursor += 4;
    const payload = Buffer.from(buffer.subarray(cursor, cursor + length));
    for (let i = 0; i < length; i++) payload[i] ^= key[i & 3];
    cursor += length;

    frames.push({ opcode, payload });
    offset = cursor;
  }

  return { frames, rest: buffer.subarray(offset) };
}

function writeServerFrame(socket, opcode, payload) {
  const body = Buffer.isBuffer(payload) ? payload : Buffer.from(String(payload), 'utf8');
  let header;
  if (body.length < 126) {
    header = Buffer.from([0x80 | opcode, body.length]);
  } else if (body.length < 0x10000) {
    header = Buffer.alloc(4);
    header[0] = 0x80 | opcode;
    header[1] = 126;
    header.writeUInt16BE(body.length, 2);
  } else {
    header = Buffer.alloc(10);
    header[0] = 0x80 | opcode;
    header[1] = 127;
    header.writeBigUInt64BE(BigInt(body.length), 2);
  }
  socket.write(Buffer.concat([header, body]));
}

class FakeTv extends EventEmitter {
  constructor(options = {}) {
    super();
    this.token = options.token ?? 'FAKE-TOKEN-1234';
    this.issueToken = options.issueToken ?? true;
    this.denyPairing = options.denyPairing ?? false;
    this.silent = options.silent ?? false; // Never answer, to exercise timeouts.
    this.tlsOptions = options.tls ?? null;
    this.received = [];
    this.connections = [];
    this.sockets = new Set();
  }

  start() {
    const handler = (socket) => this.#onSocket(socket);
    this.server = this.tlsOptions ? tls.createServer(this.tlsOptions, handler) : net.createServer(handler);
    return new Promise((resolve) => {
      this.server.listen(0, '127.0.0.1', () => {
        this.port = this.server.address().port;
        resolve(this);
      });
    });
  }

  stop() {
    for (const socket of this.sockets) socket.destroy();
    this.sockets.clear();
    return new Promise((resolve) => this.server.close(resolve));
  }

  // Cut the connection without a close frame, the way a TV does when it
  // reboots or drops off the network.
  dropConnections() {
    for (const socket of this.sockets) socket.destroy();
    this.sockets.clear();
  }

  #onSocket(socket) {
    this.sockets.add(socket);
    socket.on('close', () => this.sockets.delete(socket));
    socket.on('error', () => {});

    let buffer = Buffer.alloc(0);
    let upgraded = false;

    socket.on('data', (chunk) => {
      buffer = Buffer.concat([buffer, chunk]);

      if (!upgraded) {
        const end = buffer.indexOf('\r\n\r\n');
        if (end === -1) return;
        const head = buffer.subarray(0, end).toString('latin1');
        buffer = buffer.subarray(end + 4);
        upgraded = true;
        this.#completeHandshake(socket, head);
        if (this.silent) return;
      }

      const { frames, rest } = readClientFrames(buffer);
      buffer = rest;
      for (const frame of frames) {
        if (frame.opcode === 0x8) {
          socket.end();
          continue;
        }
        if (frame.opcode !== 0x1) continue;
        const text = frame.payload.toString('utf8');
        let parsed = null;
        try {
          parsed = JSON.parse(text);
        } catch {
          // Record the raw text below anyway.
        }
        this.received.push(parsed ?? text);
        this.emit('command', parsed ?? text);
      }
    });
  }

  #completeHandshake(socket, head) {
    const [requestLine, ...headerLines] = head.split('\r\n');
    const target = requestLine.split(' ')[1] ?? '/';
    const url = new URL(target, 'http://tv.local');

    const headers = new Map();
    for (const line of headerLines) {
      const colon = line.indexOf(':');
      if (colon !== -1) headers.set(line.slice(0, colon).trim().toLowerCase(), line.slice(colon + 1).trim());
    }

    this.connections.push({
      path: url.pathname,
      name: Buffer.from(url.searchParams.get('name') ?? '', 'base64').toString('utf8'),
      token: url.searchParams.get('token'),
    });

    const key = headers.get('sec-websocket-key');
    const accept = crypto.createHash('sha1').update(key + GUID).digest('base64');
    socket.write(
      [
        'HTTP/1.1 101 Switching Protocols',
        'Upgrade: websocket',
        'Connection: Upgrade',
        `Sec-WebSocket-Accept: ${accept}`,
        '',
        '',
      ].join('\r\n'),
    );

    if (this.silent) return;

    if (this.denyPairing) {
      writeServerFrame(socket, 0x1, JSON.stringify({ event: 'ms.channel.unauthorized' }));
      return;
    }

    const presentedToken = url.searchParams.get('token');
    const data = { clients: [], id: 'fake-client-id' };
    // Real sets only hand back a token on the connection the user approves.
    if (this.issueToken && !presentedToken) data.token = this.token;
    writeServerFrame(socket, 0x1, JSON.stringify({ event: 'ms.channel.connect', data }));
  }
}

module.exports = { FakeTv, readClientFrames, writeServerFrame };
