# Deploying to AWS Lightsail

Hosts the whole portal — web (gunicorn behind nginx) + background worker —
on one Lightsail instance. MongoDB stays external (Atlas); Lightsail only
runs the two Python processes.

## 1. Create the instance

- Lightsail console → Create instance → Linux/Unix → OS Only → **Ubuntu 22.04 LTS**
- Size: 2 GB RAM / 2 vCPU plan minimum (1 GB works for testing, but the
  worker + gunicorn workers + Strands calls can get tight)
- Networking tab → attach a **static IP** before going further (so the
  OAuth redirect URIs you register don't break on reboot)
- Firewall (networking tab): allow **80** and **443** in addition to the
  default 22 (SSH)

## 2. Point a domain at it (needed for real OAuth + HTTPS)

Google/Slack/Jira OAuth all require a real HTTPS callback (Slack rejects
plain IPs outright). Point an A record at the static IP before continuing.

## 3. Install dependencies

SSH in, then:

```bash
sudo apt update && sudo apt install -y python3.11 python3.11-venv nginx certbot python3-certbot-nginx git
sudo mkdir -p /opt/chief-of-staff && sudo chown ubuntu:ubuntu /opt/chief-of-staff
```

### Clone with a deploy key (recommended over plain HTTPS)

Generate the key **on the instance** — the private half should never leave
it. Add the public half as a **read-only Deploy key** on the GitHub repo
(Settings → Deploy keys → Add deploy key, leave "Allow write access"
unchecked — this instance only ever pulls).

```bash
ssh-keygen -t ed25519 -C "lightsail-deploy-chief-of-staff" -f ~/.ssh/chief_of_staff_deploy -N ""
cat ~/.ssh/chief_of_staff_deploy.pub   # paste this into GitHub -> Deploy keys
cat >> ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/chief_of_staff_deploy
  IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
ssh -T git@github.com   # expect: "Hi <owner>/chief-of-staff! You've successfully authenticated"
git clone git@github.com:rajaathota72-fc/chief-of-staff.git /opt/chief-of-staff
cd /opt/chief-of-staff
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 4. Configure `.env`

Copy `.env.example` to `/opt/chief-of-staff/.env` and fill in real values —
same variables as local dev, plus these become load-bearing in production:

```bash
COS_ENV=production
COS_BASE_URL=https://your-domain.example
FLASK_SECRET_KEY=$(openssl rand -hex 32)
COS_ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
MONGODB_URI=mongodb+srv://...        # Atlas, with this instance's IP allowlisted
SMTP_HOST=... SMTP_FROM=...          # required once COS_ENV=production (see app.py's startup check)
```

`create_app()` refuses to start in production without `COS_BASE_URL` on
https, a stable `FLASK_SECRET_KEY` of 32+ chars, and SMTP configured — it's
a deliberate guard, not a bug, if boot fails on a missing one of these.

Update every provider's OAuth app (Google Cloud Console, Slack app, Atlassian
dev console, GitHub OAuth App) with the new callback URLs:
`https://your-domain.example/oauth/<provider>/callback` (and
`/auth/google/callback` for sign-in) — the redirect URI Google/Slack/Jira/
GitHub see must exactly match `COS_BASE_URL`.

## 5. Install the systemd services

```bash
sudo cp deploy/lightsail/chief-of-staff-web.service /etc/systemd/system/
sudo cp deploy/lightsail/chief-of-staff-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now chief-of-staff-web chief-of-staff-worker
sudo systemctl status chief-of-staff-web chief-of-staff-worker   # confirm both are active
```

## 6. nginx + HTTPS

```bash
sudo cp deploy/lightsail/nginx.conf /etc/nginx/sites-available/chief-of-staff
sudo sed -i 's/your-domain.example/YOUR_REAL_DOMAIN/' /etc/nginx/sites-available/chief-of-staff
sudo ln -s /etc/nginx/sites-available/chief-of-staff /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d YOUR_REAL_DOMAIN   # rewrites the site config to add HTTPS + redirect
```

## 7. Verify

```bash
curl https://YOUR_REAL_DOMAIN/health   # {"status":"ok"}
```

Then sign up through the real UI and run a live briefing.

## Updating a deploy

```bash
cd /opt/chief-of-staff && git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart chief-of-staff-web chief-of-staff-worker
```

Both services must restart together on any code change — like local dev,
gunicorn doesn't hot-reload templates/static files in production mode, and
the worker is a separate long-running process holding old imports.

## Notes

- One Lightsail instance runs both processes; the worker's leader-election
  lease (see `docs/architecture.md`) means you *can* later add a second
  instance/worker for redundancy without code changes — only one becomes
  leader at a time.
- This is independent of the AgentCore Runtime path (`AGENTCORE_RUNTIME_ARN`
  in `.env`) — Lightsail hosts the portal either way; AgentCore Runtime, if
  configured, is a separate AWS-managed process the worker calls out to for
  the actual briefing reasoning. See `docs/architecture.md`.
