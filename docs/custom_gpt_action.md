# Connect this app to a Custom GPT

A Custom GPT Action lets ChatGPT call your Garmin AI Coach API before answering training questions. The app already publishes the OpenAPI schema the Action needs.

The app is now general fitness/progress first. ACFT is optional. The GPT should not assume every question is about the ACFT unless the user asks about it.

## What you need first

A Custom GPT cannot reach `http://localhost:8000` because OpenAI's servers make the API calls. Your app must be reachable from the internet. Two sane options:

- **A tunnel for testing:** ngrok or Cloudflare Tunnel. Example with ngrok:

  ```bash
  ./start.sh            # terminal 1
  ngrok http 8000       # terminal 2 → gives you https://something.ngrok.app
  ```

- **A small private deployment** on a VPS or PaaS you control.

**Before exposing the app, set a token.** In `.env`:

```bash
APP_SECRET_TOKEN=generate-a-long-random-string
```

Restart the app. Every API request now requires `Authorization: Bearer <your token>`. Without this, anyone with the URL can read your training data and write to your database.

## Set up the Action step by step

1. Start the app and your tunnel. Note your public URL, such as `https://something.ngrok.app`.
2. Get the schema: open `https://your-public-url/openapi.json` in a browser and copy the JSON.
3. In ChatGPT: **Explore GPTs → Create → Configure → Create new action**.
4. Paste the schema into the **Schema** box.
5. In the pasted schema, add your public URL so the Action knows where to call. FastAPI does not include this by default. Add this top-level key:

   ```json
   "servers": [{ "url": "https://your-public-url" }]
   ```

6. Under **Authentication**, choose **API Key**:
   - Auth Type: **Bearer**
   - API Key: the value of your `APP_SECRET_TOKEN`
7. Save, then use the test panel to call `GET /api/summary/latest`. You should see your weekly summary JSON.

Tunnel URLs change when you restart ngrok on the free tier, so update the `servers` URL when that happens.

## Suggested GPT instructions

```text
You are a private Garmin training coach for general fitness improvement.

When the user asks about training, recovery, running, workouts, progress,
readiness, or next-week planning, call the Garmin AI Coach API before answering:
- GET /api/summary/latest for the weekly picture
- GET /api/training/projection for the current training projection
- GET /api/runs/recent for individual runs when details matter

Treat ACFT as optional. Only use ACFT framing when the user asks about ACFT or
when they explicitly logged ACFT-style fields and want that analysis.

Focus on:
- consistency
- running improvement
- recovery and injury risk
- realistic weekly planning
- general fitness progress
- optional ACFT preparation when relevant

Rules:
- Do not diagnose medical conditions.
- The projection is unofficial; never present it as an official ACFT score.
- Prioritize trends over single readings; do not overreact to one bad day.
- When recovery looks poor, recommend easier training, not more.
- Give direct, practical advice.
```

## Which endpoints the GPT should use

| Endpoint | Purpose |
| --- | --- |
| `GET /api/summary/latest` | Weekly mileage, pace, HR, recovery flags |
| `GET /api/training/projection` | General 2-mile/training status + recommendation |
| `GET /api/runs/recent` | Individual recent runs |
| `POST /api/coach/ask` | Server-side coach answer using your OpenAI key if set |

Read-only endpoints are usually enough; the GPT can reason on top of the summary data.

## Troubleshooting

- **401/403 from the Action:** the bearer token in the GPT's auth settings does not match `APP_SECRET_TOKEN`, or the app was not restarted after setting it.
- **Could not find server in the Action test panel:** the `servers` key is missing from the pasted schema, or your tunnel URL changed.
- **Empty summary:** upload activities on the dashboard first; the GPT only reads what you have imported.
