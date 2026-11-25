"""The checkout experiment and its fixed-size synthetic reference run."""
from contextlib import closing
import hashlib
import math
import random
import secrets
import sqlite3

import flagsmith_bridge as flag

OPTIONS = (("economy", "Economy", 5), ("priority", "Priority", 3), ("express", "Express", 1))
# Item, budget, shipping fees. Prices are integer euro cents.
BASKETS = (
    (3080, 3500, (195, 445, 695)),
    (1960, 2400, (175, 465, 695)),
    (4150, 4700, (205, 385, 575)),
)
SAMPLE_SIZE = 600
COHORT = "simulated-v1"
SEED = 2601126
SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
    id TEXT PRIMARY KEY,
    cohort TEXT NOT NULL,
    variant TEXT NOT NULL CHECK (variant IN ('standard','landed')),
    basket INTEGER NOT NULL,
    first_option TEXT
);
"""

def connect(path):
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    return db

def initialise(path):
    with closing(connect(path)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)

def basket_for(identity):
    digest = hashlib.sha256(("basket/" + identity).encode()).digest()
    return int.from_bytes(digest[:8], "big") % len(BASKETS)

def scenario(basket):
    item, budget, fees = BASKETS[basket]
    options = [dict(id=code, label=name, days=days, feeCents=fee)
               for (code, name, days), fee in zip(OPTIONS, fees)]
    return dict(itemCents=item, budgetCents=budget, options=options)

def choice_result(basket, option_id, first_choice):
    values = scenario(basket)
    selected = next((option for option in values["options"] if option["id"] == option_id), None)
    if selected is None:
        raise ValueError("Choose one of the three delivery methods.")
    total = values["itemCents"] + selected["feeCents"]
    return dict(totalCents=total, withinBudget=total <= values["budgetCents"],
                firstChoice=first_choice, optionId=option_id)

def get_visit(db, identity, cohort="browser", demo_variant=None):
    """Issue one stable assignment per identity, even after reloads or concurrent opens."""
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("SELECT * FROM visits WHERE id=?", (identity,)).fetchone()
        if row is None:
            if demo_variant:
                if flag.mode() != "offline":
                    raise ValueError("Guided demonstrations use the offline experiment.")
                # Find a real SDK assignment for the requested walkthrough. No variant override.
                for _ in range(128):
                    identity = secrets.token_hex(20)
                    variant = flag.assign(identity)
                    if variant == demo_variant:
                        break
                else:
                    raise RuntimeError("Requested variant was unavailable in the demo environment.")
                cohort, basket = "walkthrough", 0
            else:
                variant, basket = flag.assign(identity), basket_for(identity)
            db.execute("INSERT INTO visits (id,cohort,variant,basket) VALUES (?,?,?,?)",
                       (identity, cohort, variant, basket))
            row = db.execute("SELECT * FROM visits WHERE id=?", (identity,)).fetchone()
        db.commit()
    except Exception:
        db.rollback()
        raise
    payload = dict(variant=row["variant"], scenario=scenario(row["basket"]),
                   complete=row["first_option"] is not None)
    if payload["complete"]:
        payload["result"] = choice_result(row["basket"], row["first_option"], True)
    return identity, payload

def choose(db, identity, option_id):
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("SELECT * FROM visits WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise ValueError("Open the checkout before choosing a delivery method.")
        first = row["first_option"] is None
        result = choice_result(row["basket"], option_id, first)
        if first:
            db.execute("UPDATE visits SET first_option=? WHERE id=?", (option_id, identity))
        db.commit()
    except Exception:
        db.rollback()
        raise
    if first and row["cohort"] != "walkthrough":
        properties = {"cohort": row["cohort"], "method": option_id}
        flag.record_event(identity, "shipping_option_confirmed", properties)
        if result["withinBudget"]:
            flag.record_event(identity, "first_choice_within_budget", properties)
    return result

def model_choice(payload, rng):
    """Apply the same decision policy to the information visible on each screen."""
    if rng.random() < 0.08:
        return None
    scenario_data = payload["scenario"]
    fastest_first = sorted(scenario_data["options"], key=lambda option: option["days"])
    if rng.random() < 0.10:
        return fastest_first[0]["id"]
    estimates = rng.random() >= 0.60
    item = scenario_data["itemCents"]
    for option in fastest_first:
        fee = option["feeCents"]
        if estimates and payload["variant"] == "standard":
            # Round the two addends to the nearest euro before adding.
            perceived = 100 * ((item + 50) // 100 + (fee + 50) // 100)
        else:
            perceived = item + fee
        if perceived <= scenario_data["budgetCents"]:
            return option["id"]
    return fastest_first[-1]["id"]

def simulate(path):
    """Replays never rerandomize or count a conversion twice."""
    rng = random.Random(SEED)
    with closing(connect(path)) as db:
        for n in range(SAMPLE_SIZE):
            identity = f"parcel-math-sim-v1-{n:04}"
            _, payload = get_visit(db, identity, COHORT)
            option = model_choice(payload, rng)
            if option is not None:
                choose(db, identity, option)
        return report(db)

def wilson(successes, total):
    z = 1.959963984540054
    prop = successes / total
    denom = 1 + z*z/total
    centre = (prop + z*z/(2*total)) / denom
    radius = z * math.sqrt(prop*(1-prop)/total + z*z/(4*total*total)) / denom
    return centre-radius, centre+radius

def report(db):
    arms = {v: dict(exposed=0, confirmed=0, within=0) for v in ("standard", "landed")}
    for row in db.execute("SELECT * FROM visits WHERE cohort=?", (COHORT,)):
        arm = arms[row["variant"]]
        arm["exposed"] += 1
        if row["first_option"] is not None:
            arm["confirmed"] += 1
            arm["within"] += choice_result(row["basket"], row["first_option"], True)["withinBudget"]
    output = dict(source=COHORT, arms=arms, sampleSize=SAMPLE_SIZE, delta=None, interval=None, signal=False)
    a, b = arms.values()
    if a["exposed"] and b["exposed"]:
        pa, pb = a["within"]/a["exposed"], b["within"]/b["exposed"]
        la, ua = wilson(a["within"], a["exposed"])
        lb, ub = wilson(b["within"], b["exposed"])
        delta = pb-pa
        lower = delta - math.hypot(pb-lb, ua-pa)
        upper = delta + math.hypot(ub-pb, pa-la)
        output.update(delta=delta, interval=[lower, upper],
                      signal=sum(arm["exposed"] for arm in arms.values()) == SAMPLE_SIZE
                             and delta >= 0.05 and lower > 0)
    return output
