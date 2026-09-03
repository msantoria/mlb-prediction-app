# MyDashboard authentication operations

MyDashboard keeps its existing email/password login and adds Google OAuth, GitHub OAuth, and one-time password recovery. The report workspace and existing session contract are unchanged.

## Railway configuration

Add every variable below to the **backend** Railway service (`mlb-prediction-app`), not the frontend service:

- `DASHBOARD_FRONTEND_URL=https://mlbgpt.com`
- `DASHBOARD_OAUTH_CALLBACK_BASE_URL=https://<backend-service>.up.railway.app`
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GITHUB_OAUTH_CLIENT_ID`
- `GITHUB_OAUTH_CLIENT_SECRET`
- `SMTP_HOST`
- `SMTP_PORT` (normally `587`)
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM_EMAIL`
- `SMTP_USE_TLS=1`
- `SMTP_USE_SSL=0`

Do not commit provider secrets. Railway must redeploy the backend after variables change.

## Google OAuth setup

1. In Google Cloud Console, create or select a project and configure the OAuth consent screen.
2. Create a Web application OAuth client.
3. Add this exact authorized redirect URI:
   `https://<backend-service>.up.railway.app/my-dashboard/auth/oauth/google/callback`
4. Copy the client ID and secret to the backend Railway variables.
5. The app requests only `openid email profile` and accepts only a Google-verified email.

## GitHub OAuth setup

1. In GitHub, open Settings → Developer settings → OAuth Apps → New OAuth App.
2. Set Homepage URL to `https://mlbgpt.com`.
3. Set Authorization callback URL to:
   `https://<backend-service>.up.railway.app/my-dashboard/auth/oauth/github/callback`
4. Copy the client ID and secret to the backend Railway variables.
5. The app requests `read:user user:email` and accepts only a GitHub-verified email.

## Password reset setup

Configure any standard SMTP service with the Railway variables above. The sender address must be verified with that provider. Reset requests always return the same response whether an account exists or not.

Reset controls:

- Tokens are random and stored only as SHA-256 hashes.
- A token expires after 30 minutes and works once.
- Issuing a new token invalidates earlier unused tokens.
- Requests for the same account are limited to one per minute.
- A successful reset revokes all existing MyDashboard sessions.
- Email delivery failure does not disclose whether an account exists.

## Verification checklist

1. Confirm `GET /my-dashboard/auth/providers` reports Google and GitHub as configured.
2. Sign in once with each provider and confirm return to `https://mlbgpt.com/my-dashboard`.
3. Confirm a provider with the same verified email opens the existing account instead of creating a duplicate.
4. Request a password reset for both a real and unknown email; both responses must be identical.
5. Use a reset link once, confirm the new password works, then confirm the same link fails.
6. Confirm sessions active before the password reset no longer authorize API requests.
7. Confirm existing email/password registration and login still work.

## Incident response

If a provider secret is exposed, rotate it at the provider and in Railway immediately. If OAuth must be paused, remove that provider's client ID or secret; its button remains visible but reports that the provider is not configured. Password login remains available. To pause password reset delivery, remove the SMTP sender or host and investigate backend logs.
