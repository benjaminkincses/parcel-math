"""Read the native dashboard aggregates for a local Flagsmith experiment.

Set FLAGSMITH_API_URL to the local API's /api/v1/ base, FLAGSMITH_ENVIRONMENT_KEY
to its environment key, FLAGSMITH_ADMIN_TOKEN to a management user token with
view access, and FLAGSMITH_EXPERIMENT_ID to the experiment's numeric ID. Run
python evidence/read_flagsmith.py after refreshing results and exposures in
Flagsmith. The command prints only experiment metadata and aggregate counts.
"""

import json
import os
from urllib.parse import quote, urlsplit

import requests


def main():
    base = os.environ["FLAGSMITH_API_URL"].rstrip("/") + "/"
    if urlsplit(base).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit("Use the API URL of a local Flagsmith instance.")
    key = quote(os.environ["FLAGSMITH_ENVIRONMENT_KEY"], safe="")
    study = int(os.environ["FLAGSMITH_EXPERIMENT_ID"])
    url = f"{base}environments/{key}/experiments/{study}/"
    auth = {"Authorization": "Token " + os.environ["FLAGSMITH_ADMIN_TOKEN"]}
    with requests.Session() as session:
        def read(part):
            response = session.get(url + part, headers=auth, timeout=10, allow_redirects=False)
            if response.status_code != 200:
                raise SystemExit(f"Flagsmith returned HTTP {response.status_code} for {part or 'detail'}.")
            return response.json()

        detail = read("")
        results = read("results/")["results"]
        exposures = read("exposures/")["exposures"]
    if not (results and results.get("payload") and exposures and exposures.get("payload")):
        raise SystemExit("Refresh the experiment's results and exposures in Flagsmith first.")
    names = {metric["metric"]: metric["metric_name"] for metric in detail["metrics"]}
    metrics = {
        names[item["metric_id"]]: item["variants"]
        for item in results["payload"]["metrics"]
    }
    print(json.dumps({
        "experiment": detail["name"],
        "status": detail["status"],
        "as_of": results["as_of"],
        "exposures": exposures["payload"],
        "metric_aggregates": metrics,
    }, indent=2))


if __name__ == "__main__":
    main()
