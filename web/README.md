# Sport Analyst

**Football research, not tips.**

Sport Analyst is a football-first betting research workspace for Nigerian punters.
It reads live prices from SportyBet, de-vigs them into fair probabilities in the
worker, and sets each fixture against current form, head-to-head history and
corners per game. A language model narrates the numbers; it never produces them.

The product rule is simple: **every number shown is computed from a feed, and
every gap is named out loud.** When the data cannot support a claim, the app says
so instead of filling the space with confident-sounding text.

---

## What it does

| Feature | How it works |
| --- | --- |
| Multi-league feed | 14 competitions merged into one board, grouped by day |
| Day switching | Today, tomorrow or any date, filtered in the browser |
| Favourite leagues | Star a league and it pins to the front of the filters |
| Club badges | Team logos from ESPN's team feed, matched to SportyBet names |
| De-vigged probability | `p = (1/price) / Σ(1/price)`, averaged across books |
| Single-book honesty | Fixtures with one price are labelled *no line-shop* and show no edge |
| Research report | Price, form, head-to-head, corners per game, plus explicit gaps |
| Booking code reader | Opens SportyBet codes into legs: fixture, market, pick, price |
| Leg research | Each pick checked against price, form, H2H and corners, with reasons |
| Avoid list | Legs the data argues against, named rather than buried |
| Trim to a target | Keeps the safest legs until a combined price is reached, lists the cuts |
| Split by kickoff | Groups a slip by the hour each match starts |
| Build a slip | "Give me 10 odds" → research-led picks across the day's fixtures |
| Ask desk | Plain-English questions answered from the same computed numbers |
| Slip lab | Audit, convert at equivalent odds, EV and Kelly stake sizing |
| My record | Local bet log with settled ROI and win rate |

---

## Where the data comes from

- **Prices:** SportyBet Nigeria's keyless facts-centre feed (`sportybet.com/api/ng`).
- **Booking codes:** SportyBet's own slip endpoint (`/orders/share/<code>`).
- **Form, head-to-head, corners:** ESPN team feeds and match summaries.
- **Narration:** an OpenAI-compatible gateway, configured with `AI_BASE_URL`, `AI_MODEL` and `OPENAI_API_KEY`.

The model receives a DATA block and is instructed to quote it exactly. It has no
permission to invent a referee, an injury, a line-up or a price.

---

## Honest limits

- **One priced book.** SportyBet is the only Nigerian book with an open price
  feed, so most fixtures are single-book. No cross-book edge is claimed.
- **Bet9ja, BetKing and GokaBet codes cannot be opened.** None publishes a public
  code reader; the app names the book as unsupported instead of guessing.
- **No code minting yet.** The app can read, trim and split a slip, but creating a
  native booking code requires a bookmaker partner integration.
- **Referee and squad news are not published pre-match** by these feeds. They are
  listed as gaps, and bookings markets are not leaned on without a referee.
- **Research depth.** Deep research covers up to 30 legs per slip; longer slips
  say how many legs were left unchecked.
- **Fixtures outside the tracked leagues** get a book-price check only, not fair
  probability or form.

---

## Run it locally

```bash
npm install
cp .env.example .env      # add AI keys if you want narration
npm run dev               # http://127.0.0.1:8787
```

No key is required to browse prices. Without `OPENAI_API_KEY` the market tables
still work and the AI panels report that narration is disabled.

Deploy with Wrangler (`npm run deploy`) or the Freebuff Sites deployer. Static
assets live in `public/`; all routes and adapters live in `worker.js`.

---

## Repository layout

```
worker.js              all routes, feed adapters, maths, prompts
public/index.html      the app shell
public/style.css       red/black theme, motion, layout
public/app.js          client logic: feed, days, research, slip, build
public/img/logo.svg    the shield mark
scripts/               AI key checks and setup helpers
web/                   the Worker build published from this repo
```

The original Reflex/Python research app remains in `app/`, `db_migrations/` and
`scripts/` at the repository root.

---

## Roadmap

- Native code generation once a bookmaker partner API is available.
- Wider league coverage beyond the 14 tracked competitions.
- Referee and confirmed line-up feeds for bookings research.
- Multi-book pricing so real cross-book edges can be measured.

---

18+. Research is not betting advice and never guarantees an outcome. Stake only
what you can afford to lose.
