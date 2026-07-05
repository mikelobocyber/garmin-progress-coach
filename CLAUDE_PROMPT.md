# Prompt for Claude to polish this repo

Paste this into Claude after uploading the repo:

```text
You are a senior full-stack engineer and product designer. Please review and polish this Garmin Progress Coach repo.

Goal:
Make this app feel clean, simple, professional, and extremely easy for a beginner to set up. The app is a local-first Garmin training dashboard and general fitness coaching website/PWA. It should help with broad improvement — running, weightlifting, cardio, walking/hiking, mobility, recovery flags, body composition notes, and optional ACFT-style benchmarks. It should run with one Python backend and no Node/React build step.

Hard constraints:
- Do not add a complex stack unless absolutely necessary.
- Preserve the easy setup: Python virtualenv + pip install + uvicorn.
- Keep the app local-first and privacy-conscious.
- Keep OpenAI optional. The app must still work without an API key.
- Keep the web Settings flow simple: a user should be able to paste an OpenAI API key and an optional server API token directly in the browser.
- Do not store OpenAI keys on the server unless the user deliberately puts one in .env.
- Do not send raw GPS/heart-rate samples to OpenAI by default; use summaries.
- Do not assume every user is training for ACFT. ACFT should be optional.
- Do not claim official ACFT scoring unless official scoring tables are implemented and cited.
- Keep the UI mobile-friendly and PWA-friendly.
- Avoid over-engineering with Kubernetes, microservices, OAuth, or Docker-only setup.

What I want you to improve:
1. Review the code for bugs, bad assumptions, security issues, and confusing naming.
2. Verify there are no sensitive files, secrets, personal data, generated caches, or local databases in the repo.
3. Improve the README so it looks like a public GitHub project page, not internal developer notes.
4. Improve the UI/UX while keeping it plain HTML/CSS/JS served by FastAPI.
5. Make the Garmin CSV parser more robust for real Garmin Connect exports.
6. Make summaries and coach advice account for non-running workouts like strength training, cycling, elliptical/cardio, walking/hiking, swimming, and mobility.
7. Add clear error states for bad CSV files and empty dashboards.
8. Add small tests for parsing, summaries, web settings/API-token behavior if practical, and API routes.
9. Add comments only where they clarify something non-obvious.
10. Keep the code readable enough for a portfolio project.
11. Suggest exactly what should be phase 2, but do not build phase 2 unless it is small.
12. Update docs/custom_gpt_action.md so connecting this to a Custom GPT is clear.

Please return:
- a concise summary of what you changed
- the improved files
- any commands I need to run
- any remaining TODOs
```
