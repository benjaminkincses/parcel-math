# Parcel Math

Can a shopper see whether the fastest delivery fits their budget before selecting it? This checkout compares shipping fees with all-in prices on the same three delivery methods. No payments are taken.

## Run locally

Requires Python 3.11 or later. From the project folder:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python app.py simulate
python app.py --port 8090
```

Open <http://127.0.0.1:8090/> for the checkout or <http://127.0.0.1:8090/results> for the recorded native platform run. <http://127.0.0.1:8090/results?view=local> shows the fresh local replay. Return visits keep their assignment. The two offline walkthrough links below find real SDK assignments for the same €30.80 basket and €35.00 budget. Walkthroughs do not affect the experiment counts.

- [Shipping fees](http://127.0.0.1:8090/?demo=standard)
- [Order totals](http://127.0.0.1:8090/?demo=landed)

```sh
python -m unittest discover -s tests -v
python app.py report
```

## Working demo

The [checkout walkthrough](demo/parcel-math.mp4) shows both interfaces using the offline SDK snapshot, followed by results from the separate server-connected experiment. To record the app again, run `python demo/record.py --help` for its options. The recorder uses Chromium, Playwright, Pillow and ffmpeg.

## What the experiment measured

We predeclared the first confirmed within-budget choice as the primary outcome. Its denominator is all exposed identities, including simulated shoppers who leave. The guardrail is confirmation of any first choice. Revisits, retries and alternate choices do not add conversions. The [experiment plan](EXPERIMENT.md) includes the shopper model and analysis method.

The [official Flagsmith Python SDK](https://github.com/Flagsmith/flagsmith-python-client) evaluates `checkout_price_display`. A checked-in, two-variation environment snapshot makes local runs reproducible. The app never chooses its own A/B bucket. Previewing a guided arm looks for an identity that the SDK genuinely assigns to it.

### Recorded native Flagsmith run

The application ran the fixed synthetic population against self-hosted Flagsmith 2.290.0 and its PostgreSQL 16.2 warehouse. The results API and raw events matched the app's ledger. The [aggregate export](evidence/flagsmith-readout.json) records the native experiment configuration, exposure and occurrence counts, and the server's statistical output. The [native Flagsmith dashboard](evidence/flagsmith-dashboard.png) shows both occurrence rates and relative lift. No real shoppers participated.

| Display | Exposed | Confirmed | Within budget on first choice | Rate per exposure |
| --- | ---: | ---: | ---: | ---: |
| Shipping fee | 303 | 279 | 220 | 72.6% |
| Full order total | 297 | 275 | 251 | 84.5% |

The primary outcome rose **11.9 percentage points** in this simulation (95% Newcombe interval +5.4 to +18.3 points). Flagsmith reported 16.4% relative lift. The completion guardrail was 92.1% versus 92.6%. All 600 exposures were present in the warehouse, with no excluded identities.

The fixed simulation includes shoppers who estimate whole euros when adding two amounts and shoppers who leave. It does not model revising a choice after previewing the exact total. The outcomes reflect programmed behavior and cannot establish a customer conversion effect.

### Offline reproduction

With the included flag snapshot, the same 600 scripted identities produce 208/280 within budget for shipping fees and 271/320 for order totals. The two environments have different flag-state identifiers, which changes how Flagsmith assigns these identities. The offline report reads the local SQLite visit ledger. The two runs are separate and their counts should never be pooled.

## Connect Flagsmith Experimentation

Use a dedicated empty experimental environment so test identities and customer traffic stay separate. A local, open-source Flagsmith installation can store events in its own PostgreSQL database; enable `EXPERIMENTATION_ENABLED=true` on the API and choose **Flagsmith database** under the environment's Warehouse tab. The [self-host guide](https://docs.flagsmith.com/experimentation/self-hosting) covers these settings.

1. Create and enable the multivariate flag `checkout_price_display` with the default value `standard`. Add one treatment option, key and value `landed`. The rest of the allocation takes the default value and Flagsmith records it under the reserved control key.
2. Create an **Occurrence** metric for `first_choice_within_budget`, direction higher is better. Add an **Occurrence** metric for `shipping_option_confirmed` to monitor confirmation.
3. Create and start an experiment on the flag: 100% traffic allocation, 50% on the treatment and 50% retained for the default control, the budget metric primary, and confirmation secondary. Open the environment's warehouse card and copy its events URL.
4. In a terminal, set your own URLs and environment key. The URLs below are examples for a local Flagsmith service. Keep the key out of version control:

```sh
export FLAGSMITH_API_URL=http://127.0.0.1:8000/api/v1/
export FLAGSMITH_EVENTS_URL=http://127.0.0.1:8000/api/
read -rs -p 'Flagsmith environment key: ' FLAGSMITH_ENVIRONMENT_KEY
export FLAGSMITH_ENVIRONMENT_KEY
python app.py simulate --db data/first-live-run.sqlite
python app.py --db data/first-live-run.sqlite
```

The live SDK calls `get_experiment_flag` for the first exposure and `track_event` for confirmed outcomes using the same opaque identity. It flushes the event batch when the process exits normally. In the warehouse, inspect exposures and the two occurrence metrics by variation. Actual variant counts may differ from the offline snapshot because flag-state identifiers affect assignment. Use a fresh local database after changing environments or experiments. Keep the same database when retrying a run.

To independently read an existing local experiment, [evidence/read_flagsmith.py](evidence/read_flagsmith.py) fetches the experiment, exposure histogram and metric results with a read-capable management token. Its module docstring lists the environment variables.

The SDK transport test uses a loopback HTTP fixture to check the real SDK's exposure and conversion payloads. It does not emulate warehouse aggregation. [Official instrumentation guide](https://docs.flagsmith.com/experimentation/run-an-experiment).
