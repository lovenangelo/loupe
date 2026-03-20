# Loupe

A Django-based code review tool that uses GitHub and Claude CLI to review pull requests.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- `gh` CLI authenticated on your host machine (`gh auth login`)
- `claude` CLI available on your host machine

## Getting Started

### 1. Start the host relay

The host relay is a lightweight HTTP server that runs on your machine so the Docker container can execute `gh` and `claude` commands using your local credentials.

```bash
python3 host_relay.py
```

This starts the relay on port `9111` by default. To use a custom port:

```bash
python3 host_relay.py 9222
```

### 2. Start the container

In a separate terminal:

```bash
docker compose up --build
```

This builds the image, mounts the SQLite database from your host, and starts the Django dev server on [http://localhost:8000](http://localhost:8000).

### 3. Run migrations (first time only)

```bash
docker compose exec web python manage.py migrate
```

### 4. (Optional) Load seed data

```bash
docker compose exec web python manage.py loaddata reviews/fixtures/seed.json
```

## Architecture

- **Django app** runs inside Docker on port 8000
- **Host relay** (`host_relay.py`) runs on the host on port 9111
- The container reaches the relay via `http://host.docker.internal:9111` to run `gh` and `claude` commands with the host's authentication
