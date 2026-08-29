'use strict';

// Finding the TV on the network, so nobody has to go digging through the
// router's DHCP table. Two passes run together: an SSDP shout, which most sets
// answer instantly, and a sweep of the local subnet for anything serving the
// Samsung device document on port 8001.

const dgram = require('node:dgram');
const os = require('node:os');
const { fetchDeviceInfo } = require('./tv');

const SSDP_ADDRESS = '239.255.255.250';
const SSDP_PORT = 1900;
const SSDP_TARGETS = [
  'urn:samsung.com:device:RemoteControlReceiver:1',
  'urn:dial-multiscreen-org:service:dial:1',
];

const ipToInt = (ip) => ip.split('.').reduce((acc, octet) => (acc << 8 >>> 0) + Number(octet), 0) >>> 0;
const intToIp = (value) => [24, 16, 8, 0].map((shift) => (value >>> shift) & 0xff).join('.');

// Candidate addresses on our own networks. A /16 has too many hosts to walk,
// so anything wider than a /22 falls back to the /24 around this machine.
function candidateAddresses() {
  const candidates = new Set();
  for (const entries of Object.values(os.networkInterfaces())) {
    for (const entry of entries ?? []) {
      if (entry.family !== 'IPv4' || entry.internal || !entry.netmask) continue;
      const self = ipToInt(entry.address);
      const mask = ipToInt(entry.netmask);
      const size = (~mask >>> 0) + 1;
      const [network, hosts] = size > 1024
        ? [(self & ipToInt('255.255.255.0')) >>> 0, 256]
        : [(self & mask) >>> 0, size];
      for (let offset = 1; offset < hosts - 1; offset++) {
        const address = intToIp((network + offset) >>> 0);
        if (address !== entry.address) candidates.add(address);
      }
    }
  }
  return [...candidates];
}

function looksLikeSamsungTv(info) {
  if (!info || typeof info !== 'object') return false;
  const type = String(info.type ?? info.device?.type ?? '');
  return /samsung/i.test(type) || String(info.device?.OS ?? '') === 'Tizen';
}

function summarise(ip, info) {
  const device = info.device ?? {};
  return {
    ip,
    name: info.name ?? device.name ?? 'Samsung TV',
    model: device.modelName ?? device.model ?? null,
    mac: device.wifiMac ?? null,
    powerState: device.PowerState ?? null,
    tokenAuth: device.TokenAuthSupport === 'true',
    frameTv: device.FrameTVSupport === 'true',
  };
}

async function probeAll(addresses, { timeoutMs, concurrency = 48 }) {
  const found = new Map();
  const queue = [...addresses];

  const worker = async () => {
    for (;;) {
      const address = queue.shift();
      if (!address) return;
      const info = await fetchDeviceInfo(address, timeoutMs);
      if (looksLikeSamsungTv(info)) found.set(address, summarise(address, info));
    }
  };

  await Promise.all(Array.from({ length: Math.min(concurrency, queue.length) }, worker));
  return found;
}

// Shout on the multicast group and collect whoever answers.
function ssdpResponders(timeoutMs) {
  return new Promise((resolve) => {
    const responders = new Set();
    let socket;
    try {
      socket = dgram.createSocket({ type: 'udp4', reuseAddr: true });
    } catch {
      return resolve(responders);
    }

    const finish = () => {
      try {
        socket.close();
      } catch {
        // Already closed.
      }
      resolve(responders);
    };

    socket.on('error', finish);
    socket.on('message', (message, rinfo) => {
      const text = message.toString('latin1');
      if (/samsung|dial-multiscreen/i.test(text)) responders.add(rinfo.address);
    });

    socket.bind(() => {
      try {
        socket.setBroadcast(true);
        for (const target of SSDP_TARGETS) {
          const search = [
            'M-SEARCH * HTTP/1.1',
            `HOST: ${SSDP_ADDRESS}:${SSDP_PORT}`,
            'MAN: "ssdp:discover"',
            'MX: 1',
            `ST: ${target}`,
            '',
            '',
          ].join('\r\n');
          socket.send(Buffer.from(search), SSDP_PORT, SSDP_ADDRESS);
        }
      } catch {
        return finish();
      }
      const timer = setTimeout(finish, timeoutMs);
      if (timer.unref) timer.unref();
    });
  });
}

async function discover({ timeoutMs = 6_000, probeTimeoutMs = 1_500 } = {}) {
  const [ssdp, swept] = await Promise.all([
    ssdpResponders(Math.min(2_500, timeoutMs)).then((addresses) =>
      probeAll([...addresses], { timeoutMs: probeTimeoutMs }),
    ),
    probeAll(candidateAddresses(), { timeoutMs: probeTimeoutMs }),
  ]);

  const merged = new Map([...swept, ...ssdp]);
  return [...merged.values()].sort((a, b) => ipToInt(a.ip) - ipToInt(b.ip));
}

module.exports = { discover, candidateAddresses, looksLikeSamsungTv, summarise, ipToInt, intToIp };
