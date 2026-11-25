"""SDK integration checks. The loopback fixture observes the HTTP protocol, not a warehouse."""

import json
import os
import threading
import unittest
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import flagsmith_bridge as bridge


class FlagsmithSDKTests(unittest.TestCase):
    def test_offline_assignment_is_stable_and_uses_both_arms(self):
        with patch.object(bridge, "KEY", None), patch.object(bridge, "client", bridge._client()):
            self.assertEqual(bridge.mode(), "offline")
            first = [bridge.assign(f"synthetic-{i}") for i in range(1000)]
            self.assertEqual(first, [bridge.assign(f"synthetic-{i}") for i in range(1000)])
            self.assertEqual(Counter(first), {"standard": 515, "landed": 485})
            self.assertFalse(bridge.record_event("synthetic-0", "first_choice_within_budget"))

    def test_live_sdk_sends_exposure_and_outcome_to_loopback(self):
        requests = []

        class Fixture(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append((self.path, self.headers["X-Environment-Key"], payload))
                # The real server returns this shape when the identity participates.
                flag = {
                    "enabled": True,
                    "feature_state_value": "landed",
                    "feature": {"id": 1, "name": bridge.FLAG},
                    "variant": "landed",
                    "metadata": {"experiment": {"id": 7, "name": "Demo", "in_experiment": True}},
                }
                response = {"flags": [flag]} if self.path.endswith("/identities/") else {}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())

            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), Fixture) as server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.shutdown)
            base = f"http://127.0.0.1:{server.server_port}/api/"
            endpoints = {"FLAGSMITH_API_URL": base + "v1/", "FLAGSMITH_EVENTS_URL": base}
            with patch.dict(os.environ, endpoints), patch.object(bridge, "KEY", "fixture-key"):
                with patch.object(bridge, "client", bridge._client()):
                    try:
                        self.assertEqual(bridge.assign("visitor"), "landed")
                        self.assertTrue(bridge.record_event("visitor", "first_choice_within_budget", {"value": 1}))
                    finally:
                        bridge.client.close()
            server.shutdown()
        self.assertEqual([path for path, _, _ in requests], ["/api/v1/identities/", "/api/v1/events"])
        self.assertTrue(all(key == "fixture-key" for _, key, _ in requests))
        exposure, outcome = requests[1][2]["events"]
        self.assertEqual((exposure["event"], exposure["value"]), ("$flag_exposure", "landed"))
        self.assertEqual(exposure["metadata"]["experiment_id"], 7)
        self.assertEqual((outcome["event"], outcome["value"]), ("first_choice_within_budget", "1"))
        self.assertEqual(exposure["identifier"], outcome["identifier"])
