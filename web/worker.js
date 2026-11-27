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
 *   POST /api/slip                   resolve a booking code into legs, with per-leg research
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
  norway:     { label: 'Eliteserien',           sport: 'soccer',     espn: 'nor.1',          odds: null,                          sporty: 20 },
  eredivisie: { label: 'Eredivisie',            sport: 'soccer',     espn: 'ned.1',          odds: null,                          sporty: 37 },
  belgium:    { label: 'Belgian Pro League',    sport: 'soccer',     espn: 'bel.1',          odds: null,                          sporty: 38 },
  mls:        { label: 'MLS',                   sport: 'soccer',     espn: 'usa.1',          odds: null,                          sporty: 242 },
  saudi:      { label: 'Saudi Pro League',      sport: 'soccer',     espn: 'ksa.1',          odds: null,                          sporty: 955 },
  championship: { label: 'Championship',        sport: 'soccer',     espn: 'eng.2',          odds: null,                          sporty: null },
  greece:     { label: 'Greek Super League',    sport: 'soccer',     espn: 'gre.1',          odds: null,                          sporty: null },
  ukraine:    { label: 'Ukrainian Premier League', sport: 'soccer',   espn: 'ukr.1',          odds: null,                          sporty: null },
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

function numericScore(node) {
  if (node === null || node === undefined) return null;
  const raw = typeof node === 'object' ? node.value ?? node.displayValue : node;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
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
    .map(({ row, comp }) => {
      const competitors = comp.competitors || [];
      const homeSide = competitors.find((c) => c.homeAway === 'home') || competitors[0];
      const awaySide = competitors.find((c) => c.homeAway === 'away') || competitors[1];
      return {
        id: row.id || comp.id || null,
        date: (comp.date || '').slice(0, 10),
        homeId: homeSide?.team?.id ?? null,
        awayId: awaySide?.team?.id ?? null,
        homeScore: numericScore(homeSide?.score),
        awayScore: numericScore(awaySide?.score),
        line: competitors.map((c) => `${c.team?.abbreviation || ''} ${scoreValue(c.score)}`).join(' — '),
      };
    })
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
    ids: { home: home.team.id, away: away.team.id },
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

async function leagueForEvent(env, eventId) {
  if (!eventId) return null;
  const wanted = String(eventId);
  const keys = await Promise.all(FOOTBALL_LEAGUES.map(async (key) => {
    try {
      const { events } = await loadEvents(env, key);
      return events.some((event) => event.id === wanted) ? key : null;
    } catch {
      return null;
    }
  }));
  return keys.find(Boolean) || null;
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
  let key = body.sport || 'epl';
  if (!LEAGUES[key]) {
    if (key !== 'all') return json({ error: `Unknown sport "${key}"` }, 400);
    const found = await leagueForEvent(env, body.eventId);
    if (!found) return json({ error: 'Pick a fixture before asking about it' }, 400);
    key = found;
  }

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

const CODE_SHAPE = /^[A-Za-z0-9-]{4,24}$/;

const CODE_SYSTEM = `You are Sport Analyst reading a resolved betting slip for a Nigerian punter.

You receive legs exactly as the bookmaker returned them, each with any live enrichment the worker could attach: current 1X2 prices, de-vigged fair probability, last-five form, head-to-head meetings and corners.
Rules:
- Name the number of legs and the combined price. Quote only numbers in DATA.
- For each leg say what has to happen, then name anything that does NOT favour that pick, with the reason (form line, head-to-head result, price shorter than fair, exotic market with no model).
- Mark each leg "aligned", "caution" or "avoid". Be willing to say avoid.
- Then give one safer option: the outcome in the strongest leg with the best de-vigged probability, and what to cut.
- Never invent a referee, injury, lineup or statistic. If DATA has no form for a leg, say it is unverified rather than guessing.
Reply with ONE JSON object and nothing else:
{"summary":"max 60 words","legs":[{"event":"...","selection":"...","verdict":"aligned|caution|avoid","reason":"one line"}],"avoid":["event names to drop"],"bestOption":{"event":"...","pick":"...","why":"one line"}}`;

function readAiJson(text) {
  const raw = String(text || '');
  const start = raw.indexOf('{');
  const end = raw.lastIndexOf('}');
  if (start < 0 || end <= start) throw new Error('AI did not return JSON');
  return JSON.parse(raw.slice(start, end + 1));
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
  const events = Array.isArray(data.outcomes) ? data.outcomes : [];
  const selections = data.ticket?.selections || data.ticket?.bets || [];
  if (!selections.length && !events.length) {
    return { ok: false, message: payload.message || payload.innerMsg || 'That code has no readable selections' };
  }

  const legs = (selections.length ? selections : events).map((selection) => {
    const event = events.find((row) => row.eventId === (selection.eventId || selection.id)) || null;
    const market = event && selection.marketId
      ? (event.markets || []).find((row) => String(row.id) === String(selection.marketId))
      : null;
    const outcome = market && selection.outcomeId
      ? (market.outcomes || []).find((row) => String(row.id) === String(selection.outcomeId))
      : null;
    return {
      eventId: event?.eventId || selection.eventId || null,
      event: event ? `${event.homeTeamName} v ${event.awayTeamName}` : null,
      home: event?.homeTeamName || null,
      away: event?.awayTeamName || null,
      league: event?.sport?.category?.tournament?.name || null,
      kickoff: event?.estimateStartTime ? new Date(Number(event.estimateStartTime)).toISOString() : null,
      market: market?.desc || null,
      selection: outcome?.desc || null,
      odds: Number(outcome?.odds ?? selection.odds) || null,
      marketProbability: outcome?.probability ? Number(outcome.probability) : null,
    };
  }).filter((leg) => leg.event || leg.selection);

  if (!legs.length) return { ok: false, message: 'That code resolved without readable selections' };
  const combined = legs.reduce((total, leg) => total * (leg.odds || 1), 1);
  return {
    ok: true,
    legs,
    combined: Number(combined.toFixed(4)),
    stake: data.ticket?.totalStake ?? null,
    potential: data.ticket?.potentialWinnings ?? null,
  };
}

function pickSide(leg, event) {
  if (!event) return null;
  const pick = String(leg.selection || '').toLowerCase();
  const home = nameKeys(event.home.name);
  const away = nameKeys(event.away.name);
  if (home.some((token) => pick.includes(token))) return 'home';
  if (away.some((token) => pick.includes(token))) return 'away';
  if (/^draw$|^x$|draw/i.test(leg.selection || '')) return 'draw';
  return null;
}

/* Market models: totals, both-teams-to-score, handicaps, double chance and
 * win-to-nil are all derivable from the goals in the form feed. Anything that
 * needs a half-time split or a streak sequence is named as unmodelled instead
 * of being waved away as "not 1X2". */

function poissonP(k, lambda) {
  let fact = 1;
  for (let i = 2; i <= k; i += 1) fact *= i;
  return (Math.exp(-lambda) * Math.pow(lambda, k)) / fact;
}

function scoreMatrix(homeLambda, awayLambda) {
  const limit = 10;
  const rows = [];
  let total = 0;
  for (let h = 0; h <= limit; h += 1) {
    for (let a = 0; a <= limit; a += 1) {
      const p = poissonP(h, homeLambda) * poissonP(a, awayLambda);
      rows.push({ h, a, p });
      total += p;
    }
  }
  return rows.map((row) => ({ ...row, p: row.p / (total || 1) }));
}

function goalProfile(form) {
  const rows = (form?.results || []).map((row) => {
    const [gf, ga] = String(row.score || '').split('-').map(Number);
    return Number.isFinite(gf) && Number.isFinite(ga) ? { gf, ga } : null;
  }).filter(Boolean);
  if (rows.length < 3) return null;
  const mean = (key) => rows.reduce((sum, row) => sum + row[key], 0) / rows.length;
  return { scored: mean('gf'), conceded: mean('ga'), matches: rows.length };
}

function expectedGoals(context) {
  const home = goalProfile(context?.form?.home);
  const away = goalProfile(context?.form?.away);
  if (!home || !away) return null;
  const clamp = (value) => Math.min(4, Math.max(0.25, value));
  return {
    home: clamp((home.scored + away.conceded) / 2),
    away: clamp((away.scored + home.conceded) / 2),
    matches: Math.min(home.matches, away.matches),
  };
}

function lineNumber(text) {
  const match = String(text).match(/-?\d+(?:\.\d+)?/);
  return match ? Number(match[0]) : null;
}

function overProbability(rows, line, side) {
  let over = 0;
  for (const row of rows) {
    const value = side === 'home' ? row.h : side === 'away' ? row.a : row.h + row.a;
    if (value > line) over += row.p;
    else if (value === line) over += row.p / 2;
  }
  return over;
}

function teamFromText(text, event) {
  const lower = String(text || '').toLowerCase();
  if (!event) return null;
  if (nameKeys(event.home.name).some((token) => lower.includes(token))) return 'home';
  if (nameKeys(event.away.name).some((token) => lower.includes(token))) return 'away';
  return null;
}

function marketModel(leg, event, context, consensus) {
  const market = String(leg.market || '').toLowerCase();
  const pick = String(leg.selection || '').toLowerCase();
  if (!market) return { reason: 'the book did not name this market' };

  if (/half|1up|excluded|in a row|correct score|multi-?goal|player|corner|card|booking/.test(market)) {
    const why = /half/.test(market)
      ? 'it needs a half-time split, which these feeds do not publish'
      : /in a row/.test(market)
        ? 'it needs the order goals were scored in, not just the final score'
        : /excluded/.test(market)
          ? 'it excludes specific scorelines, which the goals model cannot price'
          : /1up/.test(market)
            ? 'it is a promotion market with a refund rule the feed cannot price'
            : 'the form feed has no data for that market type';
    return { reason: why };
  }

  const expected = expectedGoals(context);
  if (!expected) return { reason: 'neither side has three scored matches in the feed to build a goals model' };
  const rows = scoreMatrix(expected.home, expected.away);
  const p1 = consensus?.home ?? 0;
  const px = consensus?.draw ?? 0;
  const p2 = consensus?.away ?? 0;

  if (/draw no bet/.test(market)) {
    if (!/home|away/.test(pick)) return { reason: 'the draw-no-bet side was not readable' };
    const chosen = pick.includes('home') ? p1 : p2;
    const total = p1 + p2;
    if (!total) return { reason: 'there is no 1X2 price to build draw-no-bet from' };
    return { label: 'Draw no bet', probability: chosen / total };
  }

  if (/double chance/.test(market)) {
    const hasHome = pick.includes('home');
    const hasAway = pick.includes('away');
    const hasDraw = pick.includes('draw');
    if (!consensus) return { reason: 'there is no 1X2 price to build double chance from' };
    const probability = hasHome && hasDraw ? p1 + px : hasAway && hasDraw ? p2 + px : hasHome && hasAway ? p1 + p2 : null;
    if (probability === null) return { reason: 'the double-chance side was not readable' };
    return { label: 'Double chance', probability };
  }

  if (/win to nil/.test(market)) {
    const side = teamFromText(market, event) || (pick.includes('home') ? 'home' : pick.includes('away') ? 'away' : null);
    if (!side) return { reason: 'the team in the win-to-nil market was not readable' };
    const won = rows.filter((row) => (side === 'home' ? row.h > 0 && row.a === 0 : row.a > 0 && row.h === 0))
      .reduce((sum, row) => sum + row.p, 0);
    const probability = /^no\b/.test(pick) ? 1 - won : won;
    return { label: `Win to nil (${side})`, probability };
  }

  if (/gg\/ng|both teams to score|draw or gg/.test(market)) {
    const btts = rows.filter((row) => row.h > 0 && row.a > 0).reduce((sum, row) => sum + row.p, 0);
    if (/draw or gg/.test(market)) {
      const either = rows.filter((row) => row.h === row.a || (row.h > 0 && row.a > 0)).reduce((sum, row) => sum + row.p, 0);
      return { label: 'Draw or both teams to score', probability: /^no\b/.test(pick) ? 1 - either : either };
    }
    return { label: 'Both teams to score', probability: /^(no|ng)\b/.test(pick) ? 1 - btts : btts };
  }

  if (/asian handicap|handicap/.test(market)) {
    const side = pick.includes('home') ? 'home' : pick.includes('away') ? 'away' : null;
    const line = lineNumber(pick);
    if (!side || line === null) return { reason: 'the handicap line or side was not readable' };
    const drawn = pick.includes('+') ? line : -Math.abs(line);
    let win = 0;
    let push = 0;
    for (const row of rows) {
      const adjusted = (side === 'home' ? row.h : row.a) + drawn - (side === 'home' ? row.a : row.h);
      if (adjusted > 0) win += row.p;
      else if (adjusted === 0) push += row.p;
    }
    return { label: `Asian handicap ${drawn > 0 ? '+' : ''}${drawn} (${side})`, probability: win + push / 2 };
  }

  if (/^(home|away) (team )?or over/.test(market)) {
    const side = market.startsWith('home') ? 'home' : 'away';
    const line = lineNumber(market);
    if (line === null) return { reason: 'the goals line in that combined market was not readable' };
    const over = overProbability(rows, line, null);
    const wins = rows.filter((row) => (side === 'home' ? row.h > row.a : row.a > row.h));
    const win = wins.reduce((sum, row) => sum + row.p, 0);
    const both = wins.filter((row) => row.h + row.a > line).reduce((sum, row) => sum + row.p, 0);
    const probability = Math.min(1, win + over - both);
    const team = side === 'home' ? event?.home?.name : event?.away?.name;
    return { label: `${team || side} win or over ${line}`, probability };
  }

  if (/over\/under|total goals/.test(market)) {
    const line = lineNumber(pick);
    if (line === null) return { reason: 'the goals line was not readable' };
    const teamSide = teamFromText(market, event);
    const over = overProbability(rows, line, teamSide);
    const wantsOver = /over/.test(pick) && !/under/.test(pick);
    const wantsUnder = /under/.test(pick) && !/over/.test(pick);
    if (!wantsOver && !wantsUnder) return { reason: 'the over/under side was not readable' };
    const probability = wantsOver ? over : 1 - over;
    const teamName = teamSide === 'home' ? event?.home?.name : teamSide === 'away' ? event?.away?.name : null;
    return { label: `${teamName ? `${teamName} ` : ''}${wantsOver ? 'Over' : 'Under'} ${line}`, probability };
  }

  return { reason: 'this market type is not one the goals model can price' };
}

async function enrichLeg(events, leg) {
  const implied = leg.odds ? 1 / leg.odds : null;
  const base = { ...leg, implied, flags: [], alternative: null, analysed: false };
  if (!leg.home || !leg.away) return { ...base, read: 'No fixture detail was returned for this leg.' };

  if (!implied) {
    base.flags.push({ level: 'caution', text: 'No price was returned for this pick.' });
  } else if (implied < 0.4) {
    base.flags.push({ level: 'avoid', text: `The book makes this a ${(implied * 100).toFixed(0)}% shot at ${leg.odds.toFixed(2)}; a long shot inside a multi.` });
  } else if (implied < 0.6) {
    base.flags.push({ level: 'caution', text: `Book implies ${(implied * 100).toFixed(0)}% at ${leg.odds.toFixed(2)} — closer to a coin flip than it looks.` });
  } else if (leg.odds < 1.25) {
    base.flags.push({ level: 'caution', text: `Very short at ${leg.odds.toFixed(2)}: one miss wipes the whole slip.` });
  }

  const event = events.find((row) => leg.eventId && String(row.id).endsWith(String(leg.eventId).split(':').pop()))
    || events.find((row) => teamScore(row.home.name, leg.home) >= 2 && teamScore(row.away.name, leg.away) >= 2)
    || null;

  if (!event) {
    return { ...base, read: 'Fixture is outside the leagues this app prices, so only the book price is known.' };
  }

  const context = await fetchMatchContext(event).catch(() => null);
  const marketText = String(leg.market || '').toLowerCase();
  const readsAs1X2 = !/double chance|draw no bet|over\/under|total goals|handicap|to score|win to nil|gg\/ng|both teams|draw or|1up|half|excluded|in a row|correct score/.test(marketText);
  const side = readsAs1X2 ? pickSide(leg, event) : null;
  const flags = [];

  let model = null;
  if (!side) {
    model = marketModel(leg, event, context, event.market?.consensus || null);
    if (model.reason) {
      flags.push({
        level: 'caution',
        text: `No model for "${leg.market || 'this market'}": ${model.reason}. Only the book's price is known.`,
      });
    }
  }

  if (side && side !== 'draw') {
    const form = context?.form?.[side];
    if (form?.results?.length) {
      const losses = form.results.filter((row) => row.result === 'L').length;
      const wins = form.results.filter((row) => row.result === 'W').length;
      if (losses >= 4) flags.push({ level: 'avoid', text: `${form.team} lost ${losses} of the last ${form.results.length} (${form.sequence}).` });
      else if (losses >= 3) flags.push({ level: 'caution', text: `${form.team} lost ${losses} of the last ${form.results.length} (${form.sequence}).` });
      if (wins === 0) flags.push({ level: 'caution', text: `${form.team} have not won in their last ${form.results.length}.` });
    }
  }

  const meetings = context?.h2h?.meetings || [];
  const ownId = context?.ids?.[side];
  if (side && side !== 'draw' && meetings.length && ownId !== undefined && ownId !== null) {
    const lost = meetings.filter((row) => {
      const atHome = String(row.homeId) === String(ownId);
      const atAway = String(row.awayId) === String(ownId);
      if (!atHome && !atAway) return false;
      const own = atHome ? row.homeScore : row.awayScore;
      const other = atHome ? row.awayScore : row.homeScore;
      return Number.isFinite(own) && Number.isFinite(other) && own < other;
    }).length;
    if (lost >= 2) flags.push({ level: 'caution', text: `Lost ${lost} of the last ${meetings.length} meetings between these sides.` });
  }

  let alternative = null;
  if (event.market && side) {
    const fair = event.market.consensus[side];
    if (Number.isFinite(fair) && leg.odds) {
      const edge = leg.odds * fair - 1;
      if (edge < -0.08) {
        flags.push({ level: 'caution', text: `${leg.odds.toFixed(2)} is short of the fair ${(1 / fair).toFixed(2)} (${(edge * 100).toFixed(1)}% at that price).` });
      }
    }
    const sides = event.hasDraw ? ['home', 'draw', 'away'] : ['home', 'away'];
    const best = sides.slice().sort((a, b) => event.market.consensus[b] - event.market.consensus[a])[0];
    if (best && best !== side) {
      alternative = {
        side: best,
        name: best === 'home' ? event.home.name : best === 'draw' ? 'Draw' : event.away.name,
        price: event.market.best[best]?.price ?? null,
        fair: event.market.consensus[best],
      };
    }
  }

  if (!event.market) flags.push({ level: 'caution', text: 'No price in the feed for this fixture, so the base cannot be checked.' });

  let read = flags.length ? flags[0].text : 'Nothing in the feed contradicts this pick.';
  if (model && Number.isFinite(model.probability) && leg.odds) {
    const implied = 1 / leg.odds;
    const edge = model.probability * leg.odds - 1;
    const sentence = edge < 0
      ? `Model gives ${(model.probability * 100).toFixed(0)}% for ${model.label} from ${expectedGoals(context)?.matches || 5} scored matches a side; ${leg.odds.toFixed(2)} needs ${(implied * 100).toFixed(0)}%, so the price is short by ${Math.abs(edge * 100).toFixed(0)} points.`
      : `Model gives ${(model.probability * 100).toFixed(0)}% for ${model.label} from ${expectedGoals(context)?.matches || 5} scored matches a side; ${leg.odds.toFixed(2)} needs ${(implied * 100).toFixed(0)}%. One book cannot confirm that as value on its own.`;
    if (edge < -0.12) flags.push({ level: 'caution', text: sentence });
    else read = sentence;
  }

  return {
    ...base,
    analysed: true,
    side,
    model: model && Number.isFinite(model.probability) ? { label: model.label, probability: Number(model.probability.toFixed(4)), edge: leg.odds ? Number((model.probability * leg.odds - 1).toFixed(3)) : null } : null,
    matchedEvent: event.name,
    form: context?.form || null,
    meetings: meetings.slice(0, 3),
    corners: context?.corners || null,
    flags,
    alternative,
    read: flags.length ? flags[0].text : read,
  };
}

function legPayload(leg) {
  return {
    event: leg.event,
    league: leg.league,
    market: leg.market,
    selection: leg.selection,
    odds: leg.odds,
    matchedEvent: leg.matchedEvent || null,
    form: leg.form ? {
      home: { team: leg.form.home.team, sequence: leg.form.home.sequence },
      away: { team: leg.form.away.team, sequence: leg.form.away.sequence },
    } : null,
    headToHead: leg.meetings || null,
    corners: leg.corners ? { home: leg.corners.home.average, away: leg.corners.away.average } : null,
    model: leg.model ? `${leg.model.label}: ${(leg.model.probability * 100).toFixed(0)}% by the goals model` : null,
    flags: leg.flags.map((flag) => flag.text),
    alternative: leg.alternative,
  };
}

async function handleSlip(request, env) {
  if (!sameOrigin(request)) return json({ error: 'Cross-origin request rejected' }, 403);
  let body;
  try {
    body = await readBody(request);
  } catch (error) {
    return json({ error: String(error.message || 'Invalid body') }, 400);
  }

  const code = String(body.code || body.input || '').replace(/\s+/g, '').toUpperCase().slice(0, 24);
  if (!code) return json({ error: 'Paste a booking code' }, 400);
  if (!CODE_SHAPE.test(code)) return json({ error: 'That does not look like a booking code' }, 400);
  const sport = body.sport && LEAGUES[body.sport] ? body.sport : 'epl';

  let resolved;
  try {
    resolved = await resolveSportyCode(code);
  } catch (error) {
    return json({ kind: 'slip', code, resolved: false, message: String(error.message || 'Code lookup failed').slice(0, 200) }, 502);
  }

  if (!resolved.ok) {
    return json({
      kind: 'slip',
      code,
      resolved: false,
      book: null,
      message: `No open Nigerian reader returned ${code}: SportyBet said "${String(resolved.message || 'no selections').replace(/\.$/, '')}". Bet9ja, BetKing and GokaBet codes have no public reader, so paste the slip text into the audit instead.`,
    });
  }

  const legs = resolved.legs.slice(0, 40);
  const pool = (await Promise.all(
    FOOTBALL_LEAGUES.map((key) => loadEvents(env, key).catch(() => ({ events: [] }))),
  )).flatMap((row) => row.events || []);

  const analysed = [];
  for (const leg of legs.slice(0, 30)) {
    analysed.push(await enrichLeg(pool, leg));
  }
  const rest = legs.slice(30).map((leg) => ({
    ...leg,
    flags: [],
    analysed: false,
    read: 'Not analysed in depth — the slip has more legs than one pass can research.',
  }));
  const all = [...analysed, ...rest];

  const candidates = analysed
    .filter((leg) => leg.alternative && Number.isFinite(leg.alternative.fair))
    .sort((a, b) => b.alternative.fair - a.alternative.fair)
    .slice(0, 3)
    .map((leg) => ({ event: leg.matchedEvent, name: leg.alternative.name, price: leg.alternative.price, fair: leg.alternative.fair }));

  let ai = null;
  let aiError = null;
  if (env.OPENAI_API_KEY) {
    try {
      ai = readAiJson(await aiCall(
        env,
        CODE_SYSTEM,
        JSON.stringify({
          book: 'SportyBet',
          code,
          legs: legs.length,
          combined: resolved.combined,
          analysed: analysed.map(legPayload),
          notAnalysedCount: rest.length,
          strongestAlternatives: candidates,
        }, null, 2),
      ));
    } catch (error) {
      aiError = String(error.message || error).slice(0, 200);
    }
  }

  const avoid = analysed.filter((leg) => leg.flags.some((flag) => flag.level === 'avoid')).map((leg) => leg.event);
  const caution = analysed.filter((leg) => leg.flags.some((flag) => flag.level === 'caution')).map((leg) => leg.event);

  return json({
    kind: 'slip',
    code,
    book: 'SportyBet',
    resolved: true,
    combined: resolved.combined,
    stake: resolved.stake,
    potential: resolved.potential,
    legs: all,
    analysedCount: analysed.length,
    avoid,
    caution,
    best: candidates[0] || null,
    ai,
    aiError,
  });
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

async function logoIndex(key) {
  const cacheKey = `logos:${key}`;
  const cached = memoGet(cacheKey);
  if (cached) return cached;
  let teams = [];
  try {
    teams = (await espnTeamList(key)) || [];
  } catch { /* no logos */ }
  const index = teams
    .map((team) => ({
      keys: nameKeys(team.displayName),
      logo: team.logo || team.logos?.[0]?.href || null,
    }))
    .filter((row) => row.logo && row.keys.length);
  memoSet(cacheKey, index, 6 * 3600 * 1000);
  return index;
}

function logoFor(team, index) {
  if (!team || team.logo || !index.length) return team;
  const keys = nameKeys(team.name);
  let best = null;
  let bestScore = 0;
  for (const row of index) {
    let score = 0;
    for (const key of keys) if (row.keys.includes(key)) score += 2;
    if (score > bestScore) {
      bestScore = score;
      best = row.logo;
    }
  }
  if (bestScore >= 2) team.logo = best;
  return team;
}

async function attachLogos(events, leagueKey) {
  const index = await logoIndex(leagueKey).catch(() => []);
  for (const event of events) {
    logoFor(event.home, index);
    logoFor(event.away, index);
  }
  return events;
}

async function handleOdds(url, env) {
  const key = url.searchParams.get('sport') || 'epl';
  if (key !== 'all' && !LEAGUES[key]) return json({ error: `Unknown sport "${key}"` }, 400);

  if (key === 'all') {
    const cached = memoGet('feed:all');
    if (cached) return json(cached);
    try {
      const packs = await Promise.all(FOOTBALL_LEAGUES.map(async (leagueKey) => {
        try {
          const { events } = await loadEvents(env, leagueKey);
          return events
            .filter((event) => !event.completed)
            .map((event) => ({ ...event, leagueLabel: LEAGUES[leagueKey].label, league: leagueKey }));
        } catch {
          return [];
        }
      }));
      const seen = new Set();
      const merged = packs.flat().filter((event) => {
        const id = event.id || event.name;
        if (seen.has(id)) return false;
        seen.add(id);
        return true;
      });
      await Promise.all([...new Set(merged.map((event) => event.league))].map(async (leagueKey) => {
        await attachLogos(merged.filter((event) => event.league === leagueKey), leagueKey);
      }));
      merged.sort((a, b) => new Date(a.start || 0) - new Date(b.start || 0));
      const payload = {
        sport: 'all',
        source: 'mixed',
        multiBook: false,
        pricedEvents: merged.filter((event) => event.books.length && event.market).length,
        updated: new Date().toISOString(),
        events: merged.slice(0, 240),
      };
      memoSet('feed:all', payload, 3 * 60 * 1000);
      return json(payload);
    } catch (error) {
      return json({ error: 'Could not load the multi-league feed', detail: String(error.message || error) }, 502);
    }
  }

  try {
    const { events, source } = await loadEvents(env, key);
    const limit = Math.min(Number(url.searchParams.get('limit')) || 12, 24);
    const priced = events.filter((event) => event.books.length && event.market).length;
    const sorted = events
      .filter((event) => !event.completed)
      .sort((a, b) => new Date(a.start || 0) - new Date(b.start || 0))
      .slice(0, limit);
    await attachLogos(sorted, key);
    return json({
      sport: key,
      league: LEAGUES[key],
      source,
      multiBook: source === 'oddsapi',
      pricedEvents: priced,
      updated: new Date().toISOString(),
      events: sorted,
    });
  } catch (error) {
    return json({ error: 'Could not load odds feed', detail: String(error.message || error) }, 502);
  }
}

async function handleBuild(request, env) {
  if (!sameOrigin(request)) return json({ error: 'Cross-origin request rejected' }, 403);
  let body;
  try {
    body = await readBody(request);
  } catch (error) {
    return json({ error: String(error.message || 'Invalid body') }, 400);
  }

  const target = Number(body.target);
  const day = String(body.day || '').slice(0, 10);
  if (!(target >= 1.2 && target <= 5000)) {
    return json({ error: 'Give a target price between 1.20 and 5,000' }, 400);
  }

  const packs = await Promise.all(FOOTBALL_LEAGUES.map(async (key) => {
    try {
      const { events } = await loadEvents(env, key);
      return events
        .filter((event) => !event.completed && event.market && event.start)
        .map((event) => ({ ...event, leagueLabel: LEAGUES[key].label, league: key }));
    } catch {
      return [];
    }
  }));

  const pool = packs.flat().filter((event) => {
    if (!day) return true;
    return new Date(event.start).toISOString().slice(0, 10) === day;
  });
  if (!pool.length) return json({ error: 'No priced fixtures on that day across the tracked leagues' }, 404);

  const candidates = [];
  for (const event of pool) {
    const sides = event.hasDraw ? ['home', 'draw', 'away'] : ['home', 'away'];
    let bestSide = null;
    for (const side of sides) {
      const fair = event.market.consensus[side];
      if (!Number.isFinite(fair)) continue;
      if (!bestSide || fair > bestSide.fair) {
        bestSide = {
          side,
          fair,
          name: side === 'home' ? event.home.name : side === 'draw' ? 'Draw' : event.away.name,
          price: event.market.best[side]?.price ?? null,
        };
      }
    }
    if (!bestSide || !bestSide.price || bestSide.fair < 0.4) continue;
    candidates.push({
      event: event.name,
      eventId: event.id,
      league: event.leagueLabel,
      kickoff: event.start,
      pick: bestSide.name,
      side: bestSide.side,
      price: bestSide.price,
      fair: Number((bestSide.fair * 100).toFixed(1)),
      lineShop: event.market.lineShop,
    });
  }

  candidates.sort((a, b) => b.fair - a.fair);
  const picked = [];
  let combined = 1;
  for (const row of candidates) {
    if (combined >= target) break;
    picked.push(row);
    combined *= row.price;
  }

  return json({
    target,
    day: day || new Date().toISOString().slice(0, 10),
    combined: Number(combined.toFixed(2)),
    picks: picked,
    considered: candidates.length,
    note: 'Picks are the highest de-vigged probability outcome per fixture, taken safest-first until the target price is met. Single-book prices mean no positive edge; this is a research shortlist, not a guarantee.',
  });
}

async function handleTrim(request, env) {
  if (!sameOrigin(request)) return json({ error: 'Cross-origin request rejected' }, 403);
  let body;
  try {
    body = await readBody(request);
  } catch (error) {
    return json({ error: String(error.message || 'Invalid body') }, 400);
  }

  const code = String(body.code || '').replace(/\s+/g, '').toUpperCase().slice(0, 24);
  const target = Number(body.target);
  if (!code) return json({ error: 'Paste the code first' }, 400);
  if (!(target >= 1.2 && target <= 100000)) return json({ error: 'Give a target combined price between 1.20 and 100,000' }, 400);

  let resolved;
  try {
    resolved = await resolveSportyCode(code);
  } catch (error) {
    return json({ error: String(error.message || 'Code lookup failed').slice(0, 160) }, 502);
  }
  if (!resolved.ok) {
    return json({ error: `SportyBet could not open ${code}: ${String(resolved.message || 'no selections').replace(/\.$/, '')}` }, 400);
  }

  const legs = resolved.legs
    .filter((leg) => leg.odds && leg.odds > 1)
    .map((leg) => ({ ...leg, implied: 1 / leg.odds }))
    .sort((a, b) => b.implied - a.implied);

  const kept = [];
  let combined = 1;
  for (const leg of legs) {
    if (combined >= target) break;
    kept.push(leg);
    combined *= leg.odds;
  }

  const keptIds = new Set(kept.map((leg) => `${leg.eventId}|${leg.market}|${leg.selection}`));
  const dropped = legs.filter((leg) => !keptIds.has(`${leg.eventId}|${leg.market}|${leg.selection}`));
  const weakest = dropped.slice(0, 12).map((leg) => ({
    event: leg.event,
    selection: leg.selection,
    odds: leg.odds,
    implied: Number((leg.implied * 100).toFixed(0)),
  }));

  return json({
    code,
    target,
    combined: Number(combined.toFixed(2)),
    kept: kept.map((leg) => ({
      event: leg.event,
      market: leg.market,
      selection: leg.selection,
      odds: leg.odds,
      implied: Number((leg.implied * 100).toFixed(0)),
    })),
    dropped: dropped.length,
    avoid: weakest,
    note: 'Legs are kept safest-first by implied probability until the target is met. The app cannot mint a new booking code: rebuild these picks in the bookmaker, and check any pick swapped for a safer market yourself.',
  });
}

async function handleResearch(request, env) {
  if (!sameOrigin(request)) return json({ error: 'Cross-origin request rejected' }, 403);
  let body;
  try {
    body = await readBody(request);
  } catch (error) {
    return json({ error: String(error.message || 'Invalid body') }, 400);
  }

  const query = String(body.query || '').slice(0, 120);
  const eventId = body.eventId ? String(body.eventId) : null;
  let key = body.sport || 'epl';

  if (!LEAGUES[key]) {
    if (key !== 'all') return json({ error: `Unknown sport "${key}"` }, 400);
    const found = eventId ? await leagueForEvent(env, eventId) : null;
    if (!found) {
      return json({ error: 'Research needs a league or a fixture from the feed' }, 400);
    }
    key = found;
  }

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
  if (pathname === '/api/slip' && request.method === 'POST') return handleSlip(request, env);
  if (pathname === '/api/trim' && request.method === 'POST') return handleTrim(request, env);
  if (pathname === '/api/build' && request.method === 'POST') return handleBuild(request, env);

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
