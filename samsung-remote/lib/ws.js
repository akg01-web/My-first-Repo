'use strict';

// A small RFC 6455 WebSocket client.
//
// Samsung TVs expose their remote-control channel over `wss` with a
// self-signed certificate, so we need a client that can be told to skip
// certificate verification. Rather than take a dependency for that, this
// implements the slice of the protocol the TV actually uses: a client
// handshake, masked text frames out, unmasked frames in, ping/pong, close.

const net = require('node:net');
const tls = require('node:tls');
const crypto = require('node:crypto');
const { EventEmitter } = require('node:events');

const HANDSHAKE_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';

const OPCODE = {
  CONTINUATION: 0x0,
  TEXT: 0x1,
  BINARY: 0x2,
  CLOSE: 0x8,
  PING: 0x9,
  PONG: 0xa,
};

const DEFAULT_MAX_PAYLOAD = 4 * 1024 * 1024;

function acceptValueFor(key) {
  return crypto.createHash('sha1').update(key + HANDSHAKE_GUID).digest('base64');
}

// Build a single frame. Clients must mask; servers must not.
function encodeFrame(opcode, payload, mask = true) {
  const body = Buffer.isBuffer(payload) ? payload : Buffer.from(String(payload), 'utf8');
  const length = body.length;

  let header;
  if (length < 126) {
    header = Buffer.alloc(2);
    header[1] = length;
  } else if (length < 0x10000) {
    header = Buffer.alloc(4);
    header[1] = 126;
    header.writeUInt16BE(length, 2);
  } else {
    header = Buffer.alloc(10);
    header[1] = 127;
    header.writeBigUInt64BE(BigInt(length), 2);
  }
  header[0] = 0x80 | opcode; // FIN + opcode; we never fragment on the way out.

  if (!mask) return Buffer.concat([header, body]);

  header[1] |= 0x80;
  const maskKey = crypto.randomBytes(4);
  const masked = Buffer.allocUnsafe(length);
  for (let i = 0; i < length; i++) masked[i] = body[i] ^ maskKey[i & 3];
  return Buffer.concat([header, maskKey, masked]);
}

// Pull as many whole frames as `buffer` holds. Returns the frames plus
// whatever trailing bytes belong to a frame that has not fully arrived.
function decodeFrames(buffer, maxPayload = DEFAULT_MAX_PAYLOAD) {
  const frames = [];
  let offset = 0;

  for (;;) {
    if (buffer.length - offset < 2) break;

    const first = buffer[offset];
    const second = buffer[offset + 1];
    const fin = (first & 0x80) !== 0;
    const opcode = first & 0x0f;
    const masked = (second & 0x80) !== 0;
    let length = second & 0x7f;
    let cursor = offset + 2;

    if (length === 126) {
      if (buffer.length - cursor < 2) break;
      length = buffer.readUInt16BE(cursor);
      cursor += 2;
    } else if (length === 127) {
      if (buffer.length - cursor < 8) break;
      const big = buffer.readBigUInt64BE(cursor);
      if (big > BigInt(maxPayload)) {
        throw new Error(`websocket frame too large: ${big} bytes`);
      }
      length = Number(big);
      cursor += 8;
    }

    if (length > maxPayload) {
      throw new Error(`websocket frame too large: ${length} bytes`);
    }

    let maskKey = null;
    if (masked) {
      if (buffer.length - cursor < 4) break;
      maskKey = buffer.subarray(cursor, cursor + 4);
      cursor += 4;
    }

    if (buffer.length - cursor < length) break;

    let payload = Buffer.from(buffer.subarray(cursor, cursor + length));
    if (maskKey) {
      for (let i = 0; i < length; i++) payload[i] ^= maskKey[i & 3];
    }
    cursor += length;

    frames.push({ fin, opcode, payload });
    offset = cursor;
  }

  return { frames, rest: buffer.subarray(offset) };
}

class WebSocketClient extends EventEmitter {
  #socket = null;
  #buffer = Buffer.alloc(0);
  #handshakeDone = false;
  #fragments = [];
  #fragmentOpcode = null;
  #closed = false;
  #connectTimer = null;

  constructor(url, options = {}) {
    super();
    this.url = new URL(url);
    if (this.url.protocol !== 'ws:' && this.url.protocol !== 'wss:') {
      throw new Error(`unsupported websocket scheme: ${this.url.protocol}`);
    }
    this.secure = this.url.protocol === 'wss:';
    this.rejectUnauthorized = options.rejectUnauthorized !== false;
    this.connectTimeoutMs = options.connectTimeoutMs ?? 10_000;
    this.maxPayload = options.maxPayload ?? DEFAULT_MAX_PAYLOAD;
    this.headers = options.headers ?? {};
  }

  get readyState() {
    if (this.#closed) return 'closed';
    if (!this.#socket) return 'idle';
    return this.#handshakeDone ? 'open' : 'connecting';
  }

  connect() {
    if (this.#socket) throw new Error('already connected');

    const port = this.url.port ? Number(this.url.port) : this.secure ? 443 : 80;
    const host = this.url.hostname;
    const key = crypto.randomBytes(16).toString('base64');
    const expectedAccept = acceptValueFor(key);

    const onConnected = () => {
      const path = `${this.url.pathname}${this.url.search}`;
      const lines = [
        `GET ${path} HTTP/1.1`,
        `Host: ${host}:${port}`,
        'Upgrade: websocket',
        'Connection: Upgrade',
        `Sec-WebSocket-Key: ${key}`,
        'Sec-WebSocket-Version: 13',
      ];
      for (const [name, value] of Object.entries(this.headers)) {
        lines.push(`${name}: ${value}`);
      }
      this.#socket.write(lines.join('\r\n') + '\r\n\r\n');
    };

    this.#socket = this.secure
      ? tls.connect(
          { host, port, servername: net.isIP(host) ? undefined : host, rejectUnauthorized: this.rejectUnauthorized },
          onConnected,
        )
      : net.connect({ host, port }, onConnected);

    this.#socket.setNoDelay(true);

    this.#connectTimer = setTimeout(() => {
      this.#fail(new Error(`timed out connecting to ${host}:${port}`));
    }, this.connectTimeoutMs);
    if (this.#connectTimer.unref) this.#connectTimer.unref();

    this.#socket.on('data', (chunk) => {
      try {
        this.#onData(chunk, expectedAccept);
      } catch (err) {
        this.#fail(err);
      }
    });
    this.#socket.on('error', (err) => this.#fail(err));
    this.#socket.on('close', () => this.#finish());

    return this;
  }

  send(data) {
    if (!this.#handshakeDone || this.#closed) {
      throw new Error('websocket is not open');
    }
    this.#socket.write(encodeFrame(OPCODE.TEXT, data, true));
  }

  close(code = 1000, reason = '') {
    if (this.#closed || !this.#socket) {
      this.#finish();
      return;
    }
    const reasonBytes = Buffer.from(reason, 'utf8');
    const payload = Buffer.alloc(2 + reasonBytes.length);
    payload.writeUInt16BE(code, 0);
    reasonBytes.copy(payload, 2);
    try {
      if (this.#handshakeDone) this.#socket.write(encodeFrame(OPCODE.CLOSE, payload, true));
    } catch {
      // The socket is already gone; destroying below is enough.
    }
    this.#socket.destroy();
    this.#finish();
  }

  #onData(chunk, expectedAccept) {
    this.#buffer = this.#buffer.length ? Buffer.concat([this.#buffer, chunk]) : chunk;

    if (!this.#handshakeDone) {
      const end = this.#buffer.indexOf('\r\n\r\n');
      if (end === -1) {
        // Guard against a peer that never finishes its headers.
        if (this.#buffer.length > 64 * 1024) throw new Error('handshake response too large');
        return;
      }
      const head = this.#buffer.subarray(0, end).toString('latin1');
      this.#buffer = this.#buffer.subarray(end + 4);
      this.#verifyHandshake(head, expectedAccept);

      clearTimeout(this.#connectTimer);
      this.#handshakeDone = true;
      this.emit('open');
    }

    const { frames, rest } = decodeFrames(this.#buffer, this.maxPayload);
    this.#buffer = rest;
    for (const frame of frames) this.#onFrame(frame);
  }

  #verifyHandshake(head, expectedAccept) {
    const [statusLine, ...headerLines] = head.split('\r\n');
    const status = Number(statusLine.split(' ')[1]);
    if (status !== 101) {
      throw new Error(`websocket upgrade rejected: ${statusLine.trim()}`);
    }
    const headers = new Map();
    for (const line of headerLines) {
      const colon = line.indexOf(':');
      if (colon === -1) continue;
      headers.set(line.slice(0, colon).trim().toLowerCase(), line.slice(colon + 1).trim());
    }
    if (headers.get('sec-websocket-accept') !== expectedAccept) {
      throw new Error('websocket handshake failed: bad Sec-WebSocket-Accept');
    }
  }

  #onFrame(frame) {
    switch (frame.opcode) {
      case OPCODE.PING:
        this.#socket.write(encodeFrame(OPCODE.PONG, frame.payload, true));
        return;
      case OPCODE.PONG:
        return;
      case OPCODE.CLOSE: {
        // Echo the peer's code back, except the "no code given" placeholder,
        // which is not allowed on the wire.
        const code = frame.payload.length >= 2 ? frame.payload.readUInt16BE(0) : 1000;
        this.close(code, '');
        return;
      }
      case OPCODE.TEXT:
      case OPCODE.BINARY:
        if (frame.fin) {
          this.#emitMessage(frame.opcode, frame.payload);
        } else {
          this.#fragmentOpcode = frame.opcode;
          this.#fragments = [frame.payload];
        }
        return;
      case OPCODE.CONTINUATION: {
        if (this.#fragmentOpcode === null) throw new Error('continuation frame without a start frame');
        this.#fragments.push(frame.payload);
        if (!frame.fin) return;
        const payload = Buffer.concat(this.#fragments);
        const opcode = this.#fragmentOpcode;
        this.#fragments = [];
        this.#fragmentOpcode = null;
        this.#emitMessage(opcode, payload);
        return;
      }
      default:
        throw new Error(`unsupported websocket opcode: ${frame.opcode}`);
    }
  }

  #emitMessage(opcode, payload) {
    if (opcode === OPCODE.TEXT) this.emit('message', payload.toString('utf8'));
    else this.emit('binary', payload);
  }

  #fail(err) {
    if (this.#closed) return;
    clearTimeout(this.#connectTimer);
    this.emit('error', err);
    if (this.#socket) this.#socket.destroy();
    this.#finish();
  }

  #finish() {
    if (this.#closed) return;
    this.#closed = true;
    clearTimeout(this.#connectTimer);
    this.emit('close');
  }
}

module.exports = { WebSocketClient, encodeFrame, decodeFrames, acceptValueFor, OPCODE };
