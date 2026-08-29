'use strict';

// Home-screen icons, drawn rather than checked in as binaries nobody can edit.
// Run `npm run icons` after changing the design.

const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');

const BACKGROUND = [0x12, 0x15, 0x1b];
const GLYPH = [0x3b, 0x82, 0xf6];
const SAMPLES = 3; // Supersampling, so the curves don't come out jagged.

// Coverage of the power glyph — a broken ring with a stem through the gap —
// at one sample point, in units where the icon is 1x1.
function glyphAt(x, y) {
  const dx = x - 0.5;
  const dy = y - 0.5;
  const distance = Math.hypot(dx, dy);
  const radius = 0.28;
  const thickness = 0.085;

  const stemHalfWidth = thickness / 2;
  const onStem = Math.abs(dx) <= stemHalfWidth && dy >= -radius - thickness * 0.75 && dy <= -radius * 0.30;
  if (onStem) return true;

  const onRing = Math.abs(distance - radius) <= thickness / 2;
  if (!onRing) return false;

  // Leave a gap at the top for the stem to sit in.
  const gapHalfWidth = thickness * 1.35;
  const inGap = dy < 0 && Math.abs(dx) <= gapHalfWidth;
  return !inGap;
}

function renderRgba(size) {
  const pixels = Buffer.alloc(size * size * 4);
  const step = 1 / (size * SAMPLES);

  for (let py = 0; py < size; py++) {
    for (let px = 0; px < size; px++) {
      let hits = 0;
      for (let sy = 0; sy < SAMPLES; sy++) {
        for (let sx = 0; sx < SAMPLES; sx++) {
          const x = (px * SAMPLES + sx + 0.5) * step;
          const y = (py * SAMPLES + sy + 0.5) * step;
          if (glyphAt(x, y)) hits++;
        }
      }
      const coverage = hits / (SAMPLES * SAMPLES);
      const offset = (py * size + px) * 4;
      for (let channel = 0; channel < 3; channel++) {
        pixels[offset + channel] = Math.round(
          BACKGROUND[channel] + (GLYPH[channel] - BACKGROUND[channel]) * coverage,
        );
      }
      pixels[offset + 3] = 0xff;
    }
  }
  return pixels;
}

// zlib.crc32 arrived in Node 22.2; fall back so older runtimes can still
// regenerate the icons.
const crc32 = typeof zlib.crc32 === 'function' ? zlib.crc32 : (() => {
  const table = Uint32Array.from({ length: 256 }, (_, index) => {
    let value = index;
    for (let bit = 0; bit < 8; bit++) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
    return value >>> 0;
  });
  return (buffer) => {
    let crc = 0xffffffff;
    for (const byte of buffer) crc = table[(crc ^ byte) & 0xff] ^ (crc >>> 8);
    return (crc ^ 0xffffffff) >>> 0;
  };
})();

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, 'latin1'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body) >>> 0);
  return Buffer.concat([length, body, crc]);
}

function encodePng(size, rgba) {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(size, 0);
  header.writeUInt32BE(size, 4);
  header[8] = 8; // bit depth
  header[9] = 6; // truecolour with alpha
  // bytes 10-12 stay zero: deflate, adaptive filtering, no interlace.

  const stride = size * 4;
  const raw = Buffer.alloc((stride + 1) * size);
  for (let row = 0; row < size; row++) {
    raw[row * (stride + 1)] = 0; // filter type: none
    rgba.copy(raw, row * (stride + 1) + 1, row * stride, (row + 1) * stride);
  }

  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', header),
    chunk('IDAT', zlib.deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

if (require.main === module) {
  const outDir = path.join(__dirname, '..', 'public');
  for (const size of [192, 512]) {
    const file = path.join(outDir, `icon-${size}.png`);
    fs.writeFileSync(file, encodePng(size, renderRgba(size)));
    console.log(`wrote ${path.relative(process.cwd(), file)}`);
  }
}

module.exports = { encodePng, renderRgba, glyphAt };
