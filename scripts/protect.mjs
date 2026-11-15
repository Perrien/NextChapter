// Use StatiCrypt's unchanged codec and browser engine. No plaintext temporary HTML.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { preparePortfolio } from '../src/portfolio.mjs';
const require = createRequire(import.meta.url);
const cryptoEngine = require('staticrypt/lib/cryptoEngine.js');
const codec = require('staticrypt/lib/codec.js').init(cryptoEngine);
const { buildStaticryptJS } = require('staticrypt/cli/helpers.js');
export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const templateHash = () => createHash('sha256').update(fs.readFileSync(path.join(root, 'src/index.html'))).update(fs.readFileSync(path.join(root, 'src/login.html'))).digest('hex');
export function loginPage(config = null, salt = '') {
  const values = {
    js_staticrypt: config ? buildStaticryptJS() : 'null',
    staticrypt_config: JSON.stringify(config),
    storage_prefix: JSON.stringify(`nextchapter:${salt}:`)
  };
  return fs.readFileSync(path.join(root, 'src/login.html'), 'utf8').replace(/\/\*\[\|(\w+)\|\]\*\/\s*0/g, (_, key) => {
    if (!(key in values)) throw new Error(`Unknown login template key: ${key}`);
    return values[key];
  });
}
export async function protect(positions, passphrase, salt) {
  if (typeof passphrase !== 'string' || passphrase.length < 6) throw new Error('Use a shared passphrase of at least 6 characters');
  if (!/^[a-f0-9]{32}$/.test(salt)) throw new Error('Invalid encryption salt');
  // Validate the full basket before protecting it.
  preparePortfolio(JSON.parse(fs.readFileSync(path.join(root, 'data/market.json'))), positions, JSON.parse(fs.readFileSync(path.join(root, 'config/funds.json'))).funds);
  const personal = JSON.stringify({ schema_version: 1, positions }).replace(/</g, '\\u003c');
  const html = fs.readFileSync(path.join(root, 'src/index.html'), 'utf8').replace('<!--PRIVATE_HOLDINGS-->', `<script type="application/json" id="private-holdings">${personal}</script>`);
  const encrypted = await codec.encode(html, passphrase, salt);
  return loginPage({ staticryptEncryptedMsgUniqueVariableName: encrypted, staticryptSaltUniqueVariableName: salt, isRememberEnabled: true, rememberDurationInDays: 30 }, salt);
}
async function main() {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const configPath = path.join(root, 'config/access.json');
  const salt = fs.existsSync(configPath) ? JSON.parse(fs.readFileSync(configPath)).salt : cryptoEngine.generateRandomSalt();
  const output = await protect(input.positions, input.passphrase, salt);
  const directory = path.join(root, 'protected');
  fs.mkdirSync(directory, { recursive: true });
  // Only ciphertext, public salt, and generic template checksums are persisted.
  fs.writeFileSync(path.join(directory, 'index.html.tmp'), output);
  fs.renameSync(path.join(directory, 'index.html.tmp'), path.join(directory, 'index.html'));
  fs.writeFileSync(configPath, JSON.stringify({ schema_version: 1, salt }, null, 2) + '\n');
  fs.writeFileSync(path.join(directory, 'manifest.json'), JSON.stringify({ schema_version: 1, template_hash: templateHash() }, null, 2) + '\n');
  console.log('Shared access prepared. Only the encrypted page was saved; the passphrase was not saved.');
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { await main(); } catch (_) { console.error('Could not prepare shared access. Check the CSV, saved prices, and passphrase length. The previous protected page was retained where possible.'); process.exitCode = 1; }
}
