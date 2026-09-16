"""Run the real tsg example against a loopback API with canned responses."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread


ROOT = Path(__file__).resolve().parents[2]
QUERY = "Does this passage state a permit requirement?"
# These are fixture scores for the bundled demo text, not model judgments.
FIXTURES = (
    ("A mobile food vendor must obtain a vending permit", 0.95),
    ("The operator must obtain the site authorization", 0.85),
    ("A business placing a vehicle or stand on public land must obtain written site", 0.90),
)
MOCK_KEY = "local-mock-not-a-real-api-key"


class MockApi(HTTPServer):
    request_count = 0


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        # Do not log request headers or credentials.
        pass

    def do_POST(self):
        if self.path != "/v1/systemone":
            self.send_error(404)
            return
        if self.headers.get("Authorization") != f"Bearer {MOCK_KEY}":
            self.send_error(401)
            return
        try:
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if request["questions"]["target_matches"]["type"] != "noul":
                raise ValueError("expected the tsg Noul question")
            target = " ".join(request["state"]["target"].split())
        except (KeyError, TypeError, ValueError):
            self.send_error(400)
            return
        score = next((value for text, value in FIXTURES if text in target), 0.05)
        body = json.dumps({
            "model": "mock-demo",
            "answers": {"target_matches": {"type": "noul", "noul": score}},
        }).encode("utf-8")
        self.server.request_count += 1
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("x-typesafe-request-id", "local-mock-demo")
        self.end_headers()
        self.wfile.write(body)


def main():
    cargo = shutil.which("cargo")
    if cargo is None:
        cargo_home = Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo"))
        candidate = cargo_home / "bin" / ("cargo.exe" if os.name == "nt" else "cargo")
        if not candidate.is_file():
            print("Install Rust nightly with rustup before running this demo.", file=sys.stderr)
            return 1
        cargo = str(candidate)

    env = os.environ.copy()
    env["PATH"] = str(Path(cargo).parent) + os.pathsep + env.get("PATH", "")
    # Replace any real key only in the child process environment.
    env["TYPESAFE_API_KEY"] = MOCK_KEY
    env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost"
    print("MOCK DEMO: fixed fixture scores; no AI inference or real API key.", flush=True)
    with MockApi(("127.0.0.1", 0), Handler) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            result = subprocess.run([
                cargo, "run", "--locked", "--example", "tsg", "--",
                "--color", "never", "grep", QUERY, "examples/tsg/demo/",
                "--unit", "section", "--model", "mock-demo",
                "--base-url", f"http://127.0.0.1:{server.server_port}",
                "--concurrency", "1", "--retries", "0", "--timeout-seconds", "5",
                "--no-progress",
            ], cwd=ROOT, env=env, check=False)
        finally:
            server.shutdown()
            worker.join()
        print(f"Local mock handled {server.request_count} HTTP requests.", flush=True)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
