# Sport Analyst

Football-first market research on a Cloudflare Worker. Live 1X2 prices come
from SportyBet's Nigerian feed, probabilities are de-vigged in the worker, and
each fixture is set against current form and head-to-head history. A language
model explains the numbers; it never produces them.

SportyBet is the only Nigerian book publishing an open price feed, so fixtures
are labelled **single book · no line-shop** and no edge is shown until a second
bookmaker price exists. The report says which research inputs are missing
(referee appointment, line-ups, manager records) instead of inventing them.

## What it does

| Feature | Source of truth |
| --- | --- |
| Football feed (7 leagues) | SportyBet NG tournament feed (`sportybet.com/api/ng`), keyless |
| Other sports (NBA, NFL, MLB, NHL) | ESPN scoreboard, or The Odds API when `ODDS_API_KEY` is set |
| Fair probability | `p = (1/price) / Σ(1/price)` per book, averaged across books |
| Best price / edge | Only shown when two or more books price the fixture; a single-book market shows no edge |
| Match form | ESPN team feeds: last five results and W/D/L sequence per side |
| Head-to-head | This season plus last season's completed meetings |
| Ask desk | Plain-English Q&A grounded in the same worker-computed numbers |
| Arbitrage flag | `Σ(1/best price) < 1` |
| Slip audit | Combined odds + per-leg edge against the live feed, with a trim suggestion |
| Book converter | Same slip at equivalent decimal odds for Bet9ja/BetKing/GokaBet/1xBet (no booking code) |
| EV + Kelly | Browser maths from your own probability estimate |
| Research report | Worker-computed market table + optional LLM narration |
| Bet log | `localStorage` in your browser; stake, ROI and win rate over settled bets |

Leagues: Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions
League, Europa League, plus NBA, NFL, MLB and NHL as secondary sports.
Platforms listed in the UI: SportyBet (priced), Bet9ja, BetKing, GokaBet, 1xBet
(conversion targets only).

## Run locally

```bash
npm install
cp .env.example .env      # optional: add keys
npm run dev               # http://127.0.0.1:8787
```

On Windows PowerShell, `npm` may be blocked by the execution policy
(`npm.ps1 cannot be loaded`). Use `npm.cmd run dev` instead, or call Node
directly for key entry: `node scripts/set-key.mjs`.

No key is required to run. Without `OPENAI_API_KEY` the report still returns the
full market table and the UI marks the AI panel as disabled. Without
`ODDS_API_KEY` the worker uses keyless ESPN prices, which cover fewer leagues
and usually expose a single bookmaker (so no cross-book edge).

### Keys

Put keys in `.env` (git-ignored). Do **not** create `.dev.vars` — its presence
stops Wrangler from reading `.env`.

Providers are chosen with one pair of variables, so no code changes are needed:

| Provider | `AI_BASE_URL` | `AI_MODEL` |
| --- | --- | --- |
| OpenLLM gateway (default) | `https://www.openllm.sh/v1` | `plus` |
| Z.ai | `https://api.z.ai/api/paas/v4` | `glm-4-flash` |
| Freebuff paid API (default) | `https://freebuff.com/api/v1/paid` | `gpt-4o-mini` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| OpenRouter | `https://openrouter.ai/api/v1` | `openai/gpt-4o-mini` |

- `OPENAI_API_KEY` — the bearer token for whichever provider above you pick.
  The variable keeps its name so the worker code stays provider-neutral.
- `ODDS_API_KEY` — enables multi-bookmaker `h2h` prices from The Odds API v4
  (`/v4/sports/{key}/odds?markets=h2h&oddsFormat=decimal`). `ODDS_REGIONS`
  defaults to `uk,eu`.

To avoid editing the file by hand, run `npm run set-key`: it prompts with hidden
input, writes `OPENAI_API_KEY` into `.env`, and fills the provider defaults.

To check the configured provider before restarting the worker, run
`npm run check-ai`. It prints the endpoint and model (never the key), lists the
models your key can actually call, sends one tiny completion, and exits non-zero
with a specific reason when the key is rejected or the model is unavailable.
On PowerShell use `npm.cmd run set-key` or `node scripts/set-key.mjs`.

**Where the OpenLLM key comes from:** create an `sk-llm-…` key in the OpenLLM
dashboard (Devices & keys). Send **only the key itself**: the dashboard's copy
command may append a device trust anchor after a second dot, and the gateway
rejects the whole string with `Invalid API key: remove everything after the
key`. Model ids come from `GET /v1/models`; `ultra`, `plus` and `lite` are
fallback chains that survive a provider outage, and direct ids such as
`openllm/qwen3.7-plus` pin one model. The hosted gateway needs no local install —
the `openllm` daemon is for serving your own subscriptions/local models and has
no Windows build, so the API works without it.

**Where a Z.ai key comes from:** register at <https://z.ai/model-api>, then create
a **Standard API key** on the [API keys page](https://z.ai/manage-apikey/apikey-list).
GLM Coding Plan keys are a separate product and are rejected by the standard
`api/paas/v4` endpoint. Keys there look like `<id>.<secret>` — no `sk-` prefix.

If the provider rejects the request, the report still returns with `ai: null`
and `aiError` describing why — the market maths never depends on the model.

For production, keep these as Worker secrets (`wrangler secret put ...` or the
host's secret store), never in client code.

## API

```
GET  /api/health                  capabilities: AI on/off, odds provider, leagues
GET  /api/odds?sport=epl          upcoming events, books, consensus, edges, arb
POST /api/research                {sport, query} or {sport, eventId}
POST /api/convert                 {text} — one leg per line, odds at the end
```

The research response separates `event.market` (computed) from `ai`
(narration) so a client can always show the maths, even when the model is off
or the upstream call fails (`ai: null`, `aiError` set).

### Why the AI cannot fudge numbers

`aiNarrate()` sends the model a `DATA` block containing the already-computed
prices, vig-free probabilities, edges and margin, and instructs it to quote
them exactly, refuse to invent injuries/lineups, and list `dataGaps` instead of
guessing. The response schema is `headline`, `lean`, `confidence`, `reasoning`,
`risks`, `dataGaps` — there is no field in which it could return a probability
or a price. Parsing is validated and retried once; failures degrade to a null
narrative rather than blocking the report.

## Deploy

```bash
npx wrangler deploy
```

Assets are served from `./public` through the `ASSETS` binding; the same
handler answers `/api/*`. `deploy.json` is provided for hosts that take a
deployment manifest.

## Boundaries

- Not a sportsbook, tipster service, or betting advice. No bets are placed.
- Booking-code conversion needs each bookmaker's partner/affiliate API. This app
  does not mint codes; it rebuilds a pasted slip at equivalent odds and says so.
- Fair probability is the market's own opinion with the margin removed. It is
  not a prediction, and a positive edge can still lose. 18+.
