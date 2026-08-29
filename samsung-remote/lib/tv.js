'use strict';

// Talks to a Tizen (2016+) Samsung TV over its remote-control channel.
//
// The first connection with no token makes the TV show an "Allow this device?"
// prompt. Accepting hands back a token that we persist, so later connections
// are silent. 2018+ sets — the N5200 among them — only accept the encrypted
// channel on 8002, and present a self-signed certificate.

const http = require('node:http');
const { EventEmitter } = require('node:events');
const { WebSocketClient } = require('./ws');

const REMOTE_PATH = '/api/v2/channels/samsung.remote.control';

const STATE = {
  OFFLINE: 'offline',
  CONNECTING: 'connecting',
  PAIRING: 'pairing',
  CONNECTED: 'connected',
  UNAUTHORIZED: 'unauthorized',
};

class SamsungTv extends EventEmitter {
  #ws = null;
  #connecting = null;
  #state = STATE.OFFLINE;
  #lastError = null;

  constructor(options = {}) {
    super();
    this.host = options.host;
    this.port = options.port ?? 8002;
    this.secure = options.secure ?? true;
    this.name = options.name ?? 'Phone Remote';
    this.token = options.token ?? null;
    // Waiting on a human to reach for the TV remote takes longer than a
    // handshake with a token we already hold.
    this.pairTimeoutMs = options.pairTimeoutMs ?? 30_000;
    this.connectTimeoutMs = options.connectTimeoutMs ?? 10_000;
    this.infoTimeoutMs = options.infoTimeoutMs ?? 2_000;
  }

  get state() {
    return this.#state;
  }

  get lastError() {
    return this.#lastError;
  }

  configure({ host, token, port, secure, name }) {
    const hostChanged = host !== undefined && host !== this.host;
    if (host !== undefined) this.host = host;
    if (token !== undefined) this.token = token;
    if (port !== undefined) this.port = port;
    if (secure !== undefined) this.secure = secure;
    if (name !== undefined) this.name = name;
    if (hostChanged) this.disconnect();
  }

  remoteUrl() {
    const scheme = this.secure ? 'wss' : 'ws';
    const params = new URLSearchParams({ name: Buffer.from(this.name, 'utf8').toString('base64') });
    if (this.token) params.set('token', this.token);
    return `${scheme}://${this.host}:${this.port}${REMOTE_PATH}?${params}`;
  }

  #setState(state, error = null) {
    this.#lastError = error ? String(error.message ?? error) : state === STATE.CONNECTED ? null : this.#lastError;
    if (this.#state === state && !error) return;
    this.#state = state;
    this.emit('state', { state, error: this.#lastError });
  }

  connect() {
    if (!this.host) return Promise.reject(new Error('no TV address configured'));
    if (this.#ws && this.#state === STATE.CONNECTED) return Promise.resolve(this.#ws);
    if (this.#connecting) return this.#connecting;

    const pairing = !this.token;
    this.#setState(pairing ? STATE.PAIRING : STATE.CONNECTING);

    this.#connecting = new Promise((resolve, reject) => {
      let settled = false;
      const ws = new WebSocketClient(this.remoteUrl(), {
        rejectUnauthorized: false, // The TV's certificate is self-signed by design.
        connectTimeoutMs: pairing ? this.pairTimeoutMs : this.connectTimeoutMs,
      });

      const timer = setTimeout(() => {
        finish(new Error(pairing
          ? 'the TV never answered the pairing request — accept the prompt on screen and try again'
          : 'the TV did not complete the handshake'));
        ws.close();
      }, pairing ? this.pairTimeoutMs : this.connectTimeoutMs);
      if (timer.unref) timer.unref();

      const finish = (err, value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        this.#connecting = null;
        if (err) {
          this.#ws = null;
          if (this.#state !== STATE.UNAUTHORIZED) this.#setState(STATE.OFFLINE, err);
          reject(err);
        } else {
          resolve(value);
        }
      };

      ws.on('message', (raw) => {
        let message;
        try {
          message = JSON.parse(raw);
        } catch {
          return; // Not something we know how to read; ignore it.
        }
        this.emit('message', message);

        if (message.event === 'ms.channel.connect') {
          const token = message.data?.token;
          if (token && token !== this.token) {
            this.token = String(token);
            this.emit('token', this.token);
          }
          this.#ws = ws;
          this.#setState(STATE.CONNECTED);
          finish(null, ws);
        } else if (message.event === 'ms.channel.unauthorized') {
          this.#setState(STATE.UNAUTHORIZED, new Error('the TV refused this device'));
          finish(new Error('the TV refused this device — check Settings > General > External Device Manager > Device Connection Manager'));
          ws.close();
        } else if (message.event === 'ms.error') {
          finish(new Error(message.data?.message ?? 'the TV reported an error'));
        }
      });

      ws.on('error', (err) => finish(err));
      ws.on('close', () => {
        if (this.#ws === ws) {
          this.#ws = null;
          this.#setState(STATE.OFFLINE);
        }
        finish(new Error('the connection to the TV closed'));
      });

      try {
        ws.connect();
      } catch (err) {
        finish(err);
      }
    });

    return this.#connecting;
  }

  disconnect() {
    if (this.#ws) {
      const ws = this.#ws;
      this.#ws = null;
      ws.close();
    }
    this.#setState(STATE.OFFLINE);
  }

  async #send(payload) {
    const ws = this.#ws && this.#state === STATE.CONNECTED ? this.#ws : await this.connect();
    try {
      ws.send(JSON.stringify(payload));
    } catch (err) {
      // The socket died between commands — reconnect once and retry.
      this.#ws = null;
      this.#setState(STATE.OFFLINE, err);
      const fresh = await this.connect();
      fresh.send(JSON.stringify(payload));
    }
  }

  sendKey(key, cmd = 'Click') {
    return this.#send({
      method: 'ms.remote.control',
      params: { Cmd: cmd, DataOfCmd: key, Option: 'false', TypeOfRemote: 'SendRemoteKey' },
    });
  }

  // Press-and-hold, for the keys where the TV repeats while held.
  async holdKey(key, durationMs = 1_000) {
    await this.sendKey(key, 'Press');
    await new Promise((resolve) => setTimeout(resolve, Math.min(Math.max(durationMs, 50), 10_000)));
    await this.sendKey(key, 'Release');
  }

  sendText(text) {
    return this.#send({
      method: 'ms.remote.control',
      params: {
        Cmd: Buffer.from(String(text), 'utf8').toString('base64'),
        DataOfCmd: 'base64',
        TypeOfRemote: 'SendInputString',
        TypeOfInput: 'string',
      },
    });
  }

  launchApp(appId, actionType = 'DEEP_LINK') {
    return this.#send({
      method: 'ms.channel.emit',
      params: {
        event: 'ed.apps.launch',
        to: 'host',
        data: { appId: String(appId), action_type: actionType },
      },
    });
  }

  // The unauthenticated REST endpoint on 8001 tells us the model, the MAC
  // address for wake-on-LAN, and on most firmware the power state.
  deviceInfo(host = this.host) {
    return fetchDeviceInfo(host, this.infoTimeoutMs);
  }
}

// Ask a candidate address whether it is a Samsung TV. Resolves to the parsed
// device document, or null for anything that isn't one (or is powered down).
function fetchDeviceInfo(host, timeoutMs = 2_000) {
  return new Promise((resolve) => {
    if (!host) return resolve(null);
    let settled = false;
    const done = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    const request = http.get({ host, port: 8001, path: '/api/v2/', timeout: timeoutMs }, (response) => {
      if (response.statusCode !== 200) {
        response.resume();
        return done(null);
      }
      const chunks = [];
      let size = 0;
      response.on('data', (chunk) => {
        size += chunk.length;
        if (size > 256 * 1024) {
          request.destroy();
          return done(null);
        }
        chunks.push(chunk);
      });
      response.on('end', () => {
        try {
          done(JSON.parse(Buffer.concat(chunks).toString('utf8')));
        } catch {
          done(null);
        }
      });
    });
    request.on('timeout', () => request.destroy());
    request.on('error', () => done(null));
  });
}

module.exports = { SamsungTv, STATE, fetchDeviceInfo };
