// Disposable browser fixture. Never uses the household CSV or production passphrase.
import fs from 'node:fs';
import path from 'node:path';
import { protect, root } from './protect.mjs';
const directory = path.join(root, '.local/access-qa');
fs.mkdirSync(path.join(directory, 'data'), { recursive: true });
const funds = JSON.parse(fs.readFileSync(path.join(root, 'config/funds.json')));
const positions = funds.funds.map(fund => ({ ticker: fund.ticker, owner: 'Kim', shares: 1 }));
const html = await protect(positions, 'next-chapter-test-passphrase', '00112233445566778899aabbccddeeff');
fs.writeFileSync(path.join(directory, 'index.html'), html);
for (const name of ['styles.css', 'app.mjs', 'portfolio.mjs', 'icons.mjs']) fs.copyFileSync(path.join(root, 'src', name), path.join(directory, name));
fs.copyFileSync(path.join(root, 'data/market.json'), path.join(directory, 'data/market.json'));
fs.copyFileSync(path.join(root, 'config/funds.json'), path.join(directory, 'data/funds.json'));
console.log('Prepared ignored synthetic access fixture. All test holdings have one share.');
