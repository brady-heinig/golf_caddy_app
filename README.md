# AI Golf Caddie (FastAPI + Next.js)

## Local dev

### Backend (FastAPI)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# required (Supabase Postgres)
export DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/postgres"

# required for chat
export ANTHROPIC_API_KEY="..."

# dev cookies over http://localhost
export SECURE_COOKIES=0
export SESSION_COOKIE_SAMESITE=lax
export CORS_ALLOW_ORIGINS="http://localhost:3000"

uvicorn app.main:app --reload --port 8000
```

### Frontend (Next.js)

```bash
cd frontend
npm install
cp .env.example .env.local
# set NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm run dev
```

Open `http://localhost:3000`.

## Production hosting (private)

### Database (Supabase)

- Create a Supabase project and copy the **connection string**.
- Use the **transaction / pooled** connection string if your backend host is serverless.

You will set this value as `DATABASE_URL` on your backend host (Render/Railway/Fly/etc).

### Backend (Docker on Render/Railway/Fly)

```bash
# required
DATABASE_URL="postgresql://..."

# required for chat
ANTHROPIC_API_KEY="..."

# required for Vercel -> API cookie auth (cross-site)
SECURE_COOKIES=1
SESSION_COOKIE_SAMESITE=none

# required: your real Vercel URL(s), comma-separated
CORS_ALLOW_ORIGINS="https://YOUR-VERCEL-DOMAIN"
```

### Frontend (Vercel)

- Deploy `frontend/` to Vercel.
- Set environment variable:
  - `NEXT_PUBLIC_API_BASE_URL` = `https://YOUR-BACKEND-DOMAIN`

## First admin user

Create an admin via the API (once backend is running):

Bootstrap the first admin directly in the backend environment:

```bash
python -c "
from app.config import load_settings
from app.db import connect
from app.repos import create_user
from app.security import hash_password
settings = load_settings()
conn = connect(settings.database_url)
create_user(conn, 'admin', hash_password('CHANGE-ME-strong-password'), is_admin=True)
print('bootstrap ok')
"
```

