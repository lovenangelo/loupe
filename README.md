<p align="center">
  <img src="design/static/images/logo.png" alt="Loupe" width="120">
</p>

<h1 align="center">Loupe</h1>

<p align="center">Automated PR review tool powered by Claude — find bugs, security issues, and code smells, then post comments back to GitHub.</p>

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- [GitHub CLI](https://cli.github.com/) authenticated (`gh auth login`)
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-cli) available on your machine

## Quick Start (Docker Image)

No cloning or building required. Download the two files you need, then run:

**macOS / Linux:**

```bash
mkdir loupe && cd loupe
curl -fsSLO https://raw.githubusercontent.com/lovenangelo/loupe/main/docker-compose.yml
curl -fsSLO https://raw.githubusercontent.com/lovenangelo/loupe/main/host_relay.py
curl -fsSLO https://raw.githubusercontent.com/lovenangelo/loupe/main/setup.py
python3 setup.py
```

**Windows (PowerShell):**

```powershell
mkdir loupe; cd loupe
foreach ($f in @("docker-compose.yml","host_relay.py","setup.py")) {
  Invoke-WebRequest "https://raw.githubusercontent.com/lovenangelo/loupe/main/$f" -OutFile $f
}
python3 setup.py
```

Then start the host relay in a separate terminal:

```bash
python3 host_relay.py
```

The app will be running at [http://localhost:8000](http://localhost:8000).

### What `setup.py` does

1. Checks prerequisites (`docker`, `gh`, `claude`)
2. Generates secrets and creates a `.env` file
3. Creates the SQLite database file
4. Pulls `ghcr.io/lovenangelo/loupe:main` and starts the container
5. Runs database migrations

### Docker image

Published to GitHub Container Registry on every push to `main`:

```
ghcr.io/lovenangelo/loupe:main
```

Tagged releases are also available (e.g. `ghcr.io/lovenangelo/loupe:1.0.0`).

Browse tags: https://github.com/lovenangelo/loupe/pkgs/container/loupe

## How It Works

Loupe runs as a Docker container but needs access to `gh` and `claude` on your host machine. The **host relay** is a lightweight HTTP server that bridges this gap:

```
Browser → [Docker container :8000] → [Host Relay :9111] → gh / claude CLI
```

This is why you need both the container **and** the relay running.

<details>
<summary><strong>Setup from source</strong> (for contributors)</summary>

```bash
git clone https://github.com/lovenangelo/loupe.git
cd loupe
python3 setup.py                # same setup script, but uses local docker-compose.yml
python3 host_relay.py           # in a separate terminal
```

To build the image locally instead of pulling:

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up --build -d
```

</details>

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
