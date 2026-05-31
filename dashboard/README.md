# Apex Dashboard

Next.js 14 (App Router) command centre for the Apex Algo. Auth via NextAuth v5
(single-user JWT), realtime via SSE polling the VPS state server.

## Local dev

```bash
npm install
cp .env.example .env.local
# fill in AUTH_SECRET, DASHBOARD_USERNAME, DASHBOARD_PASSWORD_HASH, VPS_URL, VPS_SECRET
npm run dev   # http://localhost:3000
```

Generate the secrets:

```bash
# AUTH_SECRET
openssl rand -base64 32
# bcrypt password hash
node -e "console.log(require('bcryptjs').hashSync('YOUR_PASSWORD', 12))"
```

## Deploy to Vercel

1. Import the repo in Vercel and set the **Root Directory** to `dashboard/`.
2. Add the env vars from `.env.example` in Project Settings → Environment Variables.
3. `VPS_URL` must point at the FastAPI state server (e.g. `https://your-vps:8080`),
   and `VPS_SECRET` must match the algo's `VPS_SECRET`.
4. Deploy. The middleware protects every route; visit `/login` to sign in.

## How data flows

`/api/stream` (SSE, Node runtime) polls `VPS_URL/state` every 3s with the
`X-Apex-Secret` header and streams `state` events to the browser. `useStream`
parses them; components render. No WebSockets (Vercel serverless doesn't hold them).
