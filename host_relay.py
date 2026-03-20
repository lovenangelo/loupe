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
"""
import json
import subprocess
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

ALLOWED_COMMANDS = {"gh", "claude"}


class RelayHandler(BaseHTTPRequestHandler):
    def do_POST(self):
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
        stdin_data = req.get("stdin")
        timeout = req.get("timeout", 300)

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
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9111
    server = HTTPServer(("0.0.0.0", port), RelayHandler)
    print(f"Host relay listening on :{port}")
    print(f"Allowed commands: {', '.join(sorted(ALLOWED_COMMANDS))}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
