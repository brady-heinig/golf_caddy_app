# ForeAI: An AI Golf Caddie

FastAPI backend (`backend/`) and Next.js frontend (`frontend/`).

---

## Why is this needed?

The average amateur golfer faces the challenge of making informed decisions about which club to use, where to aim, how to handle danger, and how to account for the playing conditions. These choices greatly impact performance but require knowledge, data, and quick analysis that are not readily available on the course.

ForeAI solves this problem by providing real-time, golf-intelligent shot advice. It combines accurate GPS location, individualized shot history, course maps, weather, and AI to produce pro-level insights on demand, including strategic shot plans, club recommendations, hazard warnings, and even text-to-speech summaries, all tailored to your specific situation on the course.

There are plenty of golf apps that claim to use AI to assist golfers on the course, but almost all golfers miss out on the added benefits that a caddie brings to the table. Many PGA Tour players attribute some of their success to their caddie, and this project is built so everyone can have access to similar insights.

This README walks you through setting up the necessary tools and accounts so you can run the app on your own.

---

## Prerequisites

| Need | Why |
|------|-----|
| Git | Fork the repo, clone your fork. |
| Python 3.11+ | FastAPI backend (`backend/`). |
| Node.js 20+, npm | Next.js frontend (`frontend/`). |
| [Supabase](https://supabase.com) | Hosted Postgres → `DATABASE_URL`. |
| [Anthropic](https://console.anthropic.com) | Claude for caddie advice. |
| [ElevenLabs](https://elevenlabs.io) | Text-to-speech for “Listen (ElevenLabs)” → `ELEVENLABS_API_KEY` + a voice ID. |
| [Render](https://render.com) | Host the Docker API from `backend/Dockerfile`. |
| [Vercel](https://vercel.com) | Host the Next.js app from `frontend/`. |

---

## Set up required accounts

Before you start, set up accounts for the services you will use.

**Supabase (database)**

- Go to [Supabase](https://supabase.com) and create a free account.
- Click **New project**, and set a name, password, and region.
- Once your project is ready, go to **Project Settings → Database** and copy your connection string (Database URI). You will use this as `DATABASE_URL` in the app backend.

**Anthropic (AI — Claude API)**

- Visit [Anthropic Console](https://console.anthropic.com) and sign up.
- Go to **API Keys** and create a new API key. Use it as `ANTHROPIC_API_KEY` in your backend environment.

**ElevenLabs (text-to-speech)**

- Create an account at [ElevenLabs](https://elevenlabs.io).
- Go to **Profile → API Keys** and create an API key (`ELEVENLABS_API_KEY`).
- Go to **Voices**, pick or create a voice, and copy its **Voice ID** (`ELEVENLABS_VOICE_ID`).
- These enable the “Listen” (text-to-speech) feature in the caddie flow.

**Render (backend hosting)**

- Go to [Render](https://render.com) and sign up.
- Deploy the backend using the repo `Dockerfile`, connecting your GitHub fork.
- Add environment variables (`DATABASE_URL`, `ANTHROPIC_API_KEY`, etc.) in the service settings.

**Vercel (frontend hosting)**

- Go to [Vercel](https://vercel.com) and create an account.
- Link your GitHub fork when prompted.
- Deploy the frontend from the `frontend/` directory and set environment variables (see below).

---

## Fork and clone the repo

On GitHub, fork the repository, then clone your fork.

```bash
git clone https://github.com/<YOUR_USERNAME>/golf_caddy_app.git
cd golf_caddy_app
```

---

## Local development

### Backend (FastAPI)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# required (Supabase Postgres)
export DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/postgres"

# required for caddie advice / chat
export ANTHROPIC_API_KEY="..."

export CORS_ALLOW_ORIGINS="http://localhost:3000"

uvicorn app.main:app --reload --port 8000
```

On first API start, migrations run and create the tables the app uses.

### Frontend (Next.js)

```bash
cd frontend
npm install
cp .env.example .env.local
# set NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm run dev
```

Open `http://localhost:3000`.

Authentication has been removed; the app runs as a single default user in the database.

---

## Production: Supabase + Render + Vercel + ElevenLabs

### Supabase

- Dashboard → **New project** → note the database password.
- **Project Settings → Database** → copy the URI (connection string), e.g. `postgresql://postgres...`
- Use that as `DATABASE_URL` in your backend environment (local shell or Render → Environment).

### Render (backend API)

1. [Render Dashboard](https://dashboard.render.com) → **New +** → **Web Service**.
2. Connect your GitHub repo (your fork).
3. Configure:
   - **Root directory:** `backend`
   - **Dockerfile path:** `Dockerfile` (relative to root directory, i.e. `backend/Dockerfile` in the repo).
4. Under **Environment**, add secrets:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Supabase Postgres URI |
| `ANTHROPIC_API_KEY` | Claude for `/api/caddie/advice` and related routes |
| `CORS_ALLOW_ORIGINS` | Your live site, e.g. `https://your-app.vercel.app` (comma-separated if several) |
| `ELEVENLABS_API_KEY` | ElevenLabs TTS for `/api/caddie/tts` |
| `ELEVENLABS_VOICE_ID` | Default voice for TTS (Voices page in ElevenLabs) |

5. Deploy → copy the public URL (e.g. `https://your-api.onrender.com`).
6. Verify: `https://your-api.onrender.com/api/health`

### ElevenLabs

- Sign up at [elevenlabs.io](https://elevenlabs.io) → create an API key.
- **Voices** → pick a voice → copy **Voice ID** into `ELEVENLABS_VOICE_ID` on Render (and locally if testing TTS).
- Without these, advice still works; only “Listen (ElevenLabs)” returns an error until keys are set.

### Vercel (frontend)

1. [Vercel](https://vercel.com) → **Add New… → Project** → import the same repo.
2. **Root Directory:** `frontend`
3. **Environment variable:** `NEXT_PUBLIC_API_BASE_URL` = `https://your-api.onrender.com` (no trailing slash)
4. Deploy → open `https://your-project.vercel.app`
5. If the browser shows CORS errors on `/api/...`, ensure `CORS_ALLOW_ORIGINS` on Render includes `https://your-project.vercel.app` exactly (scheme + host).

Use the **transaction / pooled** Postgres connection string if your backend host is serverless.

---

## How to use the app

### 1. Landing page

When you first open the app, you will see the landing page with options such as **Play**, **Settings**, and **Past Rounds**.

**a. Play / round mode**

- Tap **Play** to begin a golf round.
- Choose **Live round** or **Simulated round**:
  - **Live:** Uses your device GPS so your position updates on the map. Grant location access when prompted.
  - **Sim:** Drag the player on the map to simulate shots without being on the course.

**b. Settings**

- Enter typical carry distances for each club so recommendations match your bag.
- Set shot-shape preferences (fade, draw, straight, etc.) where supported.

**c. Past rounds**

- Open **Rounds** to continue an active round or review finished rounds. **Continue** opens the caddie on the map when the round has a saved mode.

### 2. Courses and holes

- After starting a round, you land on the course view.
- Use the hole controls to change holes.
- You will see adjusted distance (wind, elevation, position) and wind when data is available.

### 3. Interactive map

- **Blue dot:** Your position (live GPS or sim drag).
- **White marker:** Suggested landing / aim point; you can drag it to change the plan.
- **Wind:** The app combines wind speed and direction with your shot line to adjust plays-like yardage (headwind adds effective distance, tailwind reduces it; crosswind has a smaller along-line effect). Club suggestions follow the adjusted number.
- **Hit green %:** Benchmark-style green success from the distance context (see app for exact labeling).
- **Distance / plays-like:** Straight yardage plus elevation and wind adjustments where available.

### 4. Talk with the caddie (AI advice)

- Use **Talk with caddie** (or the advice flow in the UI) for situation-specific guidance using your position, bag, wind, and hole data.
- **Voice / TTS:** Optional ElevenLabs playback when keys are configured.
- **Ask / follow-up:** Use the chat or voice follow-up where the UI exposes it to clarify strategy, misses, or club choice.

Example questions:

- “Should I lay up short of the hazard or carry it?”
- “What is the safest miss here?”
- “Why this club instead of one longer?”

### 5. Scorecard during play

- Open the **scorecard** from the in-round controls.
- Tap a hole to edit strokes; changes save when the round is linked to the server.

**Typical workflow**

1. Open the app → **Play** → Live or Sim.
2. In live mode, allow location for accurate yardages.
3. Configure **Settings** (bag / handicap) for personalized advice.
4. Use the map and draggable target to match your plan.
5. Use caddie advice when you want a recommendation.
6. Log scores on the scorecard as you play.

---

## Limitations

- **AI context:** Advice is based on modeled data and typical patterns; rare lies or unmapped features may not be perfect.
- **Weather / elevation:** Uses available APIs; conditions on the ground can differ or lag.
- **Connectivity:** Live features need a working internet connection.
- **Course coverage:** Course list and map data depend on what is bundled in the deployment; expanding courses requires additional data work.
- **Green contours:** Detailed green slopes are not included (commercial data cost).

---

## Try it and demo

- **Try ForeAI:** replace with your deployed URL, e.g. `https://your-project.vercel.app`
- **Demo video:** replace with your walkthrough link, e.g. `https://www.youtube.com/watch?v=YOUR_DEMO_VIDEO_ID`

---

*This README was expanded from `App_Tutorial.ipynb` in the same repository.*
