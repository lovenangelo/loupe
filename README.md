<p align="center">
  <img src="design/static/images/logo.png" alt="Loupe" width="120">
</p>

<h1 align="center">Loupe</h1>

<p align="center">Automated PR review tool powered by Claude — find bugs, security issues, and code smells, then post comments back to GitHub.</p>

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- `gh` CLI authenticated on your host machine (`gh auth login`)
- `claude` CLI available on your host machine

## Quick Start

```bash
git clone https://github.com/lovenangelo/loupe.git
cd loupe
python3 setup.py
```

This will:
1. Generate secrets and create your `.env` file
2. Create the SQLite database file
3. Pull the pre-built Docker image from `ghcr.io/lovenangelo/loupe`
4. Start the container and run migrations

Then start the host relay in a separate terminal:

```bash
python3 host_relay.py
```

The app will be running at [http://localhost:8000](http://localhost:8000).

## How It Works

Loupe runs as a Docker container but needs access to `gh` and `claude` CLIs on your host machine. The **host relay** (`host_relay.py`) bridges this gap — it's a lightweight HTTP server that the container calls to execute commands using your local credentials.

```
Browser → [Django in Docker :8000] → [Host Relay :9111] → gh / claude CLI
```

This is why you need both the container and the relay running.

## Docker Image

The pre-built image is published to GitHub Container Registry on every push to `main`:

```
ghcr.io/lovenangelo/loupe:main
```

Tagged releases are also available (e.g. `ghcr.io/lovenangelo/loupe:1.0.0`).

Browse available tags: https://github.com/lovenangelo/loupe/pkgs/container/loupe

<details>
<summary><strong>Manual Setup</strong></summary>

### 1. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Description |
|----------|-------------|
| `DJANGO_SECRET_KEY` | Random secret key. Generate: `python3 -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DJANGO_DEBUG` | `True` for local dev, `False` for production |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames (default: `localhost,127.0.0.1`) |
| `RELAY_AUTH_TOKEN` | Shared secret for the relay. Generate: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |

### 2. Create the database file

**macOS / Linux:**
```bash
touch db.sqlite3
```

**Windows (Command Prompt):**
```cmd
type nul > db.sqlite3
```

**Windows (PowerShell):**
```powershell
New-Item db.sqlite3 -ItemType File
```

### 3. Pull and start

```bash
docker compose pull
docker compose up -d
```

### 4. Run migrations

```bash
docker compose exec web python manage.py migrate
```

### 5. Start the host relay

```bash
python3 host_relay.py
```

</details>

<details>
<summary><strong>Building from source</strong></summary>

For development, build the image locally instead of pulling:

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up --build -d
```

</details>

## Architecture

- **Django app** runs inside Docker on port 8000
- **Host relay** (`host_relay.py`) runs on the host on `127.0.0.1:9111`
- The container reaches the relay via `http://host.docker.internal:9111` to run `gh` and `claude` commands with the host's authentication

## Security

Loupe is designed for **local, single-user use**. Key security measures in place:

- **Host relay** is bound to `127.0.0.1` only (not accessible from the network), requires a shared auth token, validates command arguments, and enforces rate limiting
- **Django settings** load secrets from environment variables, default to `DEBUG=False`, and restrict `ALLOWED_HOSTS`
- **Security headers** are enabled (XSS protection, content-type sniffing prevention, clickjacking protection, strict cookie policies)
- **HTTPS-only settings** (HSTS, secure cookies) activate automatically when `DEBUG=False`
- **Input validation** enforces `owner/repo` format and caps field lengths to prevent abuse
- **CSRF protection** is enabled on all state-changing endpoints
- The `.env` file is gitignored — never commit your tokens or secrets

> **Important:** If you plan to expose this app beyond localhost, you should add user authentication and switch to a production-grade server (e.g. gunicorn behind nginx).
