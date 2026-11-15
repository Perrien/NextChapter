import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { protect, root, loginPage } from '../scripts/protect.mjs';
const require = createRequire(import.meta.url);
const engine = require('staticrypt/lib/cryptoEngine.js');
const codec = require('staticrypt/lib/codec.js').init(engine);
const funds = JSON.parse(fs.readFileSync(`${root}/config/funds.json`)).funds;
const positions = funds.map(fund => ({ ticker: fund.ticker, shares: 1, owner: 'Kim' }));
// Disposable fixture credential, used only with synthetic one-share test holdings.
const passphrase = 'next-chapter-test-passphrase';
const salt = '00112233445566778899aabbccddeeff';
const extract = html => JSON.parse(html.match(/const config = (\{[^\n]+\});/)[1]);

test('personal HTML is encrypted, authenticated, and only unlocks with the matching passphrase', async () => {
  const html = await protect(positions, passphrase, salt);
  assert.ok(!html.includes('id="private-holdings"'));
  assert.ok(!html.includes('"shares":1'));
  assert.ok(!html.includes(passphrase));
  const config = extract(html);
  assert.equal(config.rememberDurationInDays, 30);
  const key = await engine.hashPassword(passphrase, salt);
  const decoded = await codec.decode(config.staticryptEncryptedMsgUniqueVariableName, key, salt);
  assert.equal(decoded.success, true);
  assert.ok(decoded.decoded.includes('id="private-holdings"'));
  assert.ok(decoded.decoded.includes('"shares":1'));
  assert.ok(!decoded.decoded.includes('./data/holdings.json'));
  const wrongKey = await engine.hashPassword('different-test-passphrase', salt);
  assert.equal((await codec.decode(config.staticryptEncryptedMsgUniqueVariableName, wrongKey, salt)).success, false);
  const tampered = config.staticryptEncryptedMsgUniqueVariableName.slice(0, -1) + (config.staticryptEncryptedMsgUniqueVariableName.endsWith('0') ? '1' : '0');
  assert.equal((await codec.decode(tampered, key, salt)).success, false);
});

test('re-protecting with the same salt keeps remembered unlock keys compatible', async () => {
  const first = extract(await protect(positions, passphrase, salt));
  const updated = positions.map(position => ({ ...position, shares: 2 }));
  const second = extract(await protect(updated, passphrase, salt));
  assert.notEqual(first.staticryptEncryptedMsgUniqueVariableName, second.staticryptEncryptedMsgUniqueVariableName);
  const key = await engine.hashPassword(passphrase, salt);
  assert.equal((await codec.decode(second.staticryptEncryptedMsgUniqueVariableName, key, salt)).success, true);
});

test('unconfigured preview contains no personal page or encryption key', () => {
  const html = loginPage();
  assert.ok(html.includes('const config = null;'));
  assert.ok(!html.includes('id="private-holdings"'));
  assert.ok(!html.includes('"shares":'));
});

test('shared access accepts six characters and refuses shorter passphrases or malformed salts', async () => {
  await assert.rejects(protect(positions, 'short', salt), /6 characters/);
  assert.ok(extract(await protect(positions, 'abc123', salt)).staticryptEncryptedMsgUniqueVariableName);
  await assert.rejects(protect(positions, passphrase, 'bad-salt'), /salt/);
});
