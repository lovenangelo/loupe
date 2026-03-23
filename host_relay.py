#!/usr/bin/env python3
"""
Host relay server — runs on the host machine so that the Docker container
can execute `gh` and `claude` CLI commands using the host's auth (keychain).

Usage:
    python3 host_relay.py          # listens on port 9111
    python3 host_relay.py 9222     # custom port

The container sends JSON requests:
    {"cmd": "gh", "args": ["pr", "view", "123", "--repo", "owner/repo"]}
    {"cmd": "claude", "args": ["-p", "prompt"], "stdin": "data to pipe"}

The relay runs the command on the host and returns:
    {"returncode": 0, "stdout": "...", "stderr": "..."}

Security:
    - Requires RELAY_AUTH_TOKEN env var to be set (shared secret with container)
    - Binds to 127.0.0.1 only (not accessible from network)
    - Validates arguments against allowed patterns
"""
import json
import os
import re
import subprocess
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

ALLOWED_COMMANDS = {"gh", "claude"}
RELAY_AUTH_TOKEN = os.environ.get("RELAY_AUTH_TOKEN", "")

# Rate limiting: max requests per minute
RATE_LIMIT = 30
_request_timestamps: list[float] = []

# Disallowed argument patterns (prevent dangerous flags)
DANGEROUS_PATTERNS = [
    r"--token",      # Don't allow overriding tokens
    r"--auth-token",
    r";\s*",         # Shell injection via semicolons
    r"\|\s*",        # Shell injection via pipes
    r"&&",           # Shell injection via &&
    r"\$\(",         # Command substitution
    r"`",            # Backtick command substitution
]


def _is_rate_limited():
    """Simple sliding-window rate limiter."""
    now = time.time()
    # Remove timestamps older than 60 seconds
    while _request_timestamps and _request_timestamps[0] < now - 60:
        _request_timestamps.pop(0)
    if len(_request_timestamps) >= RATE_LIMIT:
        return True
    _request_timestamps.append(now)
    return False


def _validate_args(args):
    """Check arguments for dangerous patterns."""
    for arg in args:
        if not isinstance(arg, str):
            return False, f"argument must be a string, got {type(arg).__name__}"
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, arg):
                return False, f"argument contains disallowed pattern: {arg}"
    return True, ""


class RelayHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        # Auth check
        if RELAY_AUTH_TOKEN:
            auth = self.headers.get("Authorization", "")
            if auth != f"Bearer {RELAY_AUTH_TOKEN}":
                self._respond(401, {"error": "unauthorized"})
                return
        else:
            print("[relay] WARNING: RELAY_AUTH_TOKEN not set — running without auth")

        # Rate limit
        if _is_rate_limited():
            self._respond(429, {"error": "rate limit exceeded, try again later"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            self._respond(400, {"error": "invalid JSON"})
            return

        cmd = req.get("cmd")
        if cmd not in ALLOWED_COMMANDS:
            self._respond(403, {"error": f"command not allowed: {cmd}"})
            return

        args = req.get("args", [])
        valid, reason = _validate_args(args)
        if not valid:
            self._respond(400, {"error": f"invalid argument: {reason}"})
            return

        stdin_data = req.get("stdin")
        timeout = min(req.get("timeout", 300), 300)  # Cap at 300s

        try:
            result = subprocess.run(
                [cmd] + args,
                input=stdin_data,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            self._respond(200, {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            })
        except subprocess.TimeoutExpired:
            self._respond(504, {"error": "command timed out"})
        except FileNotFoundError:
            self._respond(500, {"error": f"{cmd} not found on host"})

    def _respond(self, status, data):
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(payload))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        print(f"[relay] {fmt % args}")


def main():
    if not RELAY_AUTH_TOKEN:
        print("WARNING: RELAY_AUTH_TOKEN not set. Set it for authenticated access.")
        print("  export RELAY_AUTH_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')")

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9111
    server = HTTPServer(("127.0.0.1", port), RelayHandler)
    print(f"Host relay listening on 127.0.0.1:{port}")
    print(f"Allowed commands: {', '.join(sorted(ALLOWED_COMMANDS))}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
