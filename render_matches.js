const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

// Color palette for badge icons by initial letter
const BADGE_COLORS = [
  { bg: '#2b3945', text: '#90cdf4' }, // Blue
  { bg: '#3b2f45', text: '#d6bcfa' }, // Purple
  { bg: '#2f3e35', text: '#9ae6b4' }, // Green
  { bg: '#45382b', text: '#fbd38d' }, // Orange
  { bg: '#452b2b', text: '#feb2b2' }, // Red
  { bg: '#2b3f3e', text: '#81e6d9' }, // Teal
];

function getBadgeStyle(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash << 5) - hash + name.charCodeAt(i);
  }
  const idx = Math.abs(hash) % BADGE_COLORS.length;
  return BADGE_COLORS[idx];
}

function getInitials(name) {
  const clean = (name || '').replace(/[^a-zA-Z0-9]/g, '');
  if (!clean) return '?';
  if (clean.length <= 3) return clean.toUpperCase();
  return clean.slice(0, 2).toUpperCase();
}

function renderTeamIcon(name) {
  const norm = (name || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  const logoDir = path.join(__dirname, 'hltv_bot', 'assets', 'logos');
  const customPng = path.join(logoDir, `${norm}.png`);
  const customSvg = path.join(logoDir, `${norm}.svg`);

  if (fs.existsSync(customPng)) {
    const b64 = fs.readFileSync(customPng).toString('base64');
    return `<img class="team-logo" src="data:image/png;base64,${b64}" alt="${name}" />`;
  }
  if (fs.existsSync(customSvg)) {
    const b64 = fs.readFileSync(customSvg).toString('base64');
    return `<img class="team-logo" src="data:image/svg+xml;base64,${b64}" alt="${name}" />`;
  }

  const { bg, text } = getBadgeStyle(name || '');
  const initials = getInitials(name || '');
  return `<span class="team-badge" style="background:${bg};color:${text}">${initials}</span>`;
}

async function render() {
  const input = JSON.parse(fs.readFileSync(0, 'utf-8'));
  const { matches, tier_filter = 'T2', title_suffix = '', updated_at = '' } = input;

  const tierRank = (t) => ({ T1: 1, T2: 2, T3: 3, Other: 4 }[t] || 5);
  const maxRank = tierRank(tier_filter);

  const filtered = matches.filter((m) => tierRank(m._tier || 'Other') <= maxRank);

  const tierTitles = {
    T1: '🔥 TIER 1 / MAJOR & BIG EVENTS',
    T2: '⚡ TIER 2 / CHALLENGER & CIRCUIT',
    T3: '🎯 TIER 3 / QUALIFIERS & CUPS',
    Other: '▫️ OTHER MATCHES',
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
    background: #12151b;
    color: #e2e8f0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 13px;
    width: 480px;
    padding: 12px 14px 8px 14px;
    display: inline-block;
  }
  .header {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    border-bottom: 2px solid #232936;
    padding-bottom: 6px;
    margin-bottom: 8px;
  }
  .header-title {
    font-size: 14px;
    font-weight: 800;
    color: #fff;
    letter-spacing: 0.5px;
  }
  .header-sub {
    font-size: 11px;
    color: #64748b;
  }
  .tier-sec {
    margin-top: 8px;
  }
  .tier-hdr {
    font-size: 10.5px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 4px;
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .tier-hdr.T1 { color: #f87171; }
  .tier-hdr.T2 { color: #fbbf24; }
  .tier-hdr.T3 { color: #60a5fa; }
  .tier-hdr.Other { color: #94a3b8; }
  .table {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .row {
    background: #191e27;
    border-radius: 4px;
    padding: 5px 8px;
    display: flex;
    align-items: center;
    border: 1px solid #232a36;
  }
  .row.live {
    border-color: #ef4444;
    background: #23161a;
  }
  .time-col {
    width: 48px;
    font-size: 11px;
    font-weight: 700;
    color: #94a3b8;
  }
  .time-col.live {
    color: #f87171;
  }
  .match-col {
    flex: 1;
    display: flex;
    align-items: center;
    gap: 5px;
    overflow: hidden;
  }
  .team-unit {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .team-logo {
    width: 16px;
    height: 16px;
    object-fit: contain;
    border-radius: 2px;
  }
  .team-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 15px;
    font-size: 9px;
    font-weight: 700;
    font-family: ui-monospace, monospace;
    border-radius: 3px;
    flex-shrink: 0;
  }
  .team {
    font-weight: 600;
    color: #fff;
    font-size: 12px;
    white-space: nowrap;
  }
  .vs {
    font-size: 10px;
    color: #475569;
    font-weight: 600;
  }
  .event-tag {
    font-size: 10px;
    color: #64748b;
    margin-left: 4px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 105px;
  }
  .stars {
    color: #f59e0b;
    font-size: 10px;
    margin-left: auto;
    padding-right: 6px;
    letter-spacing: -1px;
  }
  .id-col {
    font-family: ui-monospace, monospace;
    font-size: 11px;
    color: #38bdf8;
    font-weight: 500;
  }
  .footer {
    text-align: center;
    font-size: 10px;
    color: #475569;
    margin-top: 8px;
  }
</style>
</head>
<body>
  <div class="header">
    <div class="header-title">HLTV MATCHES</div>
    <div class="header-sub">${updated_at ? `${updated_at} · ` : ''}${tier_filter}</div>
  </div>
`;

  if (filtered.length === 0) {
    htmlContent += `<div style="text-align:center;padding:20px;color:#64748b;">No matches found for ${tier_filter}</div>`;
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
        const t1 = m.team1 || '?';
        const t2 = m.team2 || '?';
        htmlContent += `
          <div class="row ${isLive ? 'live' : ''}">
            <div class="time-col ${isLive ? 'live' : ''}">${isLive ? '🔴 LIVE' : (m.time || '--:--')}</div>
            <div class="match-col">
              <div class="team-unit">
                ${renderTeamIcon(t1)}
                <span class="team">${t1}</span>
              </div>
              <span class="vs">vs</span>
              <div class="team-unit">
                ${renderTeamIcon(t2)}
                <span class="team">${t2}</span>
              </div>
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
  await page.setViewport({ width: 480, height: 100, deviceScaleFactor: 2 });
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
