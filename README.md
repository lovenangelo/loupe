<p align="center">
  <img src="design/static/images/logo.png" alt="Loupe" width="120">
</p>

<h1 align="center">Loupe</h1>

<p align="center">Automated PR review tool powered by Claude — find bugs, security issues, and code smells, then post comments back to GitHub.</p>

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- `gh` CLI authenticated on your host machine (`gh auth login`)
- `claude` CLI available on your host machine

## Getting Started

### 1. Configure environment variables

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

Then edit `.env`:

| Variable | Description |
|----------|-------------|
| `DJANGO_SECRET_KEY` | Random secret key for Django sessions/CSRF. Generate one with: `python3 -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DJANGO_DEBUG` | Set to `True` for local development, `False` for production |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames (default: `localhost,127.0.0.1`) |
| `RELAY_AUTH_TOKEN` | Shared secret between the container and host relay. Generate one with: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |

### 2. Start the host relay

The host relay is a lightweight HTTP server that runs on your machine so the Docker container can execute `gh` and `claude` commands using your local credentials.

```bash
python3 host_relay.py
```

This starts the relay on `127.0.0.1:9111` by default. To use a custom port:

```bash
python3 host_relay.py 9222
```

### 3. Create the database file (first time only)

Docker requires the SQLite file to exist on the host before starting the container. Without it, Docker will create a directory instead of a file, causing errors.

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

### 4. Start the container

In a separate terminal:

```bash
docker compose up --build
```

This builds the image, mounts the SQLite database from your host, and starts the Django dev server on [http://localhost:8000](http://localhost:8000).

### 5. Run migrations (first time only)

```bash
docker compose exec web python manage.py migrate
```

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
