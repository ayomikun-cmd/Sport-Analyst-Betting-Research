/**
 * Sport Analyst — Cloudflare Worker
 *
 * Football-first research. Prices come from SportyBet's Nigerian 1X2 feed;
 * The Odds API and ESPN are fallbacks / extra books.
 *
 * Routes
 *   GET  /api/health                 capability probe
 *   GET  /api/odds?sport=epl         upcoming events + real bookmaker prices
 *   POST /api/research               grounded event research (+ optional AI narrative)
 *   POST /api/convert                slip translation / combined-odds rebuild
 *   POST /api/scan                   resolve a booking code, or fact-check an X post
 *   *                                static assets from ./public
 *
 * Design rule: every number returned to the client is computed here from a
 * fetched feed. The language model only narrates; it never supplies
 * probabilities, prices or edges. That is what keeps the research honest.
 */

const ESPN_BASE = 'https://site.api.espn.com/apis/site/v2/sports';
const ODDS_BASE = 'https://api.the-odds-api.com/v4';

/**
 * League registry, football first.
 * `sporty` is the SportyBet (Betradar) tournament id on its Nigerian feed;
 * `odds` is the matching The Odds API sport key.
 */
const LEAGUES = {
  epl:        { label: 'Premier League',        sport: 'soccer',     espn: 'eng.1',          odds: 'soccer_epl',                  sporty: 17 },
  laliga:     { label: 'La Liga',               sport: 'soccer',     espn: 'esp.1',          odds: 'soccer_spain_la_liga',        sporty: 8 },
  seriea:     { label: 'Serie A',               sport: 'soccer',     espn: 'ita.1',          odds: 'soccer_italy_serie_a',        sporty: 23 },
  bundesliga: { label: 'Bundesliga',            sport: 'soccer',     espn: 'ger.1',          odds: 'soccer_germany_bundesliga',   sporty: 35 },
  ligue1:     { label: 'Ligue 1',               sport: 'soccer',     espn: 'fra.1',          odds: 'soccer_france_ligue_one',     sporty: 34 },
  ucl:        { label: 'Champions League',      sport: 'soccer',     espn: 'uefa.champions', odds: 'soccer_uefa_champs_league',   sporty: 7 },
  uel:        { label: 'Europa League',         sport: 'soccer',     espn: 'uefa.europa',    odds: 'soccer_uefa_europa_league',   sporty: 679 },
  nba:        { label: 'NBA',                   sport: 'basketball', espn: 'nba',            odds: 'basketball_nba',              sporty: null },
  nfl:        { label: 'NFL',                   sport: 'football',   espn: 'nfl',            odds: 'americanfootball_nfl',        sporty: null },
  mlb:        { label: 'MLB',                   sport: 'baseball',   espn: 'mlb',            odds: 'baseball_mlb',                sporty: null },
  nhl:        { label: 'NHL',                   sport: 'hockey',     espn: 'nhl',            odds: 'icehockey_nhl',               sporty: null },
};

const FOOTBALL_LEAGUES = Object.keys(LEAGUES).filter((key) => LEAGUES[key].sport === 'soccer');
const SPORTYBET_BASE = 'https://www.sportybet.com/api/ng/factsCenter';
const SPORTYBET_HEADERS = {
  accept: 'application/json',
  'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
  referer: 'https://www.sportybet.com/ng/',
  origin: 'https://www.sportybet.com',
};

const MAX_RESEARCH_BODY = 4096;
const JSON_HEADERS = {
  'content-type': 'application/json; charset=utf-8',
  'cache-control': 'no-store',
  'x-content-type-options': 'nosniff',
};

/* ------------------------------------------------------------------ cache */

const memo = new Map();
function memoGet(key) {
  const hit = memo.get(key);
  if (!hit) return null;
  if (hit.expires < Date.now()) { memo.delete(key); return null; }
  return hit.value;
}
function memoSet(key, value, ttlMs) {
  if (memo.size > 200) memo.clear();
  memo.set(key, { value, expires: Date.now() + ttlMs });
}

/* ------------------------------------------------------------------- odds */

/** American ("-180") or decimal ("2.10") string -> decimal number. */
function toDecimal(raw) {
  if (raw === null || raw === undefined) return null;
  const text = String(raw).trim();
  if (!text) return null;
  const value = Number(text.replace(/[^0-9.+-]/g, ''));
  if (!Number.isFinite(value) || value === 0) return null;
  const american = /^[+-]/.test(text) || Math.abs(value) >= 100;
  if (!american) return value > 1 ? value : null;
  return value > 0 ? 1 + value / 100 : 1 + 100 / Math.abs(value);
}

function decimalToAmerican(price) {
  if (!Number.isFinite(price) || price <= 1) return null;
  const value = price >= 2 ? Math.round((price - 1) * 100) : Math.round(-100 / (price - 1));
  return value > 0 ? `+${value}` : String(value);
}

/** No-vig fair probabilities for one bookmaker's prices. */
function fairFromPrices(prices) {
  const keys = Object.keys(prices).filter((k) => Number.isFinite(prices[k]) && prices[k] > 1);
  if (keys.length < 2) return null;
  const implied = {};
  let total = 0;
  for (const key of keys) {
    implied[key] = 1 / prices[key];
    total += implied[key];
  }
  if (!Number.isFinite(total) || total <= 0) return null;
  const fair = {};
  for (const key of keys) fair[key] = implied[key] / total;
  return { fair, implied, margin: total - 1 };
}

/**
 * Consensus + best-price analysis across every collected bookmaker.
 * Consensus is the average vig-free probability, so it is an estimate of the
 * market's true opinion rather than one book's opinion.
 */
function analyseBooks(books, hasDraw) {
  const outcomes = hasDraw ? ['home', 'draw', 'away'] : ['home', 'away'];
  const usable = books.filter((b) => outcomes.every((k) => Number.isFinite(b[k]) && b[k] > 1));
  if (!usable.length) return null;

  const consensus = {};
  const implied = {};
  const best = {};
  const marginSum = { value: 0 };

  for (const key of outcomes) {
    let fairTotal = 0;
    let impliedTotal = 0;
    let bestPrice = null;
    let bestBook = null;
    for (const book of usable) {
      const calc = fairFromPrices(
        Object.fromEntries(outcomes.map((k) => [k, book[k]])),
      );
      if (!calc) continue;
      fairTotal += calc.fair[key];
      impliedTotal += calc.implied[key];
      if (bestPrice === null || book[key] > bestPrice) {
        bestPrice = book[key];
        bestBook = book.book;
      }
    }
    const marginCalc = fairFromPrices(
      Object.fromEntries(outcomes.map((k) => [k, usable[0][k]])),
    );
    marginSum.value += marginCalc ? marginCalc.margin : 0;
    consensus[key] = fairTotal / usable.length;
    implied[key] = impliedTotal / usable.length;
    best[key] = { price: bestPrice, book: bestBook };
  }

  const edge = {};
  for (const key of outcomes) {
    edge[key] = consensus[key] * best[key].price - 1;
  }

  // A genuine arbitrage needs the reciprocals of the best prices to sum < 1.
  const bestSum = outcomes.reduce((sum, key) => sum + 1 / best[key].price, 0);
  const arb = { isArb: bestSum < 1, profitPct: (1 / bestSum - 1) * 100, bestSum };

  return {
    outcomes,
    consensus,
    implied,
    best,
    edge,
    arb,
    occurrence: usable.length,
    lineShop: usable.length > 1,
    averageMargin: marginSum.value / usable.length,
  };
}

/** Normalise one ESPN scoreboard event into the app's event shape. */
function normaliseEspnEvent(event, key) {
  const league = LEAGUES[key];
  const comp = event.competitions?.[0] || {};
  const competitors = comp.competitors || [];
  const side = (homeAway) => {
    const found = competitors.find((c) => c.homeAway === homeAway);
    if (!found) return null;
    return {
      name: found.team?.displayName || found.team?.name || 'TBD',
      short: found.team?.abbreviation || '',
      logo: found.team?.logo || null,
      score: found.score ?? null,
    };
  };
  const home = side('home');
  const away = side('away');
  if (!home || !away) return null;

  const books = [];
  for (const raw of comp.odds || []) {
    if (!raw || typeof raw !== 'object') continue;
    const ml = raw.moneyline || {};
    const pick = (node) => toDecimal(node?.close?.odds ?? node?.open?.odds ?? node);
    const book = {
      book: raw.provider?.displayName || raw.provider?.name || 'Bookmaker',
      home: pick(ml.home),
      away: pick(ml.away),
      draw: pick(ml.draw),
      spread: raw.details || null,
      total: Number.isFinite(raw.overUnder) ? raw.overUnder : null,
    };
    if (book.home && book.away) books.push(book);
  }

  const hasDraw = books.some((b) => Number.isFinite(b.draw)) ||
    (league.sport === 'soccer');
  const market = analyseBooks(books, hasDraw);

  return {
    id: `espn:${key}:${event.id}`,
    source: 'espn',
    league: key,
    leagueLabel: league.label,
    name: event.name || `${away.name} at ${home.name}`,
    start: event.date || comp.date || null,
    status: event.status?.type?.name || null,
    live: Boolean(event.status?.type?.state === 'in'),
    completed: Boolean(event.status?.type?.completed),
    detail: event.status?.type?.shortDetail || event.status?.type?.detail || null,
    home,
    away,
    hasDraw,
    books,
    market,
  };
}

/** Optional multi-bookmaker feed. Requires ODDS_API_KEY. */
async function fetchOddsApi(env, key) {
  const league = LEAGUES[key];
  if (!env.ODDS_API_KEY || !league) return null;
  const cacheKey = `oddsapi:${key}`;
  const cached = memoGet(cacheKey);
  if (cached) return cached;

  const url = new URL(`${ODDS_BASE}/sports/${league.odds}/odds`);
  url.searchParams.set('apiKey', env.ODDS_API_KEY);
  url.searchParams.set('regions', env.ODDS_REGIONS || 'uk,eu');
  url.searchParams.set('markets', 'h2h');
  url.searchParams.set('oddsFormat', 'decimal');
  url.searchParams.set('dateFormat', 'iso');

  const res = await fetch(url.toString());
  if (!res.ok) return null;
  const rows = await res.json();
  if (!Array.isArray(rows)) return null;

  const events = rows.map((row) => {
    const books = [];
    for (const book of row.bookmakers || []) {
      const market = (book.markets || []).find((m) => m.key === 'h2h');
      if (!market) continue;
      const prices = { home: null, away: null, draw: null };
      for (const outcome of market.outcomes || []) {
        const price = toDecimal(outcome.price);
        if (outcome.name === row.home_team) prices.home = price;
        else if (outcome.name === row.away_team) prices.away = price;
        else if (String(outcome.name).toLowerCase() === 'draw') prices.draw = price;
      }
      if (prices.home && prices.away) {
        books.push({ book: book.title || book.key, ...prices });
      }
    }
    const hasDraw = books.some((b) => Number.isFinite(b.draw));
    return {
      id: `oddsapi:${key}:${row.id}`,
      source: 'oddsapi',
      league: key,
      leagueLabel: league.label,
      name: `${row.away_team} at ${row.home_team}`,
      start: row.commence_time,
      status: null,
      live: row.commence_time ? new Date(row.commence_time) <= new Date() : false,
      completed: false,
      detail: null,
      home: { name: row.home_team, short: '', logo: null, score: null },
      away: { name: row.away_team, short: '', logo: null, score: null },
      hasDraw,
      books,
      market: analyseBooks(books, hasDraw),
    };
  });

  memoSet(cacheKey, events, 5 * 60 * 1000);
  return events;
}

/**
 * SportyBet Nigeria 1X2 feed. Keyless, one bookmaker, real decimal prices.
 * SportyBet publishes `probability` per outcome, but we de-vig from the prices
 * ourselves so every book is treated identically.
 */
function normaliseSportyEvent(raw, key) {
  const league = LEAGUES[key];
  const market1 = (raw.markets || []).find((m) => String(m.id) === '1');
  if (!market1) return null;
  const price = (name) => {
    const hit = (market1.outcomes || []).find(
      (o) => String(o.desc || '').toLowerCase() === name,
    );
    return hit ? toDecimal(hit.odds) : null;
  };
  const home = price('home');
  const draw = price('draw');
  const away = price('away');
  if (!home || !away) return null;

  const books = [{ book: 'SportyBet', home, draw, away }];
  const start = Number(raw.estimateStartTime);
  return {
    id: `sporty:${raw.eventId}`,
    source: 'sportybet',
    league: key,
    leagueLabel: league.label,
    name: `${raw.homeTeamName} vs ${raw.awayTeamName}`,
    start: Number.isFinite(start) ? new Date(start).toISOString() : null,
    status: raw.matchStatus || null,
    live: Number(raw.status) === 1,
    completed: false,
    detail: raw.matchStatus || null,
    home: { name: raw.homeTeamName || 'Home', short: '', logo: null, score: null },
    away: { name: raw.awayTeamName || 'Away', short: '', logo: null, score: null },
    hasDraw: true,
    books,
    market: analyseBooks(books, true),
  };
}

async function fetchSportyBet(env, key) {
  const league = LEAGUES[key];
  if (!league || !league.sporty) return null;
  const cacheKey = `sporty:${key}`;
  const cached = memoGet(cacheKey);
  if (cached) return cached;

  const url = new URL(`${SPORTYBET_BASE}/pcUpcomingEvents`);
  url.searchParams.set('sportId', 'sr:sport:1');
  url.searchParams.set('tournamentId', `sr:tournament:${league.sporty}`);
  url.searchParams.set('marketId', '1');
  url.searchParams.set('pageSize', '40');
  url.searchParams.set('pageNum', '1');
  url.searchParams.set('option', '1');

  const res = await fetch(url.toString(), { headers: SPORTYBET_HEADERS });
  if (!res.ok) throw new Error(`SportyBet ${res.status}`);
  const payload = await res.json();
  const tournaments = payload?.data?.tournaments || [];
  const events = [];
  for (const tournament of tournaments) {
    for (const raw of tournament.events || []) {
      const event = normaliseSportyEvent(raw, key);
      if (event) events.push(event);
    }
  }
  memoSet(cacheKey, events, 60 * 1000);
  return events;
}

async function fetchEspn(env, key) {
  const league = LEAGUES[key];
  const cacheKey = `espn:${key}`;
  const cached = memoGet(cacheKey);
  if (cached) return cached;

  const res = await fetch(`${ESPN_BASE}/${league.sport}/${league.espn}/scoreboard`, {
    headers: { accept: 'application/json', 'user-agent': 'PunterAI-Pro/1.0' },
  });
  if (!res.ok) throw new Error(`ESPN ${res.status}`);
  const data = await res.json();
  const events = (data.events || [])
    .map((event) => normaliseEspnEvent(event, key))
    .filter(Boolean);

  memoSet(cacheKey, events, 60 * 1000);
  return events;
}

/**
 * Feed priority: SportyBet for football, then the multi-book feed, then ESPN.
 * Each step degrades rather than failing the request.
 */
async function loadEvents(env, key) {
  let events = null;
  let source = 'espn';

  if (LEAGUES[key].sporty) {
    try {
      events = await fetchSportyBet(env, key);
      if (events && events.length) source = 'sportybet';
    } catch { /* fall through */ }
  }
  if (!events || !events.length) {
    try {
      events = await fetchOddsApi(env, key);
      if (events && events.length) source = 'oddsapi';
    } catch { /* fall through */ }
  }
  if (!events || !events.length) {
    events = await fetchEspn(env, key);
    source = 'espn';
  }
  return { events, source };
}

/* ------------------------------------------------------------------ search */

const STOP = new Set(['vs', 'v', 'the', 'fc', 'at', 'and', 'de', 'cf']);

function tokens(text) {
  return String(text || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .filter((token) => token.length > 2 && !STOP.has(token));
}

function scoreEvent(event, query) {
  const wanted = tokens(query);
  if (!wanted.length) return 0;
  const haystack = tokens(`${event.name} ${event.home.name} ${event.away.name} ${event.home.short} ${event.away.short}`);
  const set = new Set(haystack);
  let hits = 0;
  for (const token of wanted) {
    if (set.has(token)) hits += 2;
    else if (haystack.some((word) => word.startsWith(token) || token.startsWith(word))) hits += 1;
  }
  return hits / (wanted.length * 2);
}

/* ------------------------------------------------------------- match context */

/** Bookmaker-facing platforms this app knows about. Only SportyBet publishes
 * an open price feed today; the rest are conversion targets. */
const PLATFORMS = [
  { id: 'sportybet', label: 'SportyBet', priced: true },
  { id: 'bet9ja', label: 'Bet9ja', priced: false },
  { id: 'betking', label: 'BetKing', priced: false },
  { id: 'gokabet', label: 'GokaBet', priced: false },
  { id: 'onexbet', label: '1xBet', priced: false },
];

const ALIASES = {
  'man utd': 'manchester united', 'man united': 'manchester united', 'man city': 'manchester city',
  'wolves': 'wolverhampton', 'spurs': 'tottenham', 'forest': 'nottingham forest',
  'psg': 'paris saint germain', 'inter': 'inter milan', 'milan': 'ac milan',
  'barca': 'barcelona', 'juve': 'juventus', 'dortmund': 'borussia dortmund',
  'bayern': 'bayern munich', 'atletico': 'atletico madrid', 'sociedad': 'real sociedad',
};

function nameKeys(name) {
  let text = String(name || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  for (const [alias, full] of Object.entries(ALIASES)) {
    if (text.includes(alias)) text += ` ${full}`;
  }
  return text.split(' ').filter((t) => t.length > 2);
}

function teamScore(candidate, target) {
  const a = new Set(nameKeys(candidate));
  let hits = 0;
  for (const token of nameKeys(target)) {
    if (a.has(token)) hits += 2;
    else if ([...a].some((x) => x.startsWith(token) || token.startsWith(x))) hits += 1;
  }
  return hits;
}

function scoreValue(node) {
  if (node === null || node === undefined) return '-';
  if (typeof node === 'object') return node.displayValue ?? node.value ?? '-';
  return String(node);
}

async function espnTeamList(key) {
  const league = LEAGUES[key];
  if (!league || league.sport !== 'soccer') return null;
  const cacheKey = `espnteams:${key}`;
  const cached = memoGet(cacheKey);
  if (cached) return cached;
  const res = await fetch(`${ESPN_BASE}/soccer/${league.espn}/teams`, {
    headers: { accept: 'application/json' },
  });
  if (!res.ok) return null;
  const data = await res.json();
  const teams = data?.sports?.[0]?.leagues?.[0]?.teams?.map((row) => row.team).filter(Boolean) || [];
  if (teams.length) memoSet(cacheKey, teams, 30 * 60 * 1000);
  return teams;
}

async function cornersForEvent(key, eventId) {
  const league = LEAGUES[key];
  if (!league || league.sport !== 'soccer' || !eventId) return null;
  const cacheKey = `corners:${eventId}`;
  const cached = memoGet(cacheKey);
  if (cached) return cached;
  const res = await fetch(`${ESPN_BASE}/soccer/${league.espn}/summary?event=${eventId}`, {
    headers: { accept: 'application/json' },
    signal: AbortSignal.timeout(10_000),
  });
  if (!res.ok) return null;
  const data = await res.json().catch(() => null);
  const teams = data?.boxscore?.teams || [];
  if (!teams.length) return null;
  const read = (side) => {
    const row = teams.find((team) => team.homeAway === side);
    const stat = (row?.statistics || []).find((entry) => /corner/i.test(entry.name || ''));
    const value = stat ? Number(stat.displayValue ?? stat.value) : null;
    return Number.isFinite(value) ? value : null;
  };
  const result = { home: read('home'), away: read('away') };
  memoSet(cacheKey, result, 30 * 60 * 1000);
  return result;
}

async function espnSchedule(key, teamId, season) {
  const league = LEAGUES[key];
  if (!league || league.sport !== 'soccer' || !teamId) return null;
  const cacheKey = `espnsched:${key}:${teamId}:${season || 'current'}`;
  const cached = memoGet(cacheKey);
  if (cached) return cached;
  const suffix = season ? `?season=${season}` : '';
  const res = await fetch(`${ESPN_BASE}/soccer/${league.espn}/teams/${teamId}/schedule${suffix}`, {
    headers: { accept: 'application/json' },
  });
  if (!res.ok) return null;
  const data = await res.json();
  memoSet(cacheKey, data, 10 * 60 * 1000);
  return data;
}

function recentResults(schedule, teamId) {
  return (schedule?.events || [])
    .map((event) => ({ event, comp: event.competitions?.[0] }))
    .filter(({ comp }) => comp?.status?.type?.completed)
    .map(({ event, comp }) => {
      const own = (comp.competitors || []).find((c) => String(c.team?.id) === String(teamId));
      const opp = (comp.competitors || []).find((c) => String(c.team?.id) !== String(teamId));
      if (!own || !opp) return null;
      return {
        id: event.id || comp.id || comp.uid || null,
        date: (comp.date || '').slice(0, 10),
        opponent: opp.team?.displayName || 'Opponent',
        score: `${scoreValue(own.score)}-${scoreValue(opp.score)}`,
        result: own.winner ? 'W' : opp.winner ? 'L' : 'D',
        side: own.homeAway || 'home',
      };
    })
    .filter(Boolean)
    .slice(0, 5);
}

/**
 * Real football context for a fixture: recent form and head-to-head history
 * from ESPN's team feeds. Returns null rather than guessing when a team cannot
 * be resolved, because a wrong form line is worse than none.
 */
async function fetchMatchContext(event) {
  const teams = await espnTeamList(event.league);
  if (!teams || !teams.length) return null;

  const resolve = (name) => teams
    .map((team) => ({ team, score: teamScore(team.displayName, name) }))
    .sort((a, b) => b.score - a.score)[0];

  const home = resolve(event.home.name);
  const away = resolve(event.away.name);
  if (!home || !away || home.score < 2 || away.score < 2) return null;
  if (String(home.team.id) === String(away.team.id)) return null;

  const lastSeason = new Date().getUTCFullYear() - 1;
  const [homeSchedule, awaySchedule, homeLastSeason] = await Promise.all([
    espnSchedule(event.league, home.team.id),
    espnSchedule(event.league, away.team.id),
    espnSchedule(event.league, home.team.id, lastSeason).catch(() => null),
  ]);

  const homeResults = recentResults(homeSchedule, home.team.id);
  const awayResults = recentResults(awaySchedule, away.team.id);

  const seenMeetings = new Set();
  const meetings = [homeSchedule, homeLastSeason]
    .flatMap((feed) => feed?.events || [])
    .map((row) => ({ row, comp: row.competitions?.[0] }))
    .filter(({ comp }) => comp?.status?.type?.completed && (comp.competitors || []).some((c) => String(c.team?.id) === String(away.team.id)))
    .map(({ row, comp }) => ({
      id: row.id || comp.id || null,
      date: (comp.date || '').slice(0, 10),
      line: (comp.competitors || []).map((c) => `${c.team?.abbreviation || ''} ${scoreValue(c.score)}`).join(' — '),
    }))
    .filter((row) => {
      if (!row.date || seenMeetings.has(row.date)) return false;
      seenMeetings.add(row.date);
      return true;
    })
    .sort((a, b) => (a.date < b.date ? 1 : -1))
    .slice(0, 5);

  if (!homeResults.length && !awayResults.length && !meetings.length) return null;

  const ids = [...new Set([
    ...meetings.map((row) => row.id),
    ...homeResults.map((row) => row.id),
    ...awayResults.map((row) => row.id),
  ].filter(Boolean))].slice(0, 14);

  const cornerRows = new Map();
  await Promise.all(ids.map(async (id) => {
    const row = await cornersForEvent(event.league, id).catch(() => null);
    if (row && (row.home !== null || row.away !== null)) cornerRows.set(id, row);
  }));

  const average = (values) => (values.length
    ? Number((values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(1))
    : null);

  const teamCorners = (results) => {
    const values = results
      .map((row) => {
        const corners = cornerRows.get(row.id);
        if (!corners) return null;
        return row.side === 'away' ? corners.away : corners.home;
      })
      .filter((value) => Number.isFinite(value));
    return { average: average(values), matches: values.length, values };
  };

  const h2hCorners = (() => {
    const totals = [];
    const homeValues = [];
    const awayValues = [];
    for (const meeting of meetings) {
      const corners = cornerRows.get(meeting.id);
      if (!corners || !Number.isFinite(corners.home) || !Number.isFinite(corners.away)) continue;
      totals.push(corners.home + corners.away);
      homeValues.push(corners.home);
      awayValues.push(corners.away);
    }
    return {
      matches: totals.length,
      averageTotal: average(totals),
      averageHome: average(homeValues),
      averageAway: average(awayValues),
    };
  })();

  return {
    teams: { home: home.team.displayName, away: away.team.displayName },
    form: {
      home: { team: home.team.displayName, sequence: homeResults.map((r) => r.result).join(''), results: homeResults },
      away: { team: away.team.displayName, sequence: awayResults.map((r) => r.result).join(''), results: awayResults },
    },
    h2h: { meetings },
    corners: {
      home: teamCorners(homeResults),
      away: teamCorners(awayResults),
      h2h: h2hCorners,
    },
    missing: [
      'Referee appointment and card average (not published by these feeds before kick-off)',
      'Confirmed line-ups and late fitness news',
      'Manager head-to-head record',
      'European campaign history (the team feed only carries domestic league fixtures)',
    ],
  };
}

/* --------------------------------------------------------------- ai layer */

const AI_SYSTEM = `You are Sport Analyst, a football market research assistant for Nigerian bettors.

You receive a DATA block computed from live feeds. Prices come from SportyBet's Nigerian 1X2 feed; form and head-to-head come from ESPN team feeds. Those numbers are authoritative.
Rules:
- Football first. Work through what DATA supports in this order: price and margin, current form, head-to-head, then the gaps.
- Referee, card averages, line-ups and manager records are usually missing from DATA. Never invent them: list them in dataGaps and say plainly that bookings cannot be leaned on without a referee appointment.
- When DATA says lineShop is false, say the fixture is a single-book market with no line-shopping, so no positive edge exists; do not describe a book-to-book edge.
- Never change or recalculate a probability, price or edge. Quote them exactly.
- If DATA is thin, say so in dataGaps instead of guessing.
- You give research, not betting advice. Never promise profit.
Reply with ONE JSON object and nothing else:
{"headline":string,"lean":string,"confidence":number,"reasoning":string[],"risks":string[],"dataGaps":string[]}
"confidence" is 0-100 and refers to your confidence in the market read, not a win guarantee.`;

async function aiNarrate(env, event, context) {
  const apiKey = env.OPENAI_API_KEY;
  if (!apiKey) return { ai: null, aiError: 'OPENAI_API_KEY is not configured' };

  const base = (env.AI_BASE_URL || 'https://freebuff.com/api/v1/paid').replace(/\/+$/, '');
  const model = env.AI_MODEL || 'gpt-4o-mini';

  const pct = (value) => `${(value * 100).toFixed(1)}%`;
  const money = (value) => `${(value * 100).toFixed(1)}%`;
  const data = {
    match: event.name,
    league: event.leagueLabel,
    kickoff: event.start,
    status: event.status,
    lineShop: event.market ? event.market.lineShop : false,
    context: context || null,
    bookmakers: event.books.map((book) => ({
      book: book.book,
      home: book.home,
      draw: book.draw ?? null,
      away: book.away,
    })),
    consensusFairProbability: Object.fromEntries(
      Object.entries(event.market.consensus).map(([k, v]) => [k, pct(v)]),
    ),
    bestPrices: Object.fromEntries(
      Object.entries(event.market.best).map(([k, v]) => [k, { price: v.price, book: v.book }]),
    ),
    bestPriceEdge: Object.fromEntries(
      Object.entries(event.market.edge).map(([k, v]) => [k, money(v)]),
    ),
    marketMargin: pct(event.market.averageMargin),
    arbitrage: event.market.arb,
    lineMovement: event.books.length > 1
      ? 'Multiple books compared; see bestPrices against consensus.'
      : 'Only one bookmaker available, so no line-shopping signal.',
  };

  const body = {
    model,
    temperature: 0.2,
    messages: [
      { role: 'system', content: AI_SYSTEM },
      { role: 'user', content: `DATA:\n${JSON.stringify(data, null, 2)}` },
    ],
  };

  const ask = async () => {
    const res = await fetch(`${base}/chat/completions`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: `Bearer ${apiKey}` },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(25_000),
    });
    if (!res.ok) throw new Error(`AI ${res.status}: ${(await res.text()).slice(0, 180)}`);
    const payload = await res.json();
    const text = payload.choices?.[0]?.message?.content;
    if (!text) throw new Error('AI returned no content');
    return text;
  };

  const parse = (text) => {
    const cleaned = String(text).replace(/^```(?:json)?/i, '').replace(/```$/, '').trim();
    const start = cleaned.indexOf('{');
    const end = cleaned.lastIndexOf('}');
    if (start === -1 || end === -1) throw new Error('AI returned no JSON object');
    const parsed = JSON.parse(cleaned.slice(start, end + 1));
    const strings = (value) => (Array.isArray(value) ? value.filter((v) => typeof v === 'string').slice(0, 6) : []);
    return {
      headline: typeof parsed.headline === 'string' ? parsed.headline.slice(0, 240) : 'Market read',
      lean: typeof parsed.lean === 'string' ? parsed.lean.slice(0, 160) : '',
      confidence: Number.isFinite(Number(parsed.confidence))
        ? Math.max(0, Math.min(100, Math.round(Number(parsed.confidence))))
        : null,
      reasoning: strings(parsed.reasoning),
      risks: strings(parsed.risks),
      dataGaps: strings(parsed.dataGaps),
    };
  };

  try {
    return { ai: parse(await ask()), aiError: null };
  } catch (first) {
    try {
      const retry = await ask();
      return { ai: parse(retry), aiError: null };
    } catch (error) {
      return { ai: null, aiError: String(first.message || error.message || error).slice(0, 200) };
    }
  }
}

/* ------------------------------------------------------------------- ask */

const ASK_SYSTEM = `You are Sport Analyst, a football betting-market explainer for Nigerian bettors.

Answer in plain English, at most 110 words, short paragraphs or a compact list. No preamble.
Rules:
- Use only numbers in DATA. Quote them exactly; never recompute or invent one.
- If DATA has no fixture, answer only about margin, fair probability, edge, Kelly or how to read a slip, and say you need a fixture for anything specific.
- Never invent injuries, line-ups, referees, card averages or form that DATA does not contain.
- Say when the fixture is a single book with no line-shopping and no positive edge.
- Never promise profit, never call a selection a banker or a sure thing.`;

async function aiCall(env, system, user) {
  if (!env.OPENAI_API_KEY) throw new Error('OPENAI_API_KEY is not configured');
  const base = (env.AI_BASE_URL || 'https://www.openllm.sh/v1').replace(/\/+$/, '');
  const model = env.AI_MODEL || 'plus';
  const res = await fetch(`${base}/chat/completions`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', authorization: `Bearer ${env.OPENAI_API_KEY}` },
    body: JSON.stringify({
      model,
      temperature: 0.2,
      messages: [{ role: 'system', content: system }, { role: 'user', content: user }],
    }),
    signal: AbortSignal.timeout(30_000),
  });
  if (!res.ok) throw new Error(`AI ${res.status}: ${(await res.text()).slice(0, 160)}`);
  const payload = await res.json();
  const text = payload.choices?.[0]?.message?.content;
  if (!text) throw new Error('AI returned no content');
  return String(text).trim();
}

function askContext(event, context) {
  if (!event) return { note: 'No fixture selected. Answer conceptually only.' };
  const market = event.market;
  return {
    match: event.name,
    league: event.leagueLabel,
    kickoff: event.start,
    bookmakers: event.books.map((b) => ({ book: b.book, home: b.home, draw: b.draw ?? null, away: b.away })),
    fairProbability: market
      ? {
          home: `${(market.consensus.home * 100).toFixed(1)}%`,
          draw: market.consensus.draw === null || market.consensus.draw === undefined ? null : `${(market.consensus.draw * 100).toFixed(1)}%`,
          away: `${(market.consensus.away * 100).toFixed(1)}%`,
        }
      : null,
    margin: market ? `${(market.averageMargin * 100).toFixed(1)}%` : null,
    bookCount: event.books.length,
    lineShop: market ? market.lineShop : false,
    form: context ? context.form : null,
    headToHead: context ? context.h2h : null,
    missing: context ? context.missing : null,
  };
}

async function handleAsk(request, env) {
  if (!sameOrigin(request)) return json({ error: 'Cross-origin request rejected' }, 403);
  let body;
  try {
    body = await readBody(request);
  } catch (error) {
    return json({ error: String(error.message || 'Invalid body') }, 400);
  }

  const question = String(body.question || '').slice(0, 400).trim();
  if (!question) return json({ error: 'Ask a question first' }, 400);
  const key = body.sport || 'epl';
  if (!LEAGUES[key]) return json({ error: `Unknown sport "${key}"` }, 400);

  let event = null;
  let context = null;
  if (body.eventId) {
    try {
      const { events } = await loadEvents(env, key);
      event = events.find((row) => row.id === String(body.eventId)) || null;
    } catch { /* answer conceptually */ }
    if (event) context = await fetchMatchContext(event).catch(() => null);
  }

  const fixture = event ? { id: event.id, name: event.name, start: event.start } : null;
  if (!env.OPENAI_API_KEY) {
    return json({ answer: null, aiError: 'OPENAI_API_KEY is not configured', event: fixture });
  }

  try {
    const answer = await aiCall(
      env,
      ASK_SYSTEM,
      `QUESTION: ${question}\n\nDATA:\n${JSON.stringify(askContext(event, context), null, 2)}`,
    );
    return json({ answer: answer.slice(0, 1800), aiError: null, event: fixture });
  } catch (error) {
    return json({ answer: null, aiError: String(error.message || error).slice(0, 200), event: fixture }, 502);
  }
}

/* ------------------------------------------------------- posts and codes */

const X_URL = /^https?:\/\/(?:www\.|mobile\.)?(?:x|twitter)\.com\/([A-Za-z0-9_]{1,15})\/status\/(\d{5,25})/i;
const CODE_SHAPE = /^[A-Za-z0-9-]{4,24}$/;

const VERIFY_SYSTEM = `You are Sport Analyst checking a tipster's football post against live data.

DATA contains match rows with prices, de-vigged fair probability, current form (last five, most recent first) and head-to-head meetings. It is the only evidence you may use.
Rules:
- Split the post into short factual claims (form, head-to-head, league position, streaks, manager records).
- For each claim give status:
  "supported" when DATA shows it,
  "contradicted" when DATA shows the opposite,
  "cannot verify" when DATA does not cover it. Never guess, and never use outside knowledge.
- evidence must cite the DATA field and the exact numbers or result you compared (for example "headToHead 2026-05-04 CHE 1 — NFO 3").
- A claim about a match with no DATA row is "cannot verify".
- Opinions, predictions and stakes advice are not factual claims: skip them, and mention in summary if the post is mostly opinion.
- Never invent a referee, injury, lineup or statistic.
Reply with ONE JSON object and nothing else:
{"summary":"max 45 words","claims":[{"claim":"...","status":"supported|contradicted|cannot verify","evidence":"..."}],"confidence":0-100}`;

const CODE_SYSTEM = `You are Sport Analyst reading a resolved betting slip.
You receive the legs exactly as the bookmaker returned them, with prices. Analyse the games, not the payout.
Rules:
- Name the book, the number of legs and the combined price. Quote only the numbers given.
- For each leg, say in one line what the pick needs to happen, and whether the listed price looks short or fair relative to nothing more than what you are given. If you have no independent probability, say "no independent read".
- Flag correlated legs (same match), short prices under 1.30, and anything that cannot be read.
- Never invent form, injuries or team news that the payload does not contain.
Reply with ONE JSON object and nothing else:
{"summary":"max 60 words","legs":[{"selection":"...","read":"one line"}],"risks":["short strings"]}`;

function readAiJson(text) {
  const raw = String(text || '');
  const start = raw.indexOf('{');
  const end = raw.lastIndexOf('}');
  if (start < 0 || end <= start) throw new Error('AI did not return JSON');
  return JSON.parse(raw.slice(start, end + 1));
}

async function fetchPost(url) {
  const match = String(url).match(X_URL);
  if (!match) return null;
  const [, handle, id] = match;

  const attempts = [
    {
      name: 'syndication',
      url: `https://cdn.syndication.twimg.com/tweet-result?id=${id}&lang=en&token=a`,
      pick: (data) => ({ author: data.user?.screen_name, text: data.text, date: data.created_at }),
    },
    {
      name: 'fxtwitter',
      url: `https://api.fxtwitter.com/${handle}/status/${id}`,
      pick: (data) => ({ author: data.tweet?.author?.screen_name, text: data.tweet?.text, date: data.tweet?.created_at }),
    },
    {
      name: 'vxtwitter',
      url: `https://api.vxtwitter.com/${handle}/status/${id}`,
      pick: (data) => ({ author: data.user_screen_name, text: data.text, date: data.date }),
    },
  ];

  let lastError = 'no source answered';
  for (const attempt of attempts) {
    try {
      const res = await fetch(attempt.url, {
        headers: {
          accept: 'application/json',
          'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        },
        signal: AbortSignal.timeout(12_000),
      });
      if (!res.ok) {
        lastError = `${attempt.name} ${res.status}`;
        continue;
      }
      const data = await res.json().catch(() => null);
      const picked = data ? attempt.pick(data) : null;
      const text = String(picked?.text || '').trim();
      if (!text) {
        lastError = `${attempt.name} returned no text`;
        continue;
      }
      return {
        author: picked.author || handle,
        text: text.slice(0, 1200),
        date: picked.date || null,
        url: `https://x.com/${handle}/status/${id}`,
      };
    } catch (error) {
      lastError = `${attempt.name} ${String(error.message || 'failed').slice(0, 60)}`;
    }
  }
  throw new Error(`Post lookup failed: ${lastError}`);
}

function fixtureMentions(events, text) {
  const hay = ` ${String(text || '').toLowerCase()} `;
  return events.filter((event) => {
    const names = [...nameKeys(event.home.name), ...nameKeys(event.away.name)];
    return names.filter((token) => hay.includes(token)).length >= 2;
  });
}

async function contextForText(env, sport, text) {
  const { events } = await loadEvents(env, sport);
  const hits = fixtureMentions(events, text).slice(0, 2);
  const rows = [];
  for (const event of hits) {
    const context = await fetchMatchContext(event).catch(() => null);
    rows.push({
      match: event.name,
      league: event.leagueLabel,
      kickoff: event.start,
      prices: event.market
        ? {
            home: event.market.best.home?.price ?? null,
            draw: event.market.best.draw?.price ?? null,
            away: event.market.best.away?.price ?? null,
          }
        : null,
      lineShop: event.market ? event.market.lineShop : false,
      form: context ? context.form : null,
      headToHead: context ? context.h2h : null,
      gaps: context ? context.missing : null,
    });
  }
  return rows;
}

async function resolveSportyCode(code) {
  const res = await fetch(`https://www.sportybet.com/api/ng/orders/share/${encodeURIComponent(code)}`, {
    headers: {
      accept: 'application/json',
      referer: 'https://www.sportybet.com/ng/',
      'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    },
    signal: AbortSignal.timeout(15_000),
  });
  const payload = await res.json().catch(() => null);
  if (!payload) return { ok: false, message: `SportyBet returned ${res.status}` };
  const data = payload.data || {};
  const list = Array.isArray(data.outcomes) ? data.outcomes : Array.isArray(data.bets) ? data.bets : [];
  if (!list.length) {
    return { ok: false, message: payload.message || payload.innerMsg || 'That code has no readable selections' };
  }
  const legs = list.map((row) => {
    const eventName = row.eventName
      || row.event?.name
      || [row.event?.homeTeamName, row.event?.awayTeamName].filter(Boolean).join(' v ');
    return {
      event: eventName || null,
      market: row.marketDesc || row.market?.desc || row.marketName || null,
      selection: row.outcomeDesc || row.outcome?.desc || row.selection || null,
      odds: Number(row.odds ?? row.price) || null,
    };
  }).filter((leg) => leg.selection || leg.event);
  if (!legs.length) return { ok: false, message: 'That code resolved without readable selections' };
  const combined = legs.reduce((total, leg) => total * (leg.odds || 1), 1);
  return { ok: true, legs, combined: Number(combined.toFixed(4)) };
}

async function handleScan(request, env) {
  if (!sameOrigin(request)) return json({ error: 'Cross-origin request rejected' }, 403);
  let body;
  try {
    body = await readBody(request);
  } catch (error) {
    return json({ error: String(error.message || 'Invalid body') }, 400);
  }

  const input = String(body.input || '').trim().slice(0, 500);
  if (!input) return json({ error: 'Paste a post link or a booking code' }, 400);
  const sport = body.sport && LEAGUES[body.sport] ? body.sport : 'epl';

  if (X_URL.test(input)) {
    let post;
    try {
      post = await fetchPost(input);
    } catch (error) {
      return json({ error: String(error.message || 'Could not read that post') }, 502);
    }
    const context = await contextForText(env, sport, post.text).catch(() => []);
    if (!env.OPENAI_API_KEY) {
      return json({ kind: 'post', post, context, claims: null, aiError: 'OPENAI_API_KEY is not configured' });
    }
    try {
      const parsed = readAiJson(await aiCall(
        env,
        VERIFY_SYSTEM,
        `POST by @${post.author}${post.date ? ` on ${post.date}` : ''}:\n${post.text}\n\nDATA:\n${JSON.stringify(context, null, 2)}`,
      ));
      return json({
        kind: 'post',
        post,
        context,
        summary: parsed.summary || null,
        claims: Array.isArray(parsed.claims) ? parsed.claims.slice(0, 12) : [],
        confidence: Number.isFinite(parsed.confidence) ? parsed.confidence : null,
        aiError: null,
      });
    } catch (error) {
      return json({ kind: 'post', post, context, claims: null, aiError: String(error.message || error).slice(0, 200) }, 502);
    }
  }

  const code = input.replace(/\s+/g, '');
  if (!CODE_SHAPE.test(code)) {
    return json({ error: 'That is neither an X post link nor a booking code' }, 400);
  }

  let resolved;
  try {
    resolved = await resolveSportyCode(code);
  } catch (error) {
    return json({ kind: 'code', code, resolved: false, message: String(error.message || 'Code lookup failed').slice(0, 200) }, 502);
  }

  if (!resolved.ok) {
    return json({
      kind: 'code',
      code,
      resolved: false,
      message: `SportyBet could not resolve ${code.toUpperCase()}: ${String(resolved.message || 'no selections returned').replace(/\.$/, '')}. Codes from Bet9ja, BetKing and GokaBet have no open reader, so paste the slip text into the audit instead.`,
    });
  }

  let ai = null;
  let aiError = null;
  if (env.OPENAI_API_KEY) {
    try {
      const parsed = readAiJson(await aiCall(
        env,
        CODE_SYSTEM,
        JSON.stringify({ book: 'SportyBet', code, combined: resolved.combined, legs: resolved.legs }, null, 2),
      ));
      ai = parsed;
    } catch (error) {
      aiError = String(error.message || error).slice(0, 200);
    }
  }

  return json({ kind: 'code', code, book: 'SportyBet', resolved: true, legs: resolved.legs, combined: resolved.combined, ai, aiError });
}

/* --------------------------------------------------------------- helpers */

function json(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: JSON_HEADERS });
}

function sameOrigin(request) {
  const origin = request.headers.get('origin');
  if (!origin) return true; // non-browser client
  try {
    return new URL(origin).origin === new URL(request.url).origin;
  } catch {
    return false;
  }
}

async function readBody(request) {
  const text = await request.text();
  if (text.length > MAX_RESEARCH_BODY) throw new Error('Request body too large');
  if (!text) return {};
  return JSON.parse(text);
}

/* ----------------------------------------------------------------- routes */

async function handleOdds(url, env) {
  const key = url.searchParams.get('sport') || 'epl';
  if (!LEAGUES[key]) return json({ error: `Unknown sport "${key}"` }, 400);
  try {
    const { events, source } = await loadEvents(env, key);
    const limit = Math.min(Number(url.searchParams.get('limit')) || 12, 24);
    const priced = events.filter((event) => event.books.length && event.market).length;
    return json({
      sport: key,
      league: LEAGUES[key],
      source,
      multiBook: source === 'oddsapi',
      pricedEvents: priced,
      updated: new Date().toISOString(),
      events: events
        .filter((event) => !event.completed)
        .sort((a, b) => new Date(a.start || 0) - new Date(b.start || 0))
        .slice(0, limit),
    });
  } catch (error) {
    return json({ error: 'Could not load odds feed', detail: String(error.message || error) }, 502);
  }
}

async function handleResearch(request, env) {
  if (!sameOrigin(request)) return json({ error: 'Cross-origin request rejected' }, 403);
  let body;
  try {
    body = await readBody(request);
  } catch (error) {
    return json({ error: String(error.message || 'Invalid body') }, 400);
  }

  const key = body.sport || 'epl';
  if (!LEAGUES[key]) return json({ error: `Unknown sport "${key}"` }, 400);
  const query = String(body.query || '').slice(0, 120);
  const eventId = body.eventId ? String(body.eventId) : null;

  let events;
  try {
    ({ events } = await loadEvents(env, key));
  } catch (error) {
    return json({ error: 'Could not load fixtures', detail: String(error.message || error) }, 502);
  }

  const upcoming = events.filter((event) => !event.completed);

  if (eventId) {
    const chosen = upcoming.find((event) => event.id === eventId);
    if (!chosen) return json({ error: 'Event not found in the current feed' }, 404);
    return json(await buildReport(env, chosen));
  }

  if (!query.trim()) {
    return json({
      candidates: upcoming.slice(0, 10).map((event) => ({
        id: event.id, name: event.name, start: event.start, league: event.leagueLabel,
      })),
    });
  }

  const ranked = upcoming
    .map((event) => ({ event, score: scoreEvent(event, query) }))
    .sort((a, b) => b.score - a.score);

  const strong = ranked.filter((row) => row.score >= 0.5);
  if (!strong.length) {
    return json({
      error: `No upcoming ${LEAGUES[key].label} fixture matched "${query}"`,
      candidates: upcoming.slice(0, 10).map((event) => ({
        id: event.id, name: event.name, start: event.start, league: event.leagueLabel,
      })),
    }, 404);
  }

  if (strong.length > 1 && strong[0].score === strong[1].score) {
    return json({
      ambiguous: true,
      candidates: strong.slice(0, 6).map((row) => ({
        id: row.event.id, name: row.event.name, start: row.event.start, league: row.event.leagueLabel,
      })),
    });
  }

  return json(await buildReport(env, strong[0].event));
}

async function buildReport(env, event) {
  const context = await fetchMatchContext(event).catch(() => null);
  const { ai, aiError } = await aiNarrate(env, event, context);
  const sourceName = event.source === 'sportybet'
    ? 'SportyBet Nigeria · 1X2'
    : event.source === 'oddsapi'
      ? 'The Odds API · multi-bookmaker'
      : 'ESPN scoreboard feed';
  const sources = [{ name: sourceName, kind: 'feed' }];
  if (event.books.length) {
    sources.push({
      name: `Prices: ${[...new Set(event.books.map((b) => b.book))].join(', ')}`,
      kind: 'market',
    });
  }

  const notes = [];
  if (event.books.length <= 1) {
    notes.push('Only one bookmaker is available for this fixture, so no line-shopping edge can be measured.');
  }
  if (!event.market) {
    notes.push('No moneyline prices were published yet, so probabilities are unavailable.');
  }
  if (!env.OPENAI_API_KEY) {
    notes.push('AI narrative is off. Add OPENAI_API_KEY to enable it — market numbers are computed either way.');
  }

  return {
    event,
    ai,
    aiError,
    context,
    sources,
    notes,
    generatedAt: new Date().toISOString(),
  };
}

async function handleConvert(request) {
  if (!sameOrigin(request)) return json({ error: 'Cross-origin request rejected' }, 403);
  let body;
  try {
    body = await readBody(request);
  } catch (error) {
    return json({ error: String(error.message || 'Invalid body') }, 400);
  }

  const text = String(body.text || '').slice(0, 2000);
  if (!text.trim()) return json({ error: 'Paste at least one selection' }, 400);

  const legs = [];
  const errors = [];
  const seen = new Set();

  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const oddsMatch = trimmed.match(/@?\s*(\d+(?:\.\d+)?)\s*$/);
    if (!oddsMatch) {
      errors.push(`No decimal odds found in: "${trimmed.slice(0, 60)}"`);
      continue;
    }
    const odds = Number(oddsMatch[1]);
    if (!Number.isFinite(odds) || odds <= 1) {
      errors.push(`Odds must be greater than 1.00: "${trimmed.slice(0, 60)}"`);
      continue;
    }
    const selection = trimmed.slice(0, oddsMatch.index).replace(/[-–—@|]+$/, '').trim();
    if (!selection) {
      errors.push(`No selection name in: "${trimmed.slice(0, 60)}"`);
      continue;
    }
    const fingerprint = tokens(selection).sort().join(' ');
    if (fingerprint && seen.has(fingerprint)) {
      errors.push(`Duplicate selection removed: "${selection.slice(0, 60)}"`);
      continue;
    }
    if (fingerprint) seen.add(fingerprint);
    legs.push({ selection, odds, raw: trimmed });
  }

  if (!legs.length) return json({ error: 'No valid legs found', errors }, 400);

  const combined = legs.reduce((total, leg) => total * leg.odds, 1);
  const impliedProb = 1 / combined;

  return json({
    legs,
    errors,
    combined: Number(combined.toFixed(4)),
    combinedAmerican: decimalToAmerican(combined),
    impliedProb,
    fairOddsIfEven: Number((1 / impliedProb).toFixed(4)),
    note: 'Rebuilt from the prices you pasted: the same slip at equivalent decimal odds. Minting a real SportyBet ↔ Bet9ja/BetKing/GokaBet booking code needs that bookmaker partner API; no code is created here.',
  });
}

async function route(request, env) {
  const url = new URL(request.url);
  const { pathname } = url;

  if (request.method === 'OPTIONS' && pathname.startsWith('/api/')) {
    return new Response(null, {
      status: 204,
      headers: { allow: 'GET,POST,OPTIONS', 'cache-control': 'no-store' },
    });
  }

  if (pathname === '/api/health') {
    return json({
      ok: true,
      name: 'Sport Analyst',
      ai: Boolean(env.OPENAI_API_KEY),
      model: env.OPENAI_API_KEY ? (env.AI_MODEL || 'gpt-4o-mini') : null,
      oddsProvider: 'sportybet',
      extraBooks: env.ODDS_API_KEY ? 'the-odds-api' : null,
      platforms: PLATFORMS,
      football: FOOTBALL_LEAGUES.map((k) => ({ key: k, label: LEAGUES[k].label })),
      other: Object.keys(LEAGUES).filter((k) => LEAGUES[k].sport !== 'soccer')
        .map((k) => ({ key: k, label: LEAGUES[k].label })),
      leagues: Object.fromEntries(Object.entries(LEAGUES).map(([k, v]) => [k, v.label])),
    });
  }

  if (pathname === '/api/odds' && request.method === 'GET') return handleOdds(url, env);
  if (pathname === '/api/research' && request.method === 'POST') return handleResearch(request, env);
  if (pathname === '/api/convert' && request.method === 'POST') return handleConvert(request);
  if (pathname === '/api/ask' && request.method === 'POST') return handleAsk(request, env);
  if (pathname === '/api/scan' && request.method === 'POST') return handleScan(request, env);

  if (pathname.startsWith('/api/')) return json({ error: 'Not found' }, 404);

  if (env.ASSETS) return env.ASSETS.fetch(request);
  return new Response('Not found', { status: 404 });
}

export default {
  async fetch(request, env) {
    try {
      return await route(request, env);
    } catch (error) {
      return json({ error: 'Worker error', detail: String(error?.message || error) }, 500);
    }
  },
};
