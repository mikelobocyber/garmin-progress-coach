# Garmin AI Coach

A local-first Garmin training dashboard and general fitness coach. It runs as one Python FastAPI app with plain HTML/CSS/JS, SQLite storage, and no Node, React build, Docker, or cloud account required.

Use it to upload Garmin Connect activity CSVs, track running and recovery trends, log manual progress that Garmin may not capture, and ask for simple coaching. It works for general improvement first; ACFT-style tracking is optional.

Good use cases:

- Improve running consistency and pace
- Build a simple weekly training rhythm
- Watch recovery flags from recent runs
- Track body weight, push-ups, plank, deadlift, or notes
- Keep optional ACFT-style benchmarks like SDC/agility and 2-mile time

> Any 2-mile/ACFT projection is an unofficial training estimate, not an official Army score calculator.

## Quick start (about 2 minutes)

You need Python 3.10+ installed. That's it.

**macOS / Linux**

```bash
./start.sh
```

**Windows**

```bat
start.bat
```

Then open **http://localhost:8000** and upload `sample-data/garmin_activities_sample.csv` to see the dashboard fill in.

The script creates a virtual environment, installs dependencies, creates `.env`, and starts the server. Run it again any time — it skips work it has already done.

<details>
<summary>Prefer manual setup?</summary>

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
uvicorn app.main:app --reload
```

Then open http://localhost:8000.
</details>

## Get your data out of Garmin

1. Go to Garmin Connect → **Activities** → **All Activities**.
2. Scroll to load the activities you want, then click **Export CSV**.
3. Upload that file on the dashboard.

The parser handles common export quirks: comma or semicolon delimiters, `--` for missing values, European decimal commas, pace in min/mi or min/km, and duplicate rows across multiple exports. Re-uploading the same file is safe — duplicates are skipped.

## Use it from your phone

By default the app only listens on your computer (`127.0.0.1`) for privacy. To open it to devices on your Wi-Fi:

```bash
./start.sh --lan        # Windows: start.bat --lan
```

Find your computer's local IP, then open `http://YOUR_LOCAL_IP:8000` on your phone. You can also use **Add to Home Screen** because the app works as a PWA.

## Optional: OpenAI coaching

The Coach panel works out of the box with a built-in rule-based fallback. For richer answers, edit `.env`:

```bash
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4.1-mini
```

Restart the app.

**Privacy note:** only summarized training data is sent to OpenAI: weekly totals, pace summaries, recovery flags, and your manual progress entries including notes. The app does not send raw GPS tracks or per-second heart-rate samples by default. With no key set, nothing leaves your machine.

## Optional: protect the API with a token

Only needed if you expose the app beyond your own machine/LAN, such as through a tunnel for a Custom GPT. Set this in `.env`:

```bash
APP_SECRET_TOKEN=make-a-long-random-token
```

API requests must then include `Authorization: Bearer <token>`. Note: the web dashboard itself does not send this header, so keep the token empty for normal local use.

## API endpoints

```text
GET  /api/summary/latest         weekly summary + 2-mile benchmark
GET  /api/activities             imported activities
GET  /api/runs/recent            runs only
GET  /api/training/projection    general training projection + flags
POST /api/upload/garmin-csv      import a Garmin CSV
POST /api/progress/entry         log manual progress numbers
POST /api/progress/settings      set your 2-mile goal
POST /api/coach/ask              ask the coach a question
GET  /openapi.json               schema for Custom GPT Actions
```

Legacy ACFT endpoints are still available for compatibility:

```text
GET  /api/acft/projection
POST /api/acft/entry
POST /api/acft/settings
```

Interactive docs are at http://localhost:8000/docs.

## Run the tests

```bash
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pytest
```

Tests cover CSV parser edge cases, summary/projection logic, and API routes using a throwaway database. Your local data is never touched.

## Sensitive files check

This repo is meant to be safe to publish. It includes `.env.example`, but it should not include real secrets or personal Garmin data.

Before pushing to GitHub, this is a good quick check:

```bash
find . -type f | grep -Ei '(\.env$|\.sqlite3$|\.db$|\.fit$|\.tcx$|\.gpx$|\.log$|\.pyc$|__pycache__)'
grep -RInE 'sk-[A-Za-z0-9_-]{20,}|OPENAI_API_KEY=.+|APP_SECRET_TOKEN=.+|BEGIN (RSA|OPENSSH|PRIVATE)' . --exclude-dir=.git
```

Expected result: no real `.env`, no database, no raw Garmin files, no Python cache files, and no populated API keys/tokens.

## Project structure

```text
garmin-ai-coach/
  app/
    main.py            FastAPI app + static file serving
    database.py        SQLite schema and queries
    security.py        optional bearer-token check
    routes/            upload, summary, progress/ACFT, coach endpoints
    services/          Garmin CSV parser, summary builder
    static/            plain HTML/CSS/JS dashboard (PWA)
  sample-data/         fake sample CSV to try immediately
  tests/               pytest suite
  docs/                Custom GPT Action guide
```

## Privacy

Data lives in a local SQLite file at `data/garmin_ai_coach.sqlite3`, which is gitignored. Nothing leaves your machine unless you add an OpenAI key or deploy/expose the app yourself.

## Phase 2 ideas

1. **FIT/TCX/GPX import** — the biggest unlock; CSV exports lack per-activity detail.
2. **A simple pace-trend chart** — one dependency-free SVG line chart.
3. **Goal modes** — general fitness, running improvement, weight loss, ACFT, or custom.
4. **Sleep / stress / Body Battery import** if Garmin wellness exports prove stable.
5. **Official ACFT scoring tables** only with the published tables implemented and cited.
6. **Weekly summary export** as markdown or PDF.

## Custom GPT Action

See [docs/custom_gpt_action.md](docs/custom_gpt_action.md) for connecting this app to a Custom GPT.
