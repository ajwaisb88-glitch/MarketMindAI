/* eslint-disable no-console */
const fs = require('fs');
const path = require('path');

const buildDir = path.resolve(__dirname, '..', 'dist-build');
const unpackedDir = path.join(buildDir, 'win-unpacked');
const installer = fs.readdirSync(buildDir).find((name) => /^MarketMind AI Setup .*\.exe$/i.test(name));
const backend = path.join(unpackedDir, 'resources', 'backend', 'marketmind-backend.exe');

for (const requiredPath of [path.join(buildDir, installer || ''), backend]) {
  if (!installer || !fs.existsSync(requiredPath)) {
    throw new Error(`Missing packaged output: ${requiredPath || 'Windows installer'}`);
  }
}

console.log(`Verified installer: ${installer}`);
console.log(`Verified bundled backend: ${backend}`);