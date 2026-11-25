"""Local checkout server. Run python app.py --help for the reference experiment."""
import argparse
from contextlib import closing
from functools import partial
from http import HTTPStatus
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from flagsmith.exceptions import FlagsmithClientError
import json
import mimetypes
from pathlib import Path
import secrets
from urllib.parse import parse_qs, urlsplit
from string import Template

import experiment as exp
import flagsmith_bridge as flag


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
COOKIE = "parcel_math_visitor"
STATIC = {"/": "index.html", "/style.css": "style.css", "/app.js": "app.js",
          "/web/style.css": "style.css", "/web/app.js": "app.js"}


def percentage(number, total):
    return f"{100 * number/total:.1f}%" if total else "n/a"


def render_results(data, native=None):
    table = []
    for variant, name in (("standard", "Shipping fee"), ("landed", "Order total")):
        arm = data["arms"][variant]
        table.append("<tr>" + "".join(f"<td>{value}</td>" for value in (
            name, arm["exposed"], arm["confirmed"], arm["within"], percentage(arm["within"], arm["exposed"])
        )) + "</tr>")
    delta = data["delta"]
    gap = "Run pending" if delta is None else f"{100*delta:+.1f} pp"
    interval = data["interval"]
    interval_text = ("Awaiting exposures in both arms." if interval is None else
                     f"95% interval {100*interval[0]:+.1f} to {100*interval[1]:+.1f} percentage points.")
    sample = sum(arm["exposed"] for arm in data["arms"].values())
    if native:
        inference = native["metrics"]["first_choice_within_budget"]["native_inference"]
        source = (f"Flagsmith {native['flagsmith_version']} · PostgreSQL warehouse. "
                  f"Native relative lift {100*inference['lift']:+.1f}% "
                  f"(interval {100*inference['ci_low']:+.1f}% to {100*inference['ci_high']:+.1f}%).")
        provenance = 'Recorded native platform run'
        raw = '/api/native-results'
        other = '<a href="/results?view=local">View this local run</a>'
    else:
        source = "Local SQLite analysis using the " + ("offline SDK snapshot." if flag.mode() == "offline" else "connected SDK.")
        provenance = 'Current local run'
        raw = '/api/results'
        other = '<a href="/native-results">View the recorded platform run</a>'
    return Template((WEB / "results.html").read_text()).substitute(
        table="".join(table), gap=gap, interval=interval_text, sample=sample, target=data["sampleSize"],
        source=source, provenance=provenance, raw=raw, other=other,
        verdict="met" if data["signal"] else "not met")


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, db_path, **kwargs):
        self.db_path = db_path
        super().__init__(*args, **kwargs)

    def log_message(self, fmt, *args):
        # The checkout stores anonymous assignments only. Console requests omit cookie contents.
        pass

    def send_body(self, status, body, content_type, cookie=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cookie:
            self.send_header("Set-Cookie", f"{COOKIE}={cookie}; Path=/; HttpOnly; SameSite=Lax")
        self.end_headers()
        self.wfile.write(body)

    def json_response(self, payload, status=200, cookie=None):
        self.send_body(status, json.dumps(payload), "application/json; charset=utf-8", cookie)

    def visitor(self):
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        value = jar[COOKIE].value if COOKIE in jar else ""
        if len(value) == 40 and all(c in "0123456789abcdef" for c in value):
            return value
        return None

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path in STATIC:
            filename = STATIC[parsed.path]
            return self.send_body(200, (WEB / filename).read_bytes(), mimetypes.guess_type(filename)[0])
        if parsed.path == "/favicon.ico":
            return self.send_body(204, b"", "image/x-icon")
        try:
            with closing(exp.connect(self.db_path)) as db:
                if parsed.path == "/api/visit":
                    existing = self.visitor()
                    demo = parse_qs(parsed.query).get("demo", [None])[0]
                    if demo:
                        if demo not in flag.VARIANTS or flag.mode() != "offline":
                            return self.json_response({"error": "Use an offline guided demonstration."}, 400)
                        row = db.execute("SELECT cohort,variant FROM visits WHERE id=?", (existing,)).fetchone()
                        if row is None or row["cohort"] != "walkthrough" or row["variant"] != demo:
                            existing = None
                    identifier, payload = exp.get_visit(db, existing or secrets.token_hex(20), demo_variant=demo)
                    return self.json_response(payload, cookie=identifier)
                if parsed.path in ("/results", "/native-results", "/api/native-results") and (
                        parsed.path != "/results" or parse_qs(parsed.query).get("view") != ["local"]):
                    native = json.loads((ROOT / "evidence" / "flagsmith-readout.json").read_text())
                    if parsed.path == "/api/native-results":
                        return self.json_response(native)
                    return self.send_body(200, render_results(native["app_readout"], native),
                                          "text/html; charset=utf-8")
                if parsed.path in ("/results", "/api/results"):
                    result = exp.report(db)
                    if parsed.path == "/api/results":
                        return self.json_response(result)
                    return self.send_body(200, render_results(result), "text/html; charset=utf-8")
        except (ValueError, RuntimeError, FlagsmithClientError):
            return self.json_response({"error": "The experiment could not assign a delivery view."}, 503)
        return self.json_response({"error": "Not found."}, 404)

    def do_POST(self):
        if urlsplit(self.path).path != "/api/choose":
            return self.json_response({"error": "Not found."}, 404)
        if self.headers.get_content_type() != "application/json":
            return self.json_response({"error": "Send a JSON choice."}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 2048:
                return self.json_response({"error": "Choice body must be 1 to 2048 bytes."}, 400)
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict) or not isinstance(payload.get("optionId"), str):
                return self.json_response({"error": "Select a delivery method."}, 400)
            with closing(exp.connect(self.db_path)) as db:
                result = exp.choose(db, self.visitor(), payload["optionId"])
            return self.json_response(result)
        except (ValueError, UnicodeDecodeError):
            return self.json_response({"error": "Open the checkout and select a valid method."}, 400)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["serve", "simulate", "report"], default="serve", nargs="?")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--db", type=Path, help="Local SQLite file for this experimental environment")
    args = parser.parse_args()
    db_path = args.db or ROOT / "data" / f"{flag.mode()}.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    exp.initialise(db_path)
    if args.command == "simulate":
        print(json.dumps(exp.simulate(db_path), indent=2))
    elif args.command == "report":
        with closing(exp.connect(db_path)) as db:
            print(json.dumps(exp.report(db), indent=2))
    else:
        with ThreadingHTTPServer((args.host, args.port), partial(Handler, db_path=db_path)) as server:
            print(f"Parcel Math: http://{args.host}:{server.server_port} (Flagsmith {flag.mode()})", flush=True)
            server.serve_forever()


if __name__ == "__main__":
    main()
