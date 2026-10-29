# AI Smart Mail Manager

> **Production-Ready, Enterprise-Grade Intelligent Email Workspace** built with Django 5.x, Real Google OAuth 2.0, Real Gmail API Synchronization, Real-Time WebSockets (Django Channels), Asynchronous Celery Workers, Structured AI Classification, Daily Executive Briefings, and Context-Aware Smart Replies.

---

## 🌟 Executive Summary & Full System Pipeline

**AI Smart Mail Manager** transforms high-volume email workflows into a focused, prioritized workspace. By unifying OAuth 2.0 authorization, automated MIME synchronization, LLM intelligence, WebSocket push notifications, and threaded response generation into a single cohesive platform, users regain control of their communication streams.

```
       +-----------------------+
       |   Google OAuth 2.0    |
       |  (Read & Send Scopes) |
       +-----------+-----------+
                   |
                   v
       +-----------------------+
       |  Gmail Synchronization |  <--- Background Celery Worker
       |   (MIME RFC822 / XSS)  |
       +-----------+-----------+
                   |
                   v
       +-----------------------+
       |  AI Classification    |  <--- 14 Canonical Categories &
       | (OpenAI / Ollama / LLM)|       Structured Schema Validation
       +-----------+-----------+
                   |
                   +------------------------------+
                   |                              |
                   v                              v
       +-----------------------+      +-----------------------+
       |   Urgency & VIP Rules |      | Real-Time Notification|
       | (PrioritySender/Rules)|      | (WebSockets & WebPush)|
       +-----------+-----------+      +-----------------------+
                   |
                   +------------------------------+
                   |                              |
                   v                              v
       +-----------------------+      +-----------------------+
       |  Daily AI Briefing    |      |  AI Smart Reply Studio|
       | (Executive Summaries) |      | (Human-in-the-Loop)   |
       +-----------------------+      +-----------+-----------+
                                                  |
                                                  v
                                      +-----------------------+
                                      | Threaded RFC2822 Send |
                                      | (Double-Send Protected)|
                                      +-----------------------+
```

---

## 🚀 Key Feature Matrix

| Subsystem | Capabilities |
|---|---|
| **Authentication & Profiles** | Custom `accounts.User` (unique email, dual email/username login), user avatars, profile customization, password change/reset flow. |
| **Gmail OAuth 2.0** | Cryptographic CSRF state checks, Fernet token encryption at rest (`cryptography.fernet`), automated token refresh, and safe remote revocation. |
| **Email Synchronization** | Batch pagination (`users.messages.list`), recursive MIME parsing (`multipart/mixed`, `alternative`, `related`), XSS sanitization via `bleach` & `CSSSanitizer`, attachment tracking, and database idempotency. |
| **AI Classification** | 14 canonical categories (`Education`, `Work`, `Finance`, `Technology`, etc.), importance detection, urgency scoring (`High`, `Medium`, `Low`), confidence ratings, and prompt injection defense. |
| **VIP Sender Intelligence** | `PrioritySender` rules with case-insensitive normalization, display name overrides, and explainable multi-tier importance hierarchy. |
| **Real-Time Notifications** | Django Channels WebSocket layer, short-polling fallback, HTML5 desktop notifications, PWA/Web Push pipeline (`pywebpush`), audio chime synthesizer, and dedup-keyed storage. |
| **Daily Email Summaries** | Timezone-aware date boundaries, executive briefings, bulleted highlights, actionable checklists, and category breakdowns with caching. |
| **AI Smart Reply Studio** | Contextual drafting across 4 distinct tones (`Professional`, `Friendly`, `Urgent`, `Concise`), static templates, human-in-the-loop review, and double-send protection. |
| **Production Hardening** | WhiteNoise compressed & hashed static asset pipeline, dual SQLite/PostgreSQL support via `DATABASE_URL`, Celery task workers, security headers (`HSTS`, `CSP`, `X-Content-Type-Options`), custom error pages (400, 403, 404, 429, 500), and credential-scrubbing log filters. |

---

## 🛠️ Technology Stack & Dependencies

- **Language & Framework**: Python 3.12+ / 3.13, Django 5.0+
- **Asynchronous & Real-Time**: Daphne 4.1+, Django Channels 4.0+, Celery 5.4+, Redis 5.0+
- **Production Asset Pipeline**: WhiteNoise 6.6+ (`CompressedManifestStaticFilesStorage`)
- **Database**: SQLite (local development) / PostgreSQL 15+ (production via `dj-database-url` and `psycopg2-binary`)
- **Security & Cryptography**: `cryptography.fernet`, `bleach`, `CSSSanitizer`, `pywebpush`
- **Frontend & Styling**: Bootstrap 5.3.3, Bootstrap Icons 1.11.3, Chart.js 4.4.2

---

## 💻 Local Development Setup

### 1. Clone & Set Up Virtual Environment

```bash
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Copy the provided template:
```bash
cp .env.example .env
```
Ensure the following basic values are set in `.env`:
```env
DEBUG=True
SECRET_KEY=local-dev-insecure-key-replace-in-prod-xyz123
ALLOWED_HOSTS=127.0.0.1,localhost
DATABASE_URL=sqlite:///db.sqlite3
```

### 4. Apply Migrations

```bash
python manage.py migrate
```

### 5. Seed Demonstration Data (Optional)

```bash
python manage.py seed_demo_data --clean
```
- **Demo User**: `demo@example.com`
- **Demo Password**: `demo12345`

### 6. Start the Server

```bash
# Standard development server
python manage.py runserver

# Or ASGI server with real-time WebSockets
daphne -b 127.0.0.1 -p 8000 config.asgi:application
```
Visit `http://127.0.0.1:8000/` in your browser.

---

## 🔑 Google Cloud OAuth 2.0 Credentials Setup

To connect real Gmail accounts and synchronize live correspondence:

1. Navigate to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project and enable the **Gmail API** under **APIs & Services > Library**.
3. Configure the **OAuth Consent Screen**:
   - User Type: **External**
   - Application Name: `AI Smart Mail Manager`
   - Scopes:
     - `https://www.googleapis.com/auth/gmail.readonly` (Read correspondence)
     - `https://www.googleapis.com/auth/userinfo.email` (Account identification)
     - *(Optional for Phase 7 sending)*: `https://www.googleapis.com/auth/gmail.send`
   - Add your test Google accounts to the **Test Users** list.
4. Create Credentials:
   - Type: **OAuth 2.0 Client IDs > Web application**
   - Authorized redirect URIs:
     - `http://127.0.0.1:8000/gmail/oauth/callback/`
     - *(Production)* `https://yourdomain.com/gmail/oauth/callback/`
5. Update `.env`:
   ```env
   GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=your-client-secret
   GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/gmail/oauth/callback/
   GMAIL_TOKEN_ENCRYPTION_KEY=your-32-byte-fernet-key
   ```

---

## 🤖 AI Configuration (OpenAI, Ollama, Local Models)

The AI Engine features a provider abstraction (`ai_engine/providers/`). Configure your chosen provider in `.env`:

### OpenAI / OpenAI-Compatible (vLLM, Groq, OpenRouter)
```env
AI_PROVIDER=openai
AI_API_KEY=sk-your-openai-api-key-here
AI_MODEL=gpt-4o-mini
AI_TEMPERATURE=0.2
AI_MAX_TOKENS=500
```

### Local Models (Ollama)
```env
AI_PROVIDER=openai
AI_BASE_URL=http://localhost:11434/v1
AI_API_KEY=ollama
AI_MODEL=llama3:8b
```

---

## ⚡ Background Processing: Celery & Redis Setup

For high-volume production deployments, email synchronization, AI classification, and daily briefing jobs run asynchronously via Celery:

### 1. Start Redis
```bash
# Local Redis container
docker run -d -p 6379:6379 redis:7-alpine
```

### 2. Configure `.env`
```env
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1
CHANNELS_REDIS_URL=redis://127.0.0.1:6379/2
```

### 3. Launch Workers
```bash
# Start Celery worker
celery -A config worker --loglevel=info -P gevent -c 100

# Start Celery Beat (Periodic scheduler)
celery -A config beat --loglevel=info
```

---

## 🚢 Production Deployment Guide

### 1. Database Configuration (PostgreSQL)

Set `DATABASE_URL` in `.env`:
```env
DATABASE_URL=postgres://mailuser:securepassword@db.example.com:5432/smartmail_prod
```
Run migrations:
```bash
python manage.py migrate
```

### 2. Static Asset Compilation (WhiteNoise)

WhiteNoise handles compression and cache-busting headers automatically:
```bash
python manage.py collectstatic --no-input
```

### 3. Production Environment Checklist (`.env`)

```env
DEBUG=False
SECRET_KEY=cryptographically-strong-random-50-character-secret-key
ALLOWED_HOSTS=mail.yourdomain.com
SECURE_HSTS_SECONDS=31536000
SECURE_SSL_REDIRECT=True
DJANGO_LOG_LEVEL=INFO
```

### 4. Running with Gunicorn / Daphne Behind Nginx

Use Daphne as the primary ASGI entrypoint to serve HTTP and WebSockets simultaneously:
```bash
daphne -b 127.0.0.1 -p 8000 --proxy-headers config.asgi:application
```

Example Nginx reverse proxy configuration block:
```nginx
upstream smartmail_backend {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name mail.yourdomain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name mail.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/mail.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mail.yourdomain.com/privkey.pem;

    location /static/ {
        alias /var/www/ai_smart_mail_manager/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, max-age=2592000, immutable";
    }

    location /media/ {
        alias /var/www/ai_smart_mail_manager/media/;
        expires 7d;
    }

    location / {
        proxy_pass http://smartmail_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

---

## 🔒 Security Hardening & Zero-Leakage Architecture

- **Multi-Tenant Isolation**: Every database query is strictly scoped to `request.user`. Attempting to access another user's email, notification, summary, or draft raises an immediate HTTP 404/403.
- **Token Encryption at Rest**: OAuth tokens are encrypted using AES-128-CBC with HMAC authentication (`cryptography.fernet`).
- **Zero Credential Leaking in Logs**: Custom `SensitiveDataFilter` actively strips Bearer tokens, Google `ya29.*` tokens, OpenAI keys (`sk-*`), and password hashes before writing to disk or console.
- **XSS-Immune Email Rendering**: HTML bodies are strictly filtered through `bleach` and `CSSSanitizer`.
- **Double-Send Prevention**: Gmail outbound replies use atomic database transactions with row-level locking (`select_for_update`) transitioning the draft to `SENDING` status before dispatching via Google APIs.

---

## 🧪 Comprehensive Automated Test Suite

The project includes 183 automated tests covering models, views, OAuth handlers, MIME synchronization, AI validation, WebSockets, background tasks, and production security isolation:

```bash
# Run the entire test suite
python manage.py test

# Run Phase 8 integration tests specifically
python manage.py test tests.test_phase8_final_integration

# Run deployment security audit
python manage.py check --deploy
```

All 183 tests pass with 0 failures and 0 errors:
```
Ran 183 tests in 62.026s
OK
```

---

## ⚠️ Known Limitations & Future Roadmap

1. **Google OAuth Verification**:
   - While in development/testing mode, Google limits OAuth connections to registered Test Users. Production rollout requires submitting the OAuth Consent Screen for Google Verification.
2. **Push Notifications**:
   - Web Push requires generating and populating VAPID keys (`VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY`) in `.env` along with browser service worker permissions.
3. **IMAP / Non-Gmail Mailboxes**:
   - Current synchronization is optimized for the Gmail API. Standard IMAP/SMTP multi-provider adapters can be added in subsequent milestones.
4. **Offline Mode**:
   - The application relies on active server connectivity for real-time WebSocket notifications and LLM inference.
