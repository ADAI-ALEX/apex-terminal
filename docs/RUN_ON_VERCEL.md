# Run-from-anywhere: config & login on Vercel, engine on your laptop

This is the "I don't want two logins/configs and I don't want to manage anything on
my laptop" setup. The control plane (login, onboarding config, live dashboard) lives
entirely on Vercel; your laptop just runs the trading engine and talks to Vercel.

```
  Browser (any device)
        │ login + onboarding wizard + live dashboard
        ▼
   Vercel dashboard ─────►  Vercel KV (free Redis)  ◄─────  your laptop: python main.py
     reads apex:state          apex:config                    reads config, trades,
     writes apex:config        apex:state                     pushes state every ~30s
```

**Why this works with no tunnel:** your laptop only makes **outbound** calls (to KV
and to IG). Nothing ever connects *into* your laptop, so there's no port-forwarding,
no ngrok/cloudflared, no firewall changes.

> Trade-off: in cloud-relay mode your IG/Claude keys live in the Redis store, gated by
> a server-only REST token (the same security model as Vercel env vars), rather than
> Fernet-encrypted on disk. The token is never exposed to the browser.

---

## One-time setup (≈5 minutes)

### 1. Attach a free Redis store to your Vercel project
1. Vercel → your **apex-dashboard** project → **Storage** tab → **Create / Connect Database**.
2. Pick a **Redis** integration from the Marketplace (Upstash is the default) → **Free** plan.
3. Connect it to the project for the **Production** environment. Vercel auto-injects the
   credentials (`KV_REST_API_URL` + `KV_REST_API_TOKEN`, or `UPSTASH_REDIS_REST_URL/TOKEN`).

### 2. Redeploy the dashboard so it sees the new env vars
From `dashboard/`:
```bash
vercel deploy --prod
```
(Or click **Redeploy** on the latest deployment in the Vercel dashboard.)

### 3. Point your laptop at the same store
Just run **`start.bat`** again. It runs `scripts/setup_local_env.py`, which pulls the
KV credentials down from Vercel into your local `.env`, and prints:

```
Mode : CLOUD RELAY (Vercel KV) ...
```

That confirms the engine is in cloud-relay mode.

---

## Daily use
1. On the laptop: run **`start.bat`** (or just `venv\Scripts\python main.py`). Leave it running.
   In cloud mode you don't even need the local dashboard window.
2. From **any device, anywhere**: open your Vercel URL
   (https://apex-dashboard-pearl.vercel.app), log in, and use the onboarding wizard +
   dashboard. Config is saved to Vercel KV; your laptop picks it up within ~5s and starts
   trading; live data flows back to the dashboard.

The dashboard's status bar shows the heartbeat age — if it's stale, your laptop engine
isn't running.

---

## Notes & limits
- **Free KV usage:** the dashboard polls state every ~10s and the engine writes every
  ~30s — comfortably inside Upstash's free monthly command allowance for one user.
- **Credential validation:** in cloud mode the "Test connection" buttons defer to the
  engine — it validates IG/Claude live when it picks up the saved config, then writes
  the result back to the dashboard.
- **Turning it off:** remove the KV env vars (or detach the store) and re-run
  `start.bat`; the system falls back to direct local mode (dashboard ↔ `localhost:8080`).
- **The laptop must be on** for trading to happen. For true 24/5 unattended operation,
  move `python main.py` to a always-on host (see `docs/PROP_FIRM_PLAN.md` Phase 4); the
  cloud-relay design means *only* `VPS`/host changes — the dashboard is unaffected.
