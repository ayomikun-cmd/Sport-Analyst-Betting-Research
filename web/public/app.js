/* Sport Analyst — client */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  sport: 'epl',
  football: [],
  other: [],
  platforms: [],
  events: [],
  askEvent: null,
};

const RECORD_KEY = 'sport-analyst.record.v1';
const STOP = new Set(['to', 'win', 'wins', 'the', 'fc', 'vs', 'v', 'at', 'and', 'or', 'over', 'under', 'match', 'bet', 'both', 'teams', 'score', 'goals', 'draw', 'home', 'away']);

/* ------------------------------------------------------------- formatting */

const money = (n) => `₦${Number(n || 0).toLocaleString('en-NG', { maximumFractionDigits: 0 })}`;
const pct = (n) => `${(Number(n) * 100).toFixed(1)}%`;
const price = (n) => (Number.isFinite(Number(n)) ? Number(n).toFixed(2) : '—');
const escapeHtml = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function initials(name) {
  const words = String(name || '').replace(/[^A-Za-z\s]/g, ' ').split(/\s+/).filter(Boolean);
  if (!words.length) return '?';
  if (words.length === 1) return words[0].slice(0, 3).toUpperCase();
  return words.slice(0, 3).map((w) => w[0]).join('').toUpperCase();
}

function kickoff(iso) {
  if (!iso) return 'TBD';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return 'TBD';
  const now = new Date();
  const time = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  if (date.toDateString() === now.toDateString()) return `Today ${time}`;
  const tomorrow = new Date(now.getTime() + 86400000);
  if (date.toDateString() === tomorrow.toDateString()) return `Tmrw ${time}`;
  return `${date.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })} ${time}`;
}

function isSoon(iso) {
  if (!iso) return false;
  const diff = new Date(iso).getTime() - Date.now();
  return diff > 0 && diff < 3 * 3600 * 1000;
}

function tokens(text) {
  return String(text || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .filter((t) => t.length > 2 && !STOP.has(t));
}

let toastTimer;
function toast(message) {
  const el = $('#toast');
  el.textContent = message;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2600);
}

async function api(path, options) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || data.detail || `HTTP ${res.status}`);
  return data;
}

/* ----------------------------------------------------------------- boot */

async function boot() {
  try {
    const health = await api('/api/health');
    state.football = health.football || [];
    state.other = health.other || [];
    state.platforms = health.platforms || [];
    setStatus('live', health.ai ? `AI · ${health.model}` : 'AI off');
    renderChips();
    renderPlatforms();
    renderBookOptions();
  } catch {
    setStatus('down', 'offline');
  }
  loadFeed(state.sport);
  renderRecord();
  bind();
  observeReveals();
}

function setStatus(kind, text) {
  const el = $('#status');
  if (!el) return;
  el.className = `status ${kind}`;
  $('#status-text').textContent = text;
}

function renderPlatforms() {
  const list = state.platforms.length
    ? state.platforms
    : [{ label: 'SportyBet', priced: true }];
  $('#platforms').innerHTML = list
    .map((p) => `<span class="plat${p.priced ? ' on' : ''}">${escapeHtml(p.label)}${p.priced ? ' · priced' : ''}</span>`)
    .join('');
}

function renderBookOptions() {
  const books = state.platforms.length ? state.platforms : [{ label: 'Bet9ja' }, { label: 'BetKing' }, { label: 'GokaBet' }];
  $('#convert-book').innerHTML = books
    .filter((p) => p.id !== 'sportybet')
    .map((p) => `<option>${escapeHtml(p.label)}</option>`)
    .join('');
}

function renderChips() {
  const chips = [
    ...state.football.map((l) => `<button class="chip${l.key === state.sport ? ' active' : ''}" data-sport="${l.key}">${escapeHtml(l.label)}</button>`),
    ...state.other.map((l) => `<button class="chip more${l.key === state.sport ? ' active' : ''}" data-sport="${l.key}">${escapeHtml(l.label)}</button>`),
  ];
  $('#league-chips').innerHTML = chips.join('') || '<span class="hint">Leagues unavailable</span>';
}

/* -------------------------------------------------------- scroll effects */

function observeReveals() {
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      entry.target.classList.add('in');
      observer.unobserve(entry.target);
    }
  }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
  $$('.reveal').forEach((el) => observer.observe(el));
}

function trackProgress() {
  const bar = $('#progress');
  if (!bar) return;
  const doc = document.documentElement;
  const max = doc.scrollHeight - window.innerHeight;
  bar.style.width = `${max > 0 ? (window.scrollY / max) * 100 : 0}%`;
}

/* ----------------------------------------------------------------- feed */

async function loadFeed(sport) {
  state.sport = sport;
  renderChips();
  const board = $('#board');
  board.innerHTML = '<div class="skeleton" style="height:200px"></div><div class="skeleton" style="height:200px"></div>';
  $('#feed-meta').textContent = 'loading fixtures…';

  try {
    const data = await api(`/api/odds?sport=${encodeURIComponent(sport)}&limit=24`);
    state.events = data.events || [];
    $('#feed-meta').textContent = `${data.events.length} fixtures · ${labelFor(sport)} · ${data.source} · updated ${new Date(data.updated).toLocaleTimeString()}`;
    board.innerHTML = data.events.length
      ? data.events.map(fixtureCard).join('')
      : '<div class="panel empty-state">No upcoming fixtures published for this league right now.</div>';
    updateHero(data);
    renderTicker();
  } catch (error) {
    $('#feed-meta').textContent = 'feed unavailable';
    board.innerHTML = `<div class="panel empty-state">Could not load prices: ${escapeHtml(error.message)}</div>`;
  }
}

function labelFor(key) {
  const found = [...state.football, ...state.other].find((l) => l.key === key);
  return found ? found.label : key;
}

function updateHero(data) {
  const books = new Set();
  for (const event of data.events || []) for (const book of event.books || []) books.add(book.book);
  const stats = [
    [String(data.events?.length || 0), 'fixtures priced'],
    [String(books.size || 1), books.size > 1 ? 'bookmakers' : 'bookmaker'],
    [String(state.football.length + state.other.length || 0), 'leagues'],
    [new Date(data.updated).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }), 'last refresh'],
  ];
  $('#hero-stats').innerHTML = stats
    .map(([value, label], i) => `<div class="hero-stat"><b data-count="${i}">${escapeHtml(value)}</b><span>${label}</span></div>`)
    .join('');
}

function renderTicker() {
  const items = state.events.slice(0, 14).map((event) => {
    const market = event.market;
    const home = market ? price(market.best.home?.price) : '—';
    return `<span class="ticker-item"><b>${escapeHtml(event.home.name)}</b> v <b>${escapeHtml(event.away.name)}</b><span class="px">${home}</span></span>`;
  });
  if (!items.length) {
    $('#ticker-track').innerHTML = '<span class="ticker-item">Sport Analyst · no prices published</span>';
    return;
  }
  $('#ticker-track').innerHTML = [...items, ...items].join('');
}

function fixtureCard(event, index) {
  const market = event.market;
  const sides = event.hasDraw ? ['home', 'draw', 'away'] : ['home', 'away'];
  const single = !event.books || event.books.length <= 1;

  const odds = sides.map((side) => {
    const team = side === 'home' ? event.home.name : side === 'away' ? event.away.name : 'Draw';
    const pick = market ? market.best[side] : null;
    if (!pick) {
      return `<div class="odd missing"><span class="odd-label">${side === 'draw' ? 'X' : side === 'home' ? '1' : '2'}</span><span class="odd-price">—</span><span class="odd-fair">no price</span></div>`;
    }
    const fair = market.consensus[side];
    const highlight = !single && pick.price === Math.max(...sides.map((s) => market.best[s]?.price || 0));
    return `<button class="odd${highlight ? ' best' : ''}" data-add="1" data-team="${escapeHtml(team)}" data-side="${side}" data-price="${pick.price}">
      <span class="odd-label">${side === 'home' ? '1' : side === 'draw' ? 'X' : '2'}</span>
      <span class="odd-price">${price(pick.price)}</span>
      <span class="odd-fair">${pct(fair)}</span>
    </button>`;
  }).join('');

  return `<article class="fx" style="--i:${index}">
    <div class="fx-top">
      <span class="fx-league">${escapeHtml(event.leagueLabel)}</span>
      ${event.live ? '<span class="tag warn">live</span>' : ''}
      <span class="fx-time${isSoon(event.start) ? ' soon' : ''}">${escapeHtml(kickoff(event.start))}</span>
    </div>
    <div class="fx-teams">${teamRow(event.home)}${teamRow(event.away)}</div>
    <div class="odds" style="grid-template-columns:repeat(${sides.length},1fr)">${odds}</div>
    <div class="fx-foot">
      <span class="tag src">${event.source === 'sportybet' ? 'SportyBet' : event.source === 'oddsapi' ? 'OddsAPI' : 'ESPN'}</span>
      <span class="tag${single ? ' warn' : ' good'}">${single ? 'single book · no line-shop' : `${event.books.length} books`}</span>
      <button class="btn btn-sm fx-research" data-research="${escapeHtml(event.id)}">Research →</button>
    </div>
  </article>`;
}

function teamRow(team) {
  const badge = team.logo
    ? `<img src="${escapeHtml(team.logo)}" alt="" loading="lazy" />`
    : `<span class="team-badge">${escapeHtml(initials(team.name))}</span>`;
  return `<div class="team">${badge}<span class="team-name">${escapeHtml(team.name)}</span></div>`;
}

/* ------------------------------------------------------------- research */

async function analyse(body) {
  const report = $('#report');
  report.className = 'panel';
  report.innerHTML = '<div class="skeleton" style="height:240px"></div>';
  report.scrollIntoView({ behavior: 'smooth', block: 'start' });
  try {
    const data = await api('/api/research', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (data.event) {
      state.askEvent = { id: data.event.id, name: data.event.name };
      renderReport(data);
    } else {
      renderCandidates(data);
    }
  } catch (error) {
    report.innerHTML = `<p class="empty-state">Research failed: ${escapeHtml(error.message)}</p>`;
  }
}

function renderCandidates(data) {
  const list = data.candidates || [];
  $('#report').innerHTML = `
    <p class="hint" style="margin-bottom:10px">${escapeHtml(data.error || 'Several fixtures match. Pick one:')}</p>
    <div class="row" style="margin-top:0">
      ${list.map((c) => `<button class="btn btn-sm" data-research="${escapeHtml(c.id)}">${escapeHtml(c.name)} · ${escapeHtml(kickoff(c.start))}</button>`).join('')}
    </div>`;
}

function formHtml(context) {
  if (!context) {
    return `<div class="ctx wide"><h4>Form &amp; head-to-head</h4>
      <p class="hint">No reliable match found in the ESPN team feed, so this is left blank rather than guessed.</p></div>`;
  }
  const dots = (seq) => String(seq || '').split('').map((r) => `<span class="fd ${r.toLowerCase()}">${r}</span>`).join('');
  const row = (side) => `
    <div class="form-row"><span class="form-name">${escapeHtml(side.team)}</span>${dots(side.sequence) || '<span class="hint">no results</span>'}</div>
    <ul class="res-list">${(side.results || []).map((r) => `<li><span>${escapeHtml(r.date)} · ${escapeHtml(r.opponent)}</span><b>${escapeHtml(r.score)} ${r.result}</b></li>`).join('') || '<li>No completed matches found</li>'}</ul>`;

  const meetings = (context.h2h?.meetings || []).length
    ? `<ul class="res-list">${context.h2h.meetings.map((m) => `<li><span>${escapeHtml(m.date)}</span><b>${escapeHtml(m.line)}</b></li>`).join('')}</ul>`
    : '<p class="hint">No head-to-head meetings in the current season feed.</p>';

  return `
    <div class="ctx"><h4>Current form · last 5</h4>${row(context.form.home)}<div style="height:10px"></div>${row(context.form.away)}</div>
    <div class="ctx"><h4>Head-to-head</h4>${meetings}
      <h4 style="margin-top:14px">Not in the feed</h4>
      <ul class="missing-list">${(context.missing || []).map((m) => `<li>${escapeHtml(m)}</li>`).join('')}</ul>
    </div>`;
}

function renderReport(data) {
  const { event, ai, aiError, context, sources, notes } = data;
  const market = event.market;
  const sides = event.hasDraw ? ['home', 'draw', 'away'] : ['home', 'away'];
  const sideName = (side) => (side === 'home' ? event.home.name : side === 'away' ? event.away.name : 'Draw');
  const single = !market || market.lineShop === false;

  const priceRows = market
    ? `<ul class="res-list">${sides.map((side) => `<li><span>${escapeHtml(sideName(side))}</span><b>${price(market.best[side]?.price)} · ${pct(market.consensus[side])}</b></li>`).join('')}</ul>
       <p class="hint" style="margin-top:10px">Price and fair probability. Margin ${(market.averageMargin * 100).toFixed(1)}%.</p>`
    : '<p class="hint">No prices published for this fixture yet.</p>';

  const aiHtml = ai
    ? `<div class="confidence" style="margin-top:20px">
        <span class="label" style="margin:0">confidence</span>
        <div class="confidence-bar"><i style="width:${Math.max(2, ai.confidence ?? 0)}%"></i></div>
        <b>${ai.confidence ?? '—'}</b>
      </div>
      ${ai.lean ? `<div class="lean"><strong>the read</strong>${escapeHtml(ai.lean)}</div>` : ''}
      <div class="report-grid">
        <div><h4>Why</h4><ol class="reason">${(ai.reasoning || []).map((r) => `<li>${escapeHtml(r)}</li>`).join('') || '<li>No reasoning returned.</li>'}</ol></div>
        <div>
          <h4>Risks</h4>
          <div class="taglist risk">${(ai.risks || []).map((r) => `<span class="tag">${escapeHtml(r)}</span>`).join('') || '<span class="tag">none flagged</span>'}</div>
          <h4 style="margin-top:18px">What the model says is missing</h4>
          <div class="taglist gaps">${(ai.dataGaps || []).map((g) => `<span class="tag">${escapeHtml(g)}</span>`).join('') || '<span class="tag">none flagged</span>'}</div>
        </div>
      </div>`
    : `<p class="hint" style="margin-top:16px">Narrative unavailable${aiError ? ` (${escapeHtml(aiError)})` : ''}. The maths above stands without it.</p>`;

  $('#report').innerHTML = `
    <div class="report">
      <div class="report-head">
        <span class="tag src">${event.source === 'sportybet' ? 'SportyBet NG' : event.source === 'oddsapi' ? 'Odds API' : 'ESPN'}</span>
        <span class="tag">${escapeHtml(event.leagueLabel)}</span>
        <span class="tag${single ? ' warn' : ' good'}">${single ? 'single book' : `${event.books.length} books`}</span>
      </div>
      <h3>${escapeHtml(ai?.headline || event.name)}</h3>
      <p class="report-meta">${escapeHtml(event.name)} · ${escapeHtml(kickoff(event.start))}</p>

      ${single ? '<div class="warn-line"><b>No line-shop.</b><span>Only SportyBet is publishing this fixture, so there is no second price to beat. Every outcome carries the book’s margin; no edge is shown.</span></div>' : ''}

      <div class="ctx-grid">
        <div class="ctx"><h4>Market</h4>${priceRows}</div>
        ${formHtml(context)}
      </div>

      ${aiHtml}
      <div class="sources">
        ${sources.map((s) => `<span>Source: ${escapeHtml(s.name)}</span>`).join('')}
        ${notes.map((n) => `<span>Note: ${escapeHtml(n)}</span>`).join('')}
        <span>Generated ${new Date(data.generatedAt).toLocaleTimeString()}</span>
      </div>
    </div>`;
}

/* ------------------------------------------------------- codes & claims */

function shortDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 16);
  return date.toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function claimClass(status) {
  const value = String(status || '').toLowerCase();
  if (value === 'supported') return 'good';
  if (value === 'contradicted') return 'bad';
  return 'warn';
}

async function runScan(input) {
  const out = $('#scan-out');
  out.className = 'panel';
  out.innerHTML = '<div class="skeleton" style="height:170px"></div>';

  try {
    const data = await api('/api/scan', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ input, sport: state.sport }),
    });
    if (data.kind === 'post') return renderScanPost(data);
    if (data.kind === 'code') return renderScanCode(data);
    out.className = 'panel empty-state';
    out.textContent = data.error || 'Nothing to check.';
  } catch (error) {
    out.className = 'panel empty-state';
    out.textContent = `Check failed: ${error.message}`;
  }
}

function renderScanPost(data) {
  const out = $('#scan-out');
  const claims = data.claims || [];
  const tally = { supported: 0, contradicted: 0, 'cannot verify': 0 };
  for (const claim of claims) {
    const key = String(claim.status || '').toLowerCase();
    if (key in tally) tally[key] += 1;
  }

  const body = data.aiError
    ? `<p class="hint">Claim check unavailable: ${escapeHtml(data.aiError)}</p>`
    : `
      <div class="claim-counts">
        <span class="tag good">${tally.supported} supported</span>
        <span class="tag bad">${tally.contradicted} contradicted</span>
        <span class="tag warn">${tally['cannot verify']} cannot verify</span>
      </div>
      <div class="claims">
        ${claims.map((claim) => `<div class="claim ${claimClass(claim.status)}">
          <div class="claim-top"><span class="tag ${claimClass(claim.status)}">${escapeHtml(claim.status)}</span></div>
          <p class="claim-text">${escapeHtml(claim.claim)}</p>
          <p class="claim-evidence">${escapeHtml(claim.evidence)}</p>
        </div>`).join('') || '<p class="hint">No factual claims found in that post.</p>'}
      </div>
      ${data.summary ? `<p class="hint" style="margin-top:12px">${escapeHtml(data.summary)}</p>` : ''}`;

  const checked = (data.context || []).map((row) => row.match).join(', ');

  out.innerHTML = `
    <div class="report-head">
      <span class="tag src">X post</span>
      <span class="tag">@${escapeHtml(data.post.author)}</span>
      ${data.post.date ? `<span class="tag">${escapeHtml(shortDate(data.post.date))}</span>` : ''}
    </div>
    <blockquote class="quote">${escapeHtml(data.post.text)}</blockquote>
    ${body}
    <p class="hint" style="margin-top:12px">${checked ? `Checked against: ${escapeHtml(checked)}` : 'No fixture in the current feed matches this post, so nothing could be verified against live data.'}</p>
    <p class="hint">Source: <a href="${escapeHtml(data.post.url)}" target="_blank" rel="noreferrer">the post</a> · every claim is compared only with form and head-to-head in the feed.</p>`;
}

function renderScanCode(data) {
  const out = $('#scan-out');
  if (!data.resolved) {
    out.className = 'panel empty-state';
    out.innerHTML = `<strong>${escapeHtml(data.code)}</strong><br />${escapeHtml(data.message || 'That code could not be read.')}`;
    return;
  }

  const readFor = (selection) => (data.ai?.legs || []).find((row) => row.selection && selection && row.selection.toLowerCase().includes(String(selection).toLowerCase().slice(0, 12)));

  out.innerHTML = `
    <div class="report-head">
      <span class="tag src">${escapeHtml(data.book)}</span>
      <span class="tag">code ${escapeHtml(data.code.toUpperCase())}</span>
      <span class="tag">${data.legs.length} legs</span>
    </div>
    <div class="verdict"><b>${price(data.combined)}</b><span>combined decimal odds</span></div>
    <div class="legs">
      ${data.legs.map((leg) => {
        const read = readFor(leg.selection);
        return `<div class="leg">
          <span>${escapeHtml(leg.event || 'Event not named')}<br /><span class="hint">${escapeHtml(leg.market || 'Market not named')} · ${escapeHtml(leg.selection || 'Selection not named')}</span></span>
          <span class="leg-price">${price(leg.odds)}</span>
          <span class="tag">${leg.odds && leg.odds < 1.3 ? 'short' : 'priced'}</span>
          ${read ? `<span class="leg-note">${escapeHtml(read.read)}</span>` : ''}
        </div>`;
      }).join('')}
    </div>
    ${data.aiError ? `<p class="hint">Slip read unavailable: ${escapeHtml(data.aiError)}</p>` : ''}
    ${data.ai?.summary ? `<p class="hint" style="margin-top:10px">${escapeHtml(data.ai.summary)}</p>` : ''}
    ${(data.ai?.risks || []).length ? `<div class="taglist risk" style="margin-top:10px">${data.ai.risks.map((r) => `<span class="tag warn">${escapeHtml(r)}</span>`).join('')}</div>` : ''}
    <p class="hint" style="margin-top:10px">Resolved from ${escapeHtml(data.book)}'s own share endpoint. Odds are as returned; a code from another book has no open reader yet.</p>`;
}

/* ------------------------------------------------------------------ ask */

let typeTimer = null;
function typeAnswer(text, event) {
  const out = $('#ask-out');
  clearInterval(typeTimer);
  const chip = event ? `<span class="ctx-chip">${escapeHtml(event.name)}</span>` : '';
  out.innerHTML = `<span class="who">analyst${chip}</span><span id="typed"></span><span class="cursor" id="cursor"></span>`;
  const target = $('#typed');
  let i = 0;
  typeTimer = setInterval(() => {
    i = Math.min(text.length, i + 3);
    target.textContent = text.slice(0, i);
    if (i >= text.length) {
      clearInterval(typeTimer);
      const cursor = $('#cursor');
      if (cursor) cursor.remove();
    }
  }, 12);
}

async function runAsk(question) {
  const out = $('#ask-out');
  clearInterval(typeTimer);
  out.innerHTML = '<span class="who">analyst</span><span class="cursor"></span>';
  try {
    const data = await api('/api/ask', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ question, sport: state.sport, eventId: state.askEvent?.id }),
    });
    if (!data.answer) {
      out.innerHTML = `<span class="who">analyst</span>${escapeHtml(data.aiError || 'No answer returned.')}`;
      return;
    }
    typeAnswer(data.answer, data.event || state.askEvent);
  } catch (error) {
    out.innerHTML = `<span class="who">analyst</span>${escapeHtml(error.message)}`;
  }
}

/* ------------------------------------------------------------- slip lab */

function switchTab(name) {
  $$('#lab-tabs .tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
  for (const pane of ['audit', 'convert', 'stake']) $(`#pane-${pane}`).hidden = pane !== name;
  const out = $('#lab-out');
  out.className = 'panel empty-state';
  out.textContent = name === 'audit'
    ? 'Paste a slip to see combined odds, implied probability and which leg carries the risk.'
    : name === 'convert'
      ? 'Paste the slip to rebuild it at equivalent odds for another book.'
      : 'Enter your own probability and the price on offer to get fair value and a Kelly stake.';
}

function matchEvent(selection) {
  const wanted = tokens(selection);
  if (!wanted.length) return null;
  let best = null;
  for (const event of state.events) {
    const home = tokens(event.home.name);
    const away = tokens(event.away.name);
    const hitHome = home.some((t) => wanted.includes(t));
    const hitAway = away.some((t) => wanted.includes(t));
    const hitDraw = /draw/i.test(selection) && event.hasDraw;
    if (!hitHome && !hitAway && !hitDraw) continue;
    const side = hitDraw && !hitHome && !hitAway ? 'draw' : hitHome ? 'home' : 'away';
    best = { event, side };
    if (hitHome || hitAway) break;
  }
  return best;
}

function riskOf(edge) {
  if (edge === null) return { level: '', note: 'Not in the current feed, so it cannot be priced against the market.' };
  if (edge >= -0.02) return { level: 'risk-ok', note: `Fair value: ${(edge * 100).toFixed(1)}%.` };
  if (edge >= -0.08) return { level: 'risk-mid', note: `Slightly priced in: ${(edge * 100).toFixed(1)}%.` };
  return { level: 'risk-high', note: `Carrying the risk: ${(edge * 100).toFixed(1)}%.` };
}

async function runAudit() {
  const text = $('#audit-input').value.trim();
  if (!text) return toast('Paste at least one leg');
  const out = $('#lab-out');
  out.className = 'panel';
  out.innerHTML = '<div class="skeleton" style="height:180px"></div>';
  try {
    const data = await api('/api/convert', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    const legs = data.legs.map((leg) => {
      const match = matchEvent(leg.selection);
      const market = match?.event?.market;
      const lineShop = Boolean(market && market.lineShop);
      const edge = lineShop ? leg.odds * market.consensus[match.side] - 1 : null;
      return { ...leg, match, edge, lineShop, risk: riskOf(edge) };
    });
    const priced = legs.filter((l) => l.edge !== null);
    const worst = priced.slice().sort((a, b) => a.edge - b.edge)[0];
    const cut = worst && worst.edge < -0.06 && legs.length > 1
      ? { leg: worst, combined: data.combined / worst.odds }
      : null;

    out.innerHTML = `
      <div class="verdict"><b>${price(data.combined)}</b><span>combined · implied ${pct(data.impliedProb)}</span></div>
      <div class="stat-row" style="margin:12px 0 4px">
        <div><b>${legs.length}</b><span>legs</span></div>
        <div><b>${priced.length}</b><span>priced</span></div>
        <div><b>${data.errors.length}</b><span>ignored</span></div>
      </div>
      ${legs.some((l) => l.match && !l.lineShop) ? '<div class="warn-line"><b>No line-shop.</b><span>Some legs sit in a market with one price only, so there is no second price to compare and no edge is shown.</span></div>' : ''}
      <div class="legs">
        ${legs.map((leg) => `<div class="leg ${leg.risk.level}">
          <span>${escapeHtml(leg.selection)}</span>
          <span class="leg-price">${price(leg.odds)}</span>
          <span class="tag${leg.match && !leg.lineShop ? ' warn' : ''}">${leg.edge === null ? (leg.match ? 'single book' : 'unpriced') : `${(leg.edge * 100).toFixed(1)}%`}</span>
          <span class="leg-note">${escapeHtml(leg.match
            ? `${leg.match.event.home.name} v ${leg.match.event.away.name} · ${leg.lineShop ? leg.risk.note : 'one price only, so no edge can be measured.'}`
            : leg.risk.note)}</span>
        </div>`).join('')}
      </div>
      ${cut ? `<p class="hint">Trim the weakest leg (<strong>${escapeHtml(cut.leg.selection)}</strong>) and the slip pays <strong>${price(cut.combined)}</strong>.</p>` : ''}
      ${data.errors.length ? `<p class="hint" style="margin-top:8px">${data.errors.map(escapeHtml).join('<br />')}</p>` : ''}
      <p class="hint" style="margin-top:10px">${escapeHtml(data.note)}</p>`;
  } catch (error) {
    out.className = 'panel empty-state';
    out.textContent = `Audit failed: ${error.message}`;
  }
}

async function runConvert() {
  const text = $('#convert-input').value.trim();
  if (!text) return toast('Paste at least one leg');
  const out = $('#lab-out');
  out.className = 'panel';
  out.innerHTML = '<div class="skeleton" style="height:140px"></div>';
  try {
    const data = await api('/api/convert', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    out.innerHTML = `
      <p class="label" style="margin:0 0 6px">rebuilt for ${escapeHtml($('#convert-book').value)}</p>
      <div class="verdict"><b>${price(data.combined)}</b><span>equivalent decimal odds · implied ${pct(data.impliedProb)}</span></div>
      <div class="legs">
        ${data.legs.map((leg) => `<div class="leg"><span>${escapeHtml(leg.selection)}</span><span class="leg-price">${price(leg.odds)}</span><span class="tag">${price(leg.odds)}</span></div>`).join('')}
      </div>
      ${data.errors.length ? `<p class="hint">${data.errors.map(escapeHtml).join('<br />')}</p>` : ''}
      <p class="hint" style="margin-top:10px">${escapeHtml(data.note)}</p>`;
  } catch (error) {
    out.className = 'panel empty-state';
    out.textContent = `Conversion failed: ${error.message}`;
  }
}

function runStake() {
  const p = Number($('#stake-prob').value) / 100;
  const odds = Number($('#stake-odds').value);
  const bank = Number($('#stake-bank').value);
  const fraction = Number($('#stake-fraction').value);
  const out = $('#lab-out');
  out.className = 'panel';

  if (!(p > 0 && p < 1) || !(odds > 1) || !(bank > 0)) {
    out.innerHTML = '<p class="empty-state">Enter a probability between 1 and 99, a price above 1.00 and a bankroll.</p>';
    return;
  }
  const b = odds - 1;
  const ev = p * b - (1 - p);
  const kelly = ev / b;
  const stake = Math.max(0, kelly * fraction * bank);

  out.innerHTML = `
    <div class="verdict"><b>${ev >= 0 ? '+' : ''}${(ev * 100).toFixed(1)}%</b><span>expected value per ₦1 staked</span></div>
    <div class="stat-row" style="margin:12px 0 4px">
      <div><b>${pct(p * odds - 1)}</b><span>edge at this price</span></div>
      <div><b>${(kelly * 100).toFixed(1)}%</b><span>full kelly</span></div>
      <div><b>${money(stake)}</b><span>${fraction === 1 ? 'full' : fraction === 0.5 ? 'half' : 'quarter'} kelly stake</span></div>
    </div>
    <p class="hint" style="margin-top:10px">${ev <= 0
      ? 'At your own probability this price is negative value. The maths says pass.'
      : 'Kelly assumes your probability is right — the number most likely to be wrong. Cap the stake.'}</p>`;
}

function addToSlip(team, side, odds) {
  const area = $('#audit-input');
  const label = side === 'draw' ? 'Draw' : `${team} to win`;
  const line = `${label} ${price(odds)}`;
  area.value = area.value.trim() ? `${area.value.trim()}\n${line}` : line;
  switchTab('audit');
  toast(`${label} added to the slip`);
}

/* --------------------------------------------------------------- record */

function loadRecord() {
  try {
    const raw = JSON.parse(localStorage.getItem(RECORD_KEY) || '[]');
    return Array.isArray(raw) ? raw : [];
  } catch {
    return [];
  }
}

function saveRecord(rows) {
  localStorage.setItem(RECORD_KEY, JSON.stringify(rows));
}

function renderRecord() {
  const rows = loadRecord();
  const staked = rows.reduce((sum, r) => sum + Number(r.stake || 0), 0);
  const returned = rows.reduce((sum, r) => {
    if (r.status === 'won') return sum + Number(r.stake) * Number(r.odds);
    if (r.status === 'push') return sum + Number(r.stake);
    return sum;
  }, 0);
  const settled = rows.filter((r) => r.status !== 'open').length;
  const won = rows.filter((r) => r.status === 'won').length;
  const profit = returned - staked;
  const roi = staked ? (profit / staked) * 100 : 0;

  $('#record-stats').innerHTML = `
    <div><b>${money(staked)}</b><span>staked</span></div>
    <div><b style="color:${profit >= 0 ? 'var(--good)' : 'var(--red-bright)'}">${profit >= 0 ? '+' : ''}${money(profit)}</b><span>${roi.toFixed(1)}% roi</span></div>
    <div><b>${won} / ${settled}</b><span>won / settled</span></div>`;

  $('#log-body').innerHTML = rows.length
    ? `<table class="log">
        <thead><tr><th>Slip</th><th class="num">Odds</th><th class="num">Stake</th><th>Status</th><th></th></tr></thead>
        <tbody>
          ${rows.map((r) => `<tr>
            <td>${escapeHtml(r.slip)}</td>
            <td class="num">${price(r.odds)}</td>
            <td class="num">${money(r.stake)}</td>
            <td><span class="pill ${r.status}">${r.status}</span></td>
            <td style="text-align:right">
              ${['won', 'lost', 'push'].map((s) => `<button class="mini" data-settle="${r.id}" data-status="${s}">${s}</button>`).join('')}
              <button class="mini" data-del="${r.id}">×</button>
            </td>
          </tr>`).join('')}
        </tbody>
      </table>`
    : '<p class="empty-state">No bets logged. Every settled bet here is one you can check later.</p>';
}

function addBet(event) {
  event.preventDefault();
  const slip = $('#log-slip').value.trim();
  const odds = Number($('#log-odds').value);
  const stake = Number($('#log-stake').value);
  if (!slip) return toast('Add what the slip was');
  if (!(odds > 1)) return toast('Odds must be above 1.00');
  if (!(stake > 0)) return toast('Stake must be positive');

  const rows = loadRecord();
  rows.unshift({ id: `${Date.now()}`, slip, odds, stake, status: $('#log-status').value, date: new Date().toISOString() });
  saveRecord(rows);
  $('#log-slip').value = '';
  $('#log-odds').value = '';
  $('#log-stake').value = '';
  renderRecord();
  toast('Bet logged');
}

function settle(id, status) {
  saveRecord(loadRecord().map((r) => (r.id === id ? { ...r, status } : r)));
  renderRecord();
}

/* ---------------------------------------------------------------- events */

function bind() {
  $('#league-chips').addEventListener('click', (event) => {
    const chip = event.target.closest('[data-sport]');
    if (chip) loadFeed(chip.dataset.sport);
  });

  $('#board').addEventListener('click', (event) => {
    const add = event.target.closest('[data-add]');
    if (add) return addToSlip(add.dataset.team, add.dataset.side, Number(add.dataset.price));
    const research = event.target.closest('[data-research]');
    if (research) return analyse({ sport: state.sport, eventId: research.dataset.research });
  });

  $('#report').addEventListener('click', (event) => {
    const research = event.target.closest('[data-research]');
    if (research) analyse({ sport: state.sport, eventId: research.dataset.research });
  });

  $('#research-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const query = $('#research-input').value.trim();
    analyse(query ? { sport: state.sport, query } : { sport: state.sport });
  });

  $('#scan-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const input = $('#scan-input').value.trim();
    if (!input) return toast('Paste a booking code or a post link');
    runScan(input);
  });

  $('#scan-suggest').addEventListener('click', (event) => {
    const chip = event.target.closest('[data-scan]');
    if (!chip) return;
    $('#scan-input').value = chip.dataset.scan;
    runScan(chip.dataset.scan);
  });

  $('#ask-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const question = $('#ask-input').value.trim();
    if (!question) return toast('Type a question first');
    runAsk(question);
  });

  $('#ask-suggest').addEventListener('click', (event) => {
    const chip = event.target.closest('[data-q]');
    if (!chip) return;
    $('#ask-input').value = chip.dataset.q;
    runAsk(chip.dataset.q);
  });

  $('#lab-tabs').addEventListener('click', (event) => {
    const tab = event.target.closest('[data-tab]');
    if (tab) switchTab(tab.dataset.tab);
  });

  $('#audit-run').addEventListener('click', runAudit);
  $('#audit-clear').addEventListener('click', () => { $('#audit-input').value = ''; switchTab('audit'); });
  $('#convert-run').addEventListener('click', runConvert);
  $('#stake-run').addEventListener('click', runStake);

  $('#log-form').addEventListener('submit', addBet);
  $('#log-body').addEventListener('click', (event) => {
    const settleButton = event.target.closest('[data-settle]');
    if (settleButton) return settle(settleButton.dataset.settle, settleButton.dataset.status);
    const del = event.target.closest('[data-del]');
    if (del) {
      saveRecord(loadRecord().filter((r) => r.id !== del.dataset.del));
      renderRecord();
    }
  });

  $('#nav').addEventListener('click', (event) => {
    const link = event.target.closest('a');
    if (!link) return;
    $$('#nav a').forEach((a) => a.classList.toggle('active', a === link));
  });

  const sections = ['feed', 'research', 'scan', 'ask', 'lab', 'record'].map((id) => document.getElementById(id));
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      $$('#nav a').forEach((a) => a.classList.toggle('active', a.getAttribute('href') === `#${entry.target.id}`));
    }
  }, { rootMargin: '-45% 0px -50% 0px' });
  sections.forEach((section) => section && observer.observe(section));

  window.addEventListener('scroll', trackProgress, { passive: true });
  trackProgress();
}

boot();
