from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import http.cookiejar
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from functools import partial

from app import Handler, ThreadingHTTPServer, ROOT
import experiment as exp


class CheckoutTests(unittest.TestCase):
    def setUp(self):
        # A developer may have exported a real environment key before running tests.
        key_patch = patch.object(exp.flag, "KEY", None)
        key_patch.start()
        self.addCleanup(key_patch.stop)
        offline = exp.flag._client()
        self.addCleanup(offline.close)
        client_patch = patch.object(exp.flag, "client", offline)
        client_patch.start()
        self.addCleanup(client_patch.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name)/"test.sqlite"
        exp.initialise(self.db_path)

    def test_sample_is_idempotent_and_walkthroughs_are_excluded(self):
        first = exp.simulate(self.db_path)
        self.assertEqual(first, exp.simulate(self.db_path))
        self.assertEqual(sum(a["exposed"] for a in first["arms"].values()), 600)
        self.assertTrue(all(a["within"] <= a["confirmed"] < a["exposed"] for a in first["arms"].values()))
        with closing(exp.connect(self.db_path)) as db:
            for variant in ("standard", "landed"):
                identity, payload = exp.get_visit(db, "unused", demo_variant=variant)
                self.assertEqual(payload["variant"], variant)
                self.assertEqual(exp.choose(db, identity, "priority")["totalCents"], 3525)
                self.assertFalse(exp.choose(db, identity, "economy")["firstChoice"])
            self.assertEqual(exp.report(db), first)

    def test_published_native_aggregate_matches_both_occurrence_metrics(self):
        data = json.loads((ROOT/"evidence"/"flagsmith-readout.json").read_text())
        arms = data["app_readout"]["arms"]
        self.assertEqual(data["excluded_identities"], 0)
        for native, app in (("control", "standard"), ("landed", "landed")):
            self.assertEqual(data["exposed"][native], arms[app]["exposed"])
            for metric, count in (("first_choice_within_budget","within"), ("shipping_option_confirmed","confirmed")):
                result = data["metrics"][metric]["arms"][native]
                self.assertEqual(result, {"exposed": arms[app]["exposed"], "converted": arms[app][count]})
        self.assertEqual(data["event_counts"]["$flag_exposure"], 600)

    def test_concurrent_first_confirmation(self):
        with closing(exp.connect(self.db_path)) as db:
            exp.get_visit(db, "concurrent")
        def submit(option):
            with closing(exp.connect(self.db_path)) as db:
                return exp.choose(db, "concurrent", option)
        with ThreadPoolExecutor(2) as pool:
            first, second = pool.map(submit, ("economy", "express"))
        self.assertEqual(sum(result["firstChoice"] for result in (first, second)), 1)
        with closing(exp.connect(self.db_path)) as db:
            _, resumed = exp.get_visit(db, "concurrent")
            self.assertEqual(resumed["result"]["optionId"], first["optionId"] if first["firstChoice"] else second["optionId"])

    def test_checkout_http_and_persisted_budget_choice(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, db_path=self.db_path))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        base = "http://127.0.0.1:" + str(server.server_port)
        browser = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                              urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        def get(path):
            with browser.open(base+path) as response:
                return json.load(response)
        def choose(option):
            request = urllib.request.Request(base+"/api/choose", data=json.dumps({"optionId":option}).encode(),
                                             headers={"Content-Type":"application/json"})
            with browser.open(request) as response:
                return json.load(response)
        for variant in ("standard", "landed"):
            with browser.open(base+"/?demo="+variant) as page:
                self.assertIn(b"Parcel Math", page.read())
            checkout = get("/api/visit?demo="+variant)
            self.assertEqual(checkout["variant"], variant)
            self.assertFalse(checkout["complete"])
            self.assertEqual(choose("priority"), dict(totalCents=3525, withinBudget=False,
                                                     firstChoice=True, optionId="priority"))
            self.assertTrue(choose("economy")["withinBudget"])
            self.assertEqual(get("/api/visit")["result"]["optionId"], "priority")
        with self.assertRaises(urllib.error.HTTPError) as error:
            choose("wrong")
        self.assertEqual(error.exception.code, 400)
        self.assertEqual(get("/api/results")["arms"]["standard"]["exposed"], 0)
        self.assertEqual(get("/api/native-results")["exposed"], {"control": 303, "landed": 297})
        with browser.open(base+"/results") as page:
            self.assertIn(b"Recorded native platform run", page.read())
        with browser.open(base+"/results?view=local") as page:
            self.assertIn(b"Current local run", page.read())
