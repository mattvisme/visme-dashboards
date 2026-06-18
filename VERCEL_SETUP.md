# Vercel Deployment with Password Protection

## How It Works

1. **Login Page** (`login.html`): Users enter their password
2. **Auth Script** (`auth.js`): Included in every dashboard page; redirects unauthenticated visitors to `login.html`
3. **Session**: After login, users stay authenticated for 24 hours via `localStorage`
4. **No-index**: All pages carry `<meta name="robots" content="noindex, nofollow">`, `X-Robots-Tag` response headers, and `robots.txt` to prevent search engine indexing

## Password management

The password is **never hardcoded in any committed file**. It lives in three places:

| Location | Purpose |
|----------|---------|
| Vercel project → Settings → Environment Variables → `dashboard_pw` | Injected at deploy time on Vercel |
| GitHub repo → Settings → Secrets and variables → Actions → `dashboard_pw` | Injected during the weekly GitHub Actions rebuild |
| `.env.local` (local, gitignored) | Local development only — never committed |

`login.html` in the repo contains the placeholder `__DASHBOARD_PASSWORD__`. The `scripts/build_auth.py` step replaces it with the real value at build time.

## Required secrets (one-time setup)

### Vercel
`dashboard_pw` is already set in the Vercel project dashboard under **Settings → Environment Variables**. No action needed there.

### GitHub Actions
`dashboard_pw` must be added as a GitHub Actions secret so the weekly rebuild can inject the password into `login.html` before committing it.

1. Go to: **GitHub repo → Settings → Secrets and variables → Actions**
2. Click **New repository secret**
3. Name: `dashboard_pw`
4. Value: same value as the Vercel environment variable
5. Click **Add secret**

### Local development
Create `.env.local` in the repo root (it is gitignored and must never be committed):

```
dashboard_pw=Visme@2026!Dashboard
```

Use `.env.example` as a reference template.

Then run:

```bash
python scripts/build_auth.py
```

This injects the password into your local `login.html` for testing. Do not commit the result.

## Changing the password

1. Update the value in **Vercel → Settings → Environment Variables**
2. Update the value in **GitHub → Settings → Secrets and variables → Actions**
3. Update `.env.local` locally
4. Trigger a manual rebuild via GitHub Actions (workflow_dispatch) or wait for the next Monday rebuild

## Troubleshooting

### "Password not working"
- Make sure you're using the password exactly as configured in Vercel/GitHub secrets
- Try clearing browser local storage: open DevTools (F12) → Console → `localStorage.clear()`

### "Dashboard accessible without login"
- Verify `auth.js` is present at the repo root and deployed to Vercel
- Verify every dashboard HTML file has `<script src="/auth.js"></script>` in `<head>`

### "Logout"
Open DevTools (F12) → Console:
```javascript
localStorage.removeItem('dashboard_authenticated');
```
