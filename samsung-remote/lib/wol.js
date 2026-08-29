'use strict';

// Wake-on-LAN. The remote-control channel can only reach a TV that is already
// awake, so turning a fully powered-down set back on means a magic packet.

const dgram = require('node:dgram');
const os = require('node:os');

const MAC_PATTERN = /^([0-9a-f]{2})[:-]?([0-9a-f]{2})[:-]?([0-9a-f]{2})[:-]?([0-9a-f]{2})[:-]?([0-9a-f]{2})[:-]?([0-9a-f]{2})$/i;

function parseMac(mac) {
  const match = MAC_PATTERN.exec(String(mac).trim());
  if (!match) throw new Error(`not a MAC address: ${mac}`);
  return Buffer.from(match.slice(1).map((byte) => parseInt(byte, 16)));
}

function magicPacket(mac) {
  const address = parseMac(mac);
  const packet = Buffer.alloc(6 + 16 * 6, 0xff);
  for (let i = 0; i < 16; i++) address.copy(packet, 6 + i * 6);
  return packet;
}

// Every IPv4 broadcast address this machine can see, so the packet reaches the
// TV whichever interface shares its network.
function broadcastAddresses() {
  const addresses = new Set(['255.255.255.255']);
  for (const entries of Object.values(os.networkInterfaces())) {
    for (const entry of entries ?? []) {
      if (entry.family !== 'IPv4' || entry.internal || !entry.netmask) continue;
      const ip = entry.address.split('.').map(Number);
      const mask = entry.netmask.split('.').map(Number);
      if (ip.length !== 4 || mask.length !== 4) continue;
      addresses.add(ip.map((octet, i) => (octet & mask[i]) | (~mask[i] & 0xff)).join('.'));
    }
  }
  return [...addresses];
}

// Ports 9 (discard) and 7 (echo) are both conventional for WoL; TVs differ.
async function wake(mac, { ports = [9, 7], targets = broadcastAddresses() } = {}) {
  const packet = magicPacket(mac);
  const socket = dgram.createSocket({ type: 'udp4', reuseAddr: true });

  await new Promise((resolve, reject) => {
    socket.once('error', reject);
    socket.bind(() => {
      socket.removeListener('error', reject);
      resolve();
    });
  });

  socket.setBroadcast(true);
  let sent = 0;
  try {
    for (const target of targets) {
      for (const port of ports) {
        await new Promise((resolve) => {
          socket.send(packet, port, target, (err) => {
            if (!err) sent++;
            resolve(); // A dead interface shouldn't stop the others.
          });
        });
      }
    }
  } finally {
    socket.close();
  }

  if (sent === 0) throw new Error('could not send the wake-up packet on any interface');
  return { sent, targets, ports };
}

module.exports = { wake, magicPacket, parseMac, broadcastAddresses };
