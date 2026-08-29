'use strict';

// The page is deliberately thin: it turns taps into API calls and shows what
// the server says about the connection. Everything protocol-shaped lives on
// the server side.

const $ = (id) => document.getElementById(id);

const state = {
  power: null,
  connection: 'offline',
  configured: false,
};

/* ---------- transport ---------- */

async function api(path, body) {
  const options = body
    ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
    : {};
  const response = await fetch(path, options);
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    // Keep the HTTP status as the error below.
  }
  if (!response.ok) throw new Error(payload.error || `request failed (${response.status})`);
  return payload;
}

// Key presses are sent one at a time so five taps on volume-up arrive as five
// steps in order, rather than racing each other.
const queue = [];
let draining = false;

function enqueue(task) {
  // Holding a button down on a slow link shouldn't build a backlog that keeps
  // firing after your thumb is off it.
  if (queue.length > 6) return;
  queue.push(task);
  if (!draining) drain();
}

async function drain() {
  draining = true;
  while (queue.length) {
    const task = queue.shift();
    try {
      await task();
    } catch (err) {
      toast(err.message, true);
      queue.length = 0;
    }
  }
  draining = false;
}

/* ---------- feedback ---------- */

let toastTimer = null;

function toast(message, bad = false) {
  const element = $('toast');
  element.textContent = message;
  element.classList.toggle('bad', bad);
  element.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    element.hidden = true;
  }, bad ? 4200 : 1800);
}

function buzz(ms = 8) {
  if (navigator.vibrate) navigator.vibrate(ms);
}

/* ---------- key presses ---------- */

const REPEAT_DELAY_MS = 420;
const REPEAT_EVERY_MS = 130;

let held = null;

function sendKey(key) {
  enqueue(() => api('/api/key', { key }));
}

function pressStart(button) {
  const key = button.dataset.key;
  if (!key) return;

  buzz();
  button.classList.add('pressed');

  if (button.hasAttribute('data-power')) {
    handlePower();
  } else {
    sendKey(key);
  }

  if (!button.hasAttribute('data-repeat')) {
    held = { button, timers: [] };
    return;
  }

  const timers = [];
  timers.push(setTimeout(() => {
    timers.push(setInterval(() => sendKey(key), REPEAT_EVERY_MS));
  }, REPEAT_DELAY_MS));
  held = { button, timers };
}

function pressEnd() {
  if (!held) return;
  held.button.classList.remove('pressed');
  for (const timer of held.timers) {
    clearTimeout(timer);
    clearInterval(timer);
  }
  held = null;
}

// A TV that isn't answering is asleep, and the only thing that reaches it then
// is a wake-on-LAN packet. Liveness comes from the power probe, not from
// whether we happen to hold a socket open: the remote connects lazily, so a
// live TV reads as "not connected" until the first key press.
async function handlePower() {
  if (state.power === 'unreachable') {
    try {
      await api('/api/power-on', {});
      toast('Wake-up sent');
      setTimeout(refreshState, 2500);
      return;
    } catch (err) {
      // No MAC saved, or nothing could send: fall through and try the key,
      // which works when the set is only in a light standby.
      toast(err.message, true);
    }
  }
  enqueue(() => api('/api/key', { key: 'KEY_POWER' }));
}

document.addEventListener('pointerdown', (event) => {
  const button = event.target.closest('button[data-key]');
  if (!button) return;
  event.preventDefault(); // Stop the long-press text selection on iOS.
  pressStart(button);
});

document.addEventListener('pointerup', pressEnd);
document.addEventListener('pointercancel', pressEnd);
window.addEventListener('blur', pressEnd);
document.addEventListener('contextmenu', (event) => {
  if (event.target.closest('button')) event.preventDefault();
});

/* ---------- status ---------- */

const STATUS_TEXT = {
  connected: 'Connected',
  connecting: 'Connecting…',
  pairing: 'Allow this device on the TV',
  unauthorized: 'The TV refused this device',
  offline: 'Not connected',
};

function renderStatus() {
  const dot = $('dot');
  const text = $('statusText');
  const connection = state.connection;

  dot.className = 'dot';
  if (connection === 'connected') dot.classList.add('on');
  else if (connection === 'connecting' || connection === 'pairing') dot.classList.add('busy');
  else dot.classList.add('off');

  if (!state.configured) {
    text.textContent = 'Tap ⚙ to find your TV';
    return;
  }
  if (connection !== 'connected' && state.power === 'unreachable') {
    text.textContent = 'TV is off — tap power';
    return;
  }
  text.textContent = STATUS_TEXT[connection] ?? connection;
}

async function refreshState() {
  try {
    const status = await api('/api/state');
    Object.assign(state, status);
    renderStatus();
    if (!status.configured) openSettings();
    if (status.host) $('hostInput').value = status.host;
    if (status.mac) $('macInput').value = status.mac;
  } catch {
    state.connection = 'offline';
    renderStatus();
  }
}

function listenForStateChanges() {
  const source = new EventSource('/api/events');
  source.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === 'state') {
        state.connection = payload.state;
        renderStatus();
      }
    } catch {
      // A malformed frame isn't worth interrupting anything over.
    }
  };
  // EventSource reconnects on its own; refresh the fuller picture when it does.
  source.onerror = () => setTimeout(refreshState, 4000);
}

/* ---------- apps ---------- */

async function loadApps() {
  try {
    const { apps } = await api('/api/keys');
    const container = $('apps');
    container.replaceChildren(
      ...apps.map(({ id, name }) => {
        const button = document.createElement('button');
        button.className = 'pill';
        button.type = 'button';
        button.textContent = name;
        button.addEventListener('click', () => {
          buzz();
          enqueue(() => api('/api/app', { appId: id }));
        });
        return button;
      }),
    );
  } catch {
    // The shortcuts are a convenience; the rest of the remote works without.
  }
}

/* ---------- setup sheet ---------- */

function openSettings() {
  $('settings').hidden = false;
}

function closeSettings() {
  $('settings').hidden = true;
}

$('openSettings').addEventListener('click', openSettings);
$('closeSettings').addEventListener('click', closeSettings);
$('settings').addEventListener('click', (event) => {
  if (event.target === $('settings')) closeSettings();
});

$('scanBtn').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  const results = $('scanResults');
  button.disabled = true;
  button.textContent = 'Looking…';
  results.replaceChildren();
  try {
    const { found } = await api('/api/discover');
    if (!found.length) {
      toast('No TV answered. Check it is on and on this Wi-Fi.', true);
    }
    results.replaceChildren(
      ...found.map((tv) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.innerHTML = '';
        const title = document.createElement('strong');
        title.textContent = tv.name;
        const detail = document.createElement('small');
        detail.textContent = [tv.model, tv.ip].filter(Boolean).join(' · ');
        button.append(title, detail);
        button.addEventListener('click', () => {
          $('hostInput').value = tv.ip;
          if (tv.mac) $('macInput').value = tv.mac;
          toast(`Selected ${tv.name}`);
        });
        return button;
      }),
    );
  } catch (err) {
    toast(err.message, true);
  } finally {
    button.disabled = false;
    button.textContent = 'Find my TV';
  }
});

$('saveBtn').addEventListener('click', async () => {
  try {
    await api('/api/config', { host: $('hostInput').value.trim(), mac: $('macInput').value.trim() });
    toast('Saved');
    await refreshState();
  } catch (err) {
    toast(err.message, true);
  }
});

$('pairBtn').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = 'Look at the TV…';
  try {
    await api('/api/pair', {});
    toast('Paired');
    closeSettings();
  } catch (err) {
    toast(err.message, true);
  } finally {
    button.disabled = false;
    button.textContent = 'Pair with the TV';
    refreshState();
  }
});

$('forgetBtn').addEventListener('click', async () => {
  try {
    await api('/api/forget', {});
    toast('Pairing forgotten');
    refreshState();
  } catch (err) {
    toast(err.message, true);
  }
});

/* ---------- typing ---------- */

$('typeForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const input = $('typeInput');
  const text = input.value;
  if (!text) return;
  try {
    await api('/api/text', { text });
    input.value = '';
    buzz();
    toast('Sent');
  } catch (err) {
    toast(err.message, true);
  }
});

/* ---------- start ---------- */

refreshState();
loadApps();
listenForStateChanges();
setInterval(refreshState, 20_000);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) refreshState();
});
