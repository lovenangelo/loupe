"""
Loupe — One-command setup script.
Works on macOS, Linux, and Windows.

Usage:
    python3 setup.py
"""

import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
DB_FILE = ROOT / "db.sqlite3"


def check(name, cmd):
    """Return True if *cmd* is found on PATH."""
    return shutil.which(cmd) is not None


def run(args, **kwargs):
    """Run a subprocess, exit on failure."""
    result = subprocess.run(args, **kwargs)
    if result.returncode != 0:
        sys.exit(result.returncode)


def main():
    print("=== Loupe Setup ===\n")

    # --- prerequisite check ---
    prerequisites = {
        "docker": "docker",
        "gh (GitHub CLI)": "gh",
        "claude (Claude CLI)": "claude",
    }
    missing = [label for label, cmd in prerequisites.items() if not check(label, cmd)]
    if missing:
        print("Missing prerequisites:")
        for dep in missing:
            print(f"  - {dep}")
        print("\nPlease install them and re-run this script.")
        sys.exit(1)

    # Check gh auth
    result = subprocess.run(
        ["gh", "auth", "status"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        print("GitHub CLI is not authenticated. Run 'gh auth login' first.")
        sys.exit(1)

    # --- 1. Generate .env ---
    print("[1/4] Generating .env file...")
    if ENV_FILE.exists():
        print("  .env already exists, skipping. Delete it and re-run to regenerate.")
    else:
        django_key = secrets.token_urlsafe(50)
        relay_token = secrets.token_urlsafe(32)
        ENV_FILE.write_text(
            f"DJANGO_SECRET_KEY={django_key}\n"
            f"DJANGO_DEBUG=True\n"
            f"DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1\n"
            f"RELAY_AUTH_TOKEN={relay_token}\n"
        )
        print("  Created .env with generated secrets.")

    # --- 2. Create database file ---
    print("[2/4] Creating database file...")
    if DB_FILE.exists():
        print("  db.sqlite3 already exists, skipping.")
    else:
        DB_FILE.touch()
        print("  Created db.sqlite3.")

    # --- 3. Pull image and start container ---
    print("[3/4] Pulling image and starting container...")
    run(["docker", "compose", "pull"], cwd=ROOT)
    run(["docker", "compose", "up", "-d"], cwd=ROOT)

    # --- 4. Run migrations ---
    print("[4/4] Running migrations...")
    run(["docker", "compose", "exec", "web", "python", "manage.py", "migrate"], cwd=ROOT)

    print("\n=== Setup complete! ===\n")
    print("The Django app is running at: http://localhost:8000\n")
    print("Start the host relay in a separate terminal to enable gh/claude commands:")
    print("  python3 host_relay.py\n")
    print("To load sample data (optional):")
    print("  docker compose exec web python manage.py loaddata reviews/fixtures/seed.json")


if __name__ == "__main__":
    main()
