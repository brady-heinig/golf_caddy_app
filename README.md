# ForeAi: App Tutorial

---

## Why is this Needed?

The average amateur golfer faces the challenge of making informed decisions about which club to use, where to aim, how to handle danger, and how to account for the playing conditions. These choices greatly impact performance but require knowledge, data, and quick analysis that aren’t readily available on the course.

ForeAi solves this problem by providing real-time, golf-intelligent shot advice. It combines accurate GPS location, individualized shot history, course maps, weather, and AI to produce pro-level insights on demand, including strategic shot plans, club recommendations, hazard warnings, and even text-to-speech summaries, all tailored to your specific situation on the course.

There are plenty of golf apps that claim to use AI to assist golfers on the course, but almost all golfers miss out on the added benefits that a caddie brings to the table. Many PGA tour players attribute some of their success to their caddie, and I believe everyone should have access to these insights.

This tutorial will walk you through setting up the necessary tools and accounts, so you can run the app on your own!

## Prerequisites

| Need | Why |
|------|-----|
|  Git  | Fork the repo, clone your fork. |
|  Python 3.11+  | FastAPI backend (backend/). |
|  Node.js 20+ ,  npm  | Next.js frontend (frontend/). |
| [ Supabase ](https://supabase.com) | Hosted  Postgres  → DATABASE_URL. |
| [ Anthropic ](https://console.anthropic.com) |  Claude  for “Talk with caddie”. |
| [ ElevenLabs ](https://elevenlabs.io) |  Text-to-speech  for “Listen (ElevenLabs)” → ELEVENLABS_API_KEY + a  Voice ID . |
| [ Render ](https://render.com) | Host the  Docker  API from backend/Dockerfile. |
| [ Vercel ](https://vercel.com) | Host the  Next.js  app from frontend/. |

---

## Set Up Required Accounts

Before you start, you'll need to set up accounts for several key services. Here's a quick walkthrough:

**Supabase (Database)**
- Go to [Supabase](https://supabase.com) and create a free account.
- Click **New project**, and set a name, password, and region.
- Once your project is ready, go to **Project Settings → Database** and copy your connection string (Database URI). You'll use this as DATABASE_URL in the app's backend.

**Anthropic (AI - Claude API)**
- Visit [Anthropic Console](https://console.anthropic.com), sign up for an account.
- After registering, go to **API Keys** in your account settings.
- Create a new API key and save it. You'll use this as the ANTHROPIC_API_KEY in your backend environment.

**ElevenLabs (Text-to-Speech)**
- Create a free account at [ElevenLabs](https://elevenlabs.io).
- Go to **Profile → API Keys** and create an API key (ELEVENLABS_API_KEY).
- Go to **Voices** and pick or create a voice; copy its **Voice ID** (ELEVENLABS_VOICE_ID).
- These enable the "Listen" (text-to-speech) feature in the caddie modal.

**Render (Backend Hosting)**
- Go to [Render](https://render.com) and sign up.
- You can deploy the backend using the repo's Dockerfile, connecting your GitHub fork.
- When setting up the service, add your environment variables (DATABASE_URL, ANTHROPIC_API_KEY, etc.).

**Vercel (Frontend Hosting)**
- Go to [Vercel](https://vercel.com) and create an account.
- Link your GitHub fork when prompted.
- Deploy the frontend from the frontend/ directory, and add any necessary environment variables (see project README for details).

## Fork and clone the repo

On GitHub, fork the repository, then clone your fork.

git clone https://github.com/<YOUR_USERNAME>/golf_caddy_app.git
cd golf_caddy_app
      
---

## Production: Supabase + Render + Vercel + ElevenLabs

### Supabase

Once a Supabase account has been created, follow these steps:
- Dashboard → New project → note the database password.  
- Project Settings → Database → copy the URI (connection string), e.g.: postgresql://postgres... 
- Use that as DATABASE_URL in your backend environment (local shell or Render → Environment).

On first API start, migrations run and create the tables the app uses.

### Render (backend API)
1. [Render Dashboard](https://dashboard.render.com) →  New +  →  Web Service .  
2. Connect your GitHub repo (your fork).  
3. Configure:
   - Root directory: backend. 
   - Dockerfile path: Dockerfile (if root is backend, this is backend/Dockerfile in the repo).  
4. Under Environment, add secrets:

| Variable | Purpose |
|----------|--------|
| DATABASE_URL | Supabase Postgres URI |
| ANTHROPIC_API_KEY | Claude for   /api/caddie/advice   |
| CORS_ALLOW_ORIGINS | Your live site, e.g.   https://your-app.vercel.app   (comma-separated if several) |
| ELEVENLABS_API_KEY | ElevenLabs TTS for   /api/caddie/tts   |
| ELEVENLABS_VOICE_ID | Default voice for TTS (Voices page in ElevenLabs) |

5. Deploy → copy the public URL (e.g.   https://your-api.onrender.com  ).  
6. Verify:   https://your-api.onrender.com/api/health  

### ElevenLabs
- Sign up at [ elevenlabs.io ](https://elevenlabs.io) → create an  API key .  
-  Voices  → pick a voice → copy  Voice ID  into    ELEVENLABS_VOICE_ID    on  Render  (and locally if testing TTS).  
- Without these,  advice still works ; only  Listen (ElevenLabs)  returns an error until keys are set.

### Vercel (frontend)
1. [ Vercel ](https://vercel.com) →  Add New… → Project  → import the same repo.  
2.  Root Directory:    frontend    
3.  Environment variable: 
   -    NEXT_PUBLIC_API_BASE_URL    =   https://your-api.onrender.com   (no trailing slash)
4. Deploy → open   https://your-project.vercel.app    
5. If the browser shows  CORS  errors on   /api/...  , ensure    CORS_ALLOW_ORIGINS    on Render includes    https://your-project.vercel.app    exactly (scheme + host).

---

## How to Use the App

### 1. Landing Page
When you first open the app, you'll see the landing page with options such as "Play," "Settings," and "Past Rounds." Here’s what you can do:

#### a. Play Mode Selection
- Tap **Play** to begin a new golf round.
- You will be prompted to choose between two modes:
  - **Live Mode:** Uses your device’s GPS/location to automatically update your real-time position on the golf course map. Grant location access when prompted for accurate distances and advice based on your current spot.
  - **Sim Mode:** Lets you try out all features and simulate play without being physically present at a course or providing location. Great for exploring or planning ahead.

#### b. Settings
- Tap "Settings" to open the customization page.
- Enter the average distances you hit with each club. Adjusting these values makes the app’s club recommendations more accurate.
- You can also select shot-shape preferences for your clubs (fade, draw, straight, etc.) to further tune the advice.

#### c. Past Rounds
- Access your history of previous rounds to review performance, scores, and shots

### 2. Navigating Courses and Holes
- After starting a round, you’ll arrive at the course view.
- **Hole Navigation:** Use arrow buttons or a picker to switch between holes. You can preplan or revisit any part of your round.
- For each hole, you’ll see the adjusted distance (factoring in wind, elevation, and your current position) and a visual display of wind conditions.

### 3. Interactive Map
- The map shows your position and key targets:
  - **Blue Dot:** Your current location (updates in real-time in Live mode).
  - **White Marker:** The recommended landing/aim point. You can drag this marker to choose your target.
  - **Wind:** The wind adjustment is calculated as follows:  
    - The app measures the wind speed (in mph or kph) and the angle between the wind direction and your intended shot line.  
    - The **wind effect (in yards)** is:  
    - wind_effect = wind_speed × wind_factor × cos(angle_from_shot_line)
    - A **headwind** (blowing against you) will increase the effective distance; a **tailwind** (blowing behind you) will decrease it; crosswinds have less impact but can also slightly affect lateral aim.
    - The default wind factor is approximately **0.9 yards per mph** for full shots (e.g. a 10 mph headwind adds ~9 extra yards needed; a 10 mph tailwind subtracts ~9 yards).
    - Example: If wind is 12 mph coming directly against your shot, you'll need to play for about 12 × 0.9 = 10.8 more yards.
    - The app automatically calculates this for you, displays an adjusted yardage to the pin, and updates any club recommendations accordingly.
    - We found these calculations from [this Golf Monthly article](https://www.golfmonthly.com/tips/golf-swing/how-to-calculate-distance-in-the-wind-108215)
  - **Chance of Hitting Green %:** This value is the likelihood of a PGA tour player hitting the green from that distance, to be used as a benchmark to compare shot outcomes.
  - **Distance to Hole:** This is the adjusted distance to the hole, after accounting for elevation changes and wind

### 4. Talk with Caddie (AI Advice)
- Tap **"Talk with caddie"** whenever you want expert, AI-powered guidance for your current shot.
    - The app features an interactive, conversational caddie with a Scottish accent who offers you clear, situation-specific advice. This advice incorporates real-time data such as your location, club distances, wind, and course layout.
    - You'll receive a breakdown of your shot: what type of swing is best, which hazards (water, bunkers, rough) to avoid, where to aim given current conditions, and whether an aggressive strategy (“go for the green”) or a safer layup is recommended.
    - Each shot’s advice is tailored: factoring in not just basic yardage, but also elevation, wind strength/direction, your lie, tee or approach specifics, and your personal club data. The caddie delivers not only practical direction but a one-sentence summary you can listen to with the ElevenLabs voice, perfect for heads-up use.

- **Ask Caddie Chat Feature:**  
  Under the "Talk with caddie" option, you’ll also find an AI chat interface that lets you ask your own questions to the caddie, just like texting with a real golf pro. Use this chat for deeper strategy, rules questions (“Is this area out of bounds?”), club selection tips, or explanations of the logic behind the advice. The caddie responds conversationally, adapting answers to your specific round and context.
    - Example questions:  
        - “Should I lay up short of the creek or try to carry it with my 3-wood?”  
        - “What’s the safest miss on this approach?”  
        - “Why did you pick 7-iron instead of 6-iron here?”  
        - “Explain the wind adjustment—how did you calculate?”  

    The chat can clarify caddie recommendations, break down strategy for tough shots, or just offer encouragement as you play.

### 5. Settings & Scorecard During Play
- Access **Settings** in-app anytime (side menu or button):
  - Adjust club distances, shot-shape categories, or player preferences. Changes immediately affect recommendations.
- Use the **Scorecard** to enter your strokes per hole and track your round.

#### Summary of Workflow
1. Open the app and pick Play (Live or Sim mode).
2. Enable location services (Live mode) for accurate recommendations.
3. Set your club stats and shot types in Settings for personalized advice.
4. Use the map to see your position and suggested target; move the target if you like.
5. Tap "Talk with caddie" for guidance anytime during play.
6. Listen to advice and adjust your strategy as needed.
7. Record your score after each hole.



### Limitations of the App
While the app offers helpful, real-time golf advice, there are a few limitations to keep in mind:
- **AI context:** The caddie responds based on available data and typical scenarios; unusual situations or uncommon course features may not be fully accounted for.
- **Weather data:** Wind and weather adjustments use available sensor data, which may lag behind actual conditions on the course.
- **Connectivity:** Some features, especially live AI chat, may require an internet connection.
- **Aim Point Assistance** I would have loved to have spent more time building out agentic features that would find the optimal aimpoint for a user.
- **Green Contour:** Getting access to the contours of the greens would allow me to implement green reading assistance, but unfortunately this data is not available without paying a substantial fee. 
- **More Robust Course List** The app currently only has Steven's Park Golf Course available, but I would like to expand the course list in the future.

### Try the App and Watch the Demo
- **[Try ForeAI](https://golf-caddy-app-six.vercel.app/)**  
  Click the link to access and use the app yourself.
- **[Watch a Demo](https://youtu.be/pkpECc7uTy4)**  
  See a full walkthrough of all features in action.
