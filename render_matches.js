const puppeteer = require('puppeteer');
const fs = require('fs');

async function render() {
  const input = JSON.parse(fs.readFileSync(0, 'utf-8'));
  const { matches, tier_filter = 'T3', title_suffix = '' } = input;

  const tierRank = (t) => ({ T1: 1, T2: 2, T3: 3, Other: 4 }[t] || 5);
  const maxRank = tierRank(tier_filter);

  const filtered = matches.filter((m) => tierRank(m._tier || 'Other') <= maxRank);

  const tierTitles = {
    T1: '🔥 Tier 1 / Major & Big Events',
    T2: '⚡ Tier 2 / Challenger & Circuit',
    T3: '🎯 Tier 3 / Qualifiers & Cups',
    Other: '▫️ Other Matches',
  };

  const grouped = {};
  for (const m of filtered) {
    const t = m._tier || 'Other';
    if (!grouped[t]) grouped[t] = [];
    grouped[t].push(m);
  }

  const sortedTiers = Object.keys(grouped).sort((a, b) => tierRank(a) - tierRank(b));

  let htmlContent = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #14171e;
    color: #e2e8f0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 13px;
    width: 440px;
    padding: 12px 14px 8px 14px;
    display: inline-block;
  }
  .header {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    border-bottom: 2px solid #2d3748;
    padding-bottom: 6px;
    margin-bottom: 8px;
  }
  .header-title {
    font-size: 15px;
    font-weight: 700;
    color: #fff;
    letter-spacing: 0.3px;
  }
  .header-sub {
    font-size: 11px;
    color: #718096;
  }
  .tier-sec {
    margin-top: 8px;
  }
  .tier-hdr {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    color: #a0aec0;
    margin-bottom: 4px;
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .tier-hdr.T1 { color: #f56565; }
  .tier-hdr.T2 { color: #ecc94b; }
  .tier-hdr.T3 { color: #4299e1; }
  .tier-hdr.Other { color: #a0aec0; }
  .table {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .row {
    background: #1e232d;
    border-radius: 4px;
    padding: 5px 8px;
    display: flex;
    align-items: center;
    border: 1px solid #28303d;
  }
  .row.live {
    border-color: #e53e3e;
    background: #251b20;
  }
  .time-col {
    width: 46px;
    font-size: 11px;
    font-weight: 600;
    color: #a0aec0;
  }
  .time-col.live {
    color: #fc8181;
  }
  .match-col {
    flex: 1;
    display: flex;
    align-items: center;
    gap: 6px;
    overflow: hidden;
  }
  .team {
    font-weight: 600;
    color: #fff;
    font-size: 12px;
    white-space: nowrap;
  }
  .vs {
    font-size: 10px;
    color: #718096;
  }
  .event-tag {
    font-size: 10px;
    color: #718096;
    margin-left: 4px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 120px;
  }
  .stars {
    color: #ecc94b;
    font-size: 10px;
    margin-left: auto;
    padding-right: 6px;
  }
  .id-col {
    font-family: ui-monospace, monospace;
    font-size: 11px;
    color: #63b3ed;
    font-weight: 500;
  }
  .footer {
    text-align: center;
    font-size: 10px;
    color: #4a5568;
    margin-top: 8px;
  }
</style>
</head>
<body>
  <div class="header">
    <div class="header-title">HLTV MATCHES</div>
    <div class="header-sub">UTC+8 · ${tier_filter}</div>
  </div>
`;

  if (filtered.length === 0) {
    htmlContent += `<div style="text-align:center;padding:20px;color:#718096;">No matches found for ${tier_filter}</div>`;
  } else {
    for (const t of sortedTiers) {
      htmlContent += `
      <div class="tier-sec">
        <div class="tier-hdr ${t}">${tierTitles[t] || t}</div>
        <div class="table">
      `;
      for (const m of grouped[t]) {
        const isLive = m.live === '1';
        const starsStr = m.stars > 0 ? '★'.repeat(Number(m.stars)) : '';
        htmlContent += `
          <div class="row ${isLive ? 'live' : ''}">
            <div class="time-col ${isLive ? 'live' : ''}">${isLive ? '🔴 LIVE' : (m.time || '--:--')}</div>
            <div class="match-col">
              <span class="team">${m.team1 || '?'}</span>
              <span class="vs">vs</span>
              <span class="team">${m.team2 || '?'}</span>
              <span class="event-tag">${m.event || ''}</span>
            </div>
            ${starsStr ? `<div class="stars">${starsStr}</div>` : ''}
            <div class="id-col">#${m.id}</div>
          </div>
        `;
      }
      htmlContent += `</div></div>`;
    }
  }

  htmlContent += `
    <div class="footer">/watch &lt;id&gt; to stream live scorebot</div>
  </body></html>`;

  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 440, height: 100, deviceScaleFactor: 2 });
  await page.setContent(htmlContent, { waitUntil: 'domcontentloaded' });
  const bodyHandle = await page.$('body');
  const imageBuffer = await bodyHandle.screenshot({ type: 'png' });
  await browser.close();

  process.stdout.write(imageBuffer);
}

render().catch((err) => {
  console.error(err);
  process.exit(1);
});
