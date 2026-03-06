# Need Matcha Retail POS (Flask + Supabase)

Mobile-first point-of-sale web app with:
- 3x3 menu grid (9 products with fixed prices/images)
- Live running order total at the bottom
- Order submission to Supabase Postgres (one record per item with timestamp)
- Database page to view, edit, and delete records

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env        # Windows PowerShell: Copy-Item .env.example .env
# Then set SUPABASE_DB_POOLER_URL in .env (recommended)
python app.py
```

Open `http://localhost:5000`.

## Deploy on Render with GitHub

1. Push this repo to GitHub.
2. In Render, create a new Blueprint and select this repo.
3. In Render service environment variables, set `SUPABASE_DB_POOLER_URL` (recommended) or `SUPABASE_DB_URL`.
3. Render will use `render.yaml` and run:
   - Build: `pip install -r requirements.txt`
   - Start: `gunicorn app:app --workers=1 --threads=2 --worker-class=gthread --timeout=45 --graceful-timeout=45 --keep-alive=5`

## Notes

- App reads DB URL in this order: `SUPABASE_DB_POOLER_URL`, `SUPABASE_DB_URL`, then `DATABASE_URL`.
- `sslmode=require` is auto-applied if not present in the URL.
- If local Windows TLS inspection blocks cert validation, set `DB_SSLMODE=disable` locally only.
- Table `order_items` is auto-created at startup if missing.
- Writes use a server-side idempotency key (`Idempotency-Key`) to avoid duplicate orders on retries/timeouts.
- Optional reliability env vars:
  - `DB_CONNECT_TIMEOUT_SECONDS` (default `10`)
  - `DB_STATEMENT_TIMEOUT_MS` (default `12000`)
  - `DB_IDLE_IN_TX_TIMEOUT_MS` (default `15000`)
  - `DB_POOL_MIN_SIZE` (default `0`)
  - `DB_POOL_MAX_SIZE` (default `4`)
  - `DB_POOL_ACQUIRE_TIMEOUT_SECONDS` (default `2`)
  - `DB_WRITE_RETRIES` (default `1`)
  - `DB_WRITE_RETRY_DELAY_MS` (default `250`)
  - `SCHEMA_INIT_RETRY_INTERVAL_SECONDS` (default `300`)
