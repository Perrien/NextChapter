# The Next Chapter

A weather-style portfolio dashboard with shared-passphrase protection, saved market prices, and GitHub Pages deployment.

Site: https://perrien.github.io/NextChapter/  
Repository: https://github.com/Perrien/NextChapter

## Automatic and on-demand updates

The target download times are **11:15 AM, 2:15 PM, and 9:15 PM America/Chicago, Monday–Friday**. The workflow uses explicit UTC timers covering both Central offsets; Python decides which Central-time slot is actually due. This preserves local times across daylight saving changes without relying on GitHub's optional `timezone` field. GitHub schedules are best effort; market holidays can return unchanged quotes.

Each slot has a catch-up check at **:45**, and the extra UTC-offset checks provide further opportunities to recover a missed slot. A lightweight job checks live publication metadata against the most recent due weekday slot, including the previous evening before the first daytime update and across weekends. It skips an already published slot, so the extra checks normally make no provider download or deployment. A repository data commit alone is insufficient, because deployment may have failed afterward. Missing or unreadable publication metadata allows an update. Manual runs and source pushes always proceed. Logs include the original UTC cron and actual Central check time. GitHub may still delay or drop timer events; this mitigation does not guarantee precise timing.

For a fresh download, open **Data & updates → Update prices now**, sign in to GitHub if necessary, and choose **Run workflow** on `main`. You need repository write access to start jobs. The site passphrase gives portfolio access, not GitHub permissions. After the run finishes, **Reload saved prices** reads the newly published files. The open dashboard also checks saved site files every five minutes while visible and when returning to the tab.

Scheduled and manual runs download public ticker data, validate all securities and the encrypted page, build an allowlisted site, commit **only `data/market.json`** for durable storage, and deploy the Pages artifact. A failure stops publication and leaves the last good site available. Jobs share a concurrency group. Bot data commits do not trigger another deployment workflow. Code pushes to `main` validate and deploy the saved snapshot without requesting another Yahoo download.

The workflow uses GitHub's automatically issued token; it does not need the household CSV, unlock key, shared passphrase, a personal access token, or repository secrets. The footer separates source-close dates, download time, and site snapshot publication time. `data/publication.json` includes a public snapshot fingerprint and workflow-run URL for verification.

## Run locally

Use Python 3.10+ and Node.js 20+. Install the pinned build dependency once, then choose the shared passphrase in your own terminal:

```sh
cd next-chapter
npm ci --ignore-scripts
npm run setup:access
npm run dev
```

Open http://127.0.0.1:4174/ . Setup asks for the passphrase twice with hidden input. The minimum is 6 characters, as requested; longer passphrases resist guessing better. Neither the passphrase nor an unlock key is saved to a file or printed. Setup reads `../Portfolio.csv`, embeds the holdings in the dashboard HTML in memory, encrypts it with StatiCrypt, and builds the protected site. The CSV, screenshots, test output, and any private copies must stay out of public Git history. There is no plaintext holdings file in the served build.

Before initial setup, `npm run preview:setup` can display the entry-page design and setup reminder without any personal content. A normal build refuses to proceed without a protected page. The current development server can remain running through rebuilds.

## Shared access

- Enter the shared passphrase to open the portfolio. It is checked by decrypting the personal page locally in the browser; no password is submitted to a server.
- **Remember this device for 30 days** is unchecked initially. It saves a derived unlock key in that browser, not the plaintext passphrase. Anyone using that browser can then open the page without entering the passphrase until it expires or is locked.
- **Lock portfolio** in the header removes this site's remembered key and replaces the open dashboard with the entry page. Reloading stays locked. Without Remember, a reload asks for the passphrase again.
- Share the eventual site link and shared passphrase. There are no separate users, account permissions, or reset emails. Keep your passphrase in a password manager or another place you can find it.
- To change holdings, edit `../Portfolio.csv` and run `npm run setup:access` again, entering the same passphrase. To change the passphrase, run that command and choose a new one. Saved old keys stop opening the new encrypted page. People with an old downloaded copy can still unlock that old copy; static encryption cannot revoke it.

After changing holdings or the passphrase locally, publish only the newly protected files:

```sh
git add protected/index.html protected/manifest.json config/access.json
git commit -m "Update encrypted portfolio"
git push
```

That push runs the deployment workflow. Editing the local CSV alone does not change the live site; the CSV stays outside this Git repository. To receive automated price commits before making other changes, use `git pull --ff-only` while the checkout is clean.

The implementation uses pinned [StatiCrypt 3.5.4](https://github.com/robinmoisson/staticrypt), including its unchanged authenticated encryption codec and browser engine, with a custom entry-page template. WebCrypto requires HTTPS or localhost. The salt in `config/access.json` is public and is retained across rebuilds so remembered access survives ordinary holdings updates. It is safe to publish the encrypted `protected/index.html`, its generic manifest, and that public salt. The raw CSV and passphrase must never be published.

## Refresh prices

`npm run update:data` downloads public ticker prices to `data/market.json`; no owner names or share counts are sent. The first run gets two years. Later runs refresh a month, reconcile adjustments using overlapping observations, and fall back to a full reload if corrections are inconsistent. Use `python3 scripts/update_data.py --full` to force a full reconciliation. Output replaces the previous snapshot only after the complete update validates. An HTTP/provider failure retains the prior file.

After downloading, run `npm run build`. This copies the saved public prices and already-encrypted personal page into a fresh allowlisted output tree. It needs neither the CSV nor the passphrase, so future GitHub price jobs can run without either. A local CSV change or an HTML-template change requires `npm run setup:access` instead. Generic JS/CSS and price updates do not require re-encryption.

Use **Data & updates → Reload saved prices** on the open dashboard after a download/build. That button reads saved site files and makes no Yahoo request. **Update prices now** opens the real GitHub workflow as described above. A full page reload obtains newly protected holdings.

## What is wired

- Current share-price valuations, actual source dates, and owner/sector reconciliation.
- Today (latest trading day), this week, this month, and trailing-year comparisons.
- Joint / Kim / Ashley selection inside the one portfolio card.
- Seasonal weather, holdings details, a weighted heat map, and actual growth history.
- Actual trailing-year growth for milestone pace and the $10,000/month spending scenario.
- Intraday estimates aligned to the last fund NAV date; direct stock/ETF quotes use their own prices. A published fund close is never moved a second time using that same day's proxy change.
- Source loading/error states and in-memory retention of the last good snapshot if a reload fails.
- Encrypted entry screen, optional 30-day remembered access, and a Lock control.

## What the history means

Current value is **current shares × actual latest price**. Historical **growth** uses Yahoo Adjusted Close, including distributions, and is normalized to current value. It assumes the current investment basket was held throughout with payouts reinvested. It is not a record of actual historical account balances or cash flows. The page states this next to the chart and in **About these numbers**.

For a holding with current value V, latest published adjusted price A, any subsequent total-return proxy factor F, and historical adjusted price H:

`normalized historical value = V × H / (A × F)`

The difference between current value and this comparison value supplies investment change. This avoids counting an ex-distribution share-price drop as an investment loss, but the normalized starting value is not a literal historical share-price valuation. Annual projection growth uses completed common closes, independently of intraday estimates and the selected display period.

The spending scenario withdraws at the **start of each month**, then compounds the remainder at the monthly equivalent of the observed annual rate. The editable defaults are **$10,000/month living costs**, **$1,500/month extra healthcare until age 65**, and a **10% effective tax rate on withdrawals**. Dollar controls step by $500 and display thousands separators; the tax control steps by one percentage point (0–99%). Healthcare can be set to zero. Both living costs and healthcare rise at **2.5% per year**, compounded monthly: `cost in month n = starting cost × 1.025^(n/12)`, where the first month is n = 0. Each gross withdrawal is `(living costs + applicable healthcare) / (1 − tax rate)`; for example, $11,500 of costs requires $12,777.78 at 10% tax. Extra healthcare stops in **January 2040**, the calendar year of turning 65, using the existing birth-year assumption of 1975 and Central time. Any healthcare after 65 must be part of regular spending. The simulation uses the mathematically equivalent inflation-adjusted monthly growth factor `((1 + annual return) / 1.025)^(1/12)` with starting-dollar withdrawals, avoiding double-counted inflation. It excludes new deposits and uneven returns. `50+ years` is a display horizon, not a guarantee of perpetual sustainability.

The duration's subtitle shows **To about age 86**, for example, or **Beyond age 101** for the current 50-year cap. Ages assume turning 50 in 2025 (a 1975 birth year) and use the projected calendar year at the end of the calculated duration. No exact birthday is assumed. The age advances with the calendar rather than being fixed to today's age.

## Source verification

`config/funds.json` contains verified issuer identities, sector groups, proxy choices, and source URLs. Index-fund proxies follow closely related benchmarks. MIEIX, PJSQX, and NERNX use explicitly approximate proxies because they are actively managed. PJSQX uses SMMD to match its Russell 2500 benchmark. Proxy selection is an estimate, not a claim by an issuer that prices will match intraday.

Apple's issuer-hosted price page independently displayed the November 13, 2026 close of $356.27, matching the downloaded Yahoo value to cents. It uses Tickertech data: https://investor.apple.com/stock-price/default.aspx . VBTIX and VFFSX were not independently verified on a readable dated issuer page; their values should be compared with a brokerage statement before publication. Yahoo access remains unofficial and subject to its usage terms.

## Checks

```sh
npm test
npm run verify:local
npm run verify:public
npm run verify:artifact
```

The 43 focused tests cover distribution-adjusted growth, proxy anchoring, avoiding duplicate same-day movement, cent rounding in history, date boundaries, owner reconciliation, missing-data rejection, withdrawal mathematics including monthly compounded inflation, tax gross-up, and the age-65 healthcare cutoff, projected ages and capped subtitles, milestone edge cases, historical adjustment reconciliation, published-price precision, retaining a prior snapshot after failed refreshes, wrong-key/tampered-ciphertext rejection, remembered-key compatibility, hidden setup input, rejecting stale personal inputs, excluding legacy plaintext files from the built site, and refresh decisions across midnight, weekends, and daylight saving changes. `verify:local` additionally reconciles the original local CSV against owner and sector totals for every period and saves an ignored `.local/verification.json` report. Official closing prices use the provider's published decimal precision; adjusted prices retain their calculation precision.

Browser checks exercised wrong and correct passphrases, reload with and without Remember, Lock followed by reload, external app modules after decryption, and the 320-pixel layout. These used disposable one-share holdings and a test-only credential, not the real household passphrase.

`verify:public` and `verify:artifact` run without the CSV and are used on GitHub's runner. The artifact check enforces an exact list of allowed files, encrypted personal HTML, and a market-data fingerprint. The local commands above do not publish anything; Git publication uses ordinary commits and pushes from this `next-chapter/` repository.

Official workflow references: [Pages custom workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages), [timezone-aware schedules](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule), and [token-trigger behavior](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).
