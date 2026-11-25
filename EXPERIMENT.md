# Parcel Math experiment plan

Written before the reference run. One basket, three delivery methods and a spending cap. A shopper wants the fastest delivery they can afford. The product question is whether showing the amount payable next to each method helps them stay within that cap on their first choice.

## Design

- Randomization unit: one browser identity. Flagsmith assigns the two values of the multivariate flag `checkout_price_display` at equal weights and keeps an identity's assignment stable. Browser sessions use a random opaque cookie.
- Control (`standard`): show the shipping price on each method. Treatment (`landed`): show basket plus shipping on each method. The running review panel shows the order total after selection in both arms. The item, budget, options, order and interaction are otherwise identical.
- Primary metric: unique exposed identities whose first confirmed choice fits the cap, divided by all unique exposed identities. Define the Flagsmith metric as the percentage of exposed identities with a `first_choice_within_budget` event. Abandonments count as unsuccessful. Later changes never rewrite the primary outcome.
- Guardrail: count unique identities that confirmed any choice, using the `shipping_option_confirmed` event. A higher primary rate caused by missing events is not sufficient evidence.
- Readout: one fixed run of 600 synthetic shopper identities, split by the flag. Compare treatment minus control in percentage points with a two-sided 95% Newcombe interval from two independent Wilson intervals. Predeclared signal: at least five percentage points of improvement with the lower bound above zero. An imbalance or missing conversions calls for investigation. No early stopping or alternative primary metric.
- The fixed scenario set has three baskets. Assignment and scenario selection use separate calculations. Each basket has an affordable and an over-budget delivery method. The two decision styles below apply to every basket.

## Synthetic shopper model

The simulator is a test of the mechanism, not customer research. Its seeded choices deliberately include shoppers who estimate cents. In either arm 8% of simulated visits abandon and 10% of the remaining ones choose the fastest method regardless of budget. Of the rest, 60% use exact arithmetic; the remainder compare whole-euro estimates for any values that must be added. When a total is displayed these shoppers compare it directly against the cap. All budget-aware shoppers choose the fastest qualifying method. A shopper selects once. There is no variant-specific probability of success.

This design predicts an advantage for visible totals by construction. A positive result validates delivery of the variants and measurement under the stated policy. It does not estimate an effect on real shoppers or justify a rollout. A follow-up with consenting real shoppers would need its own sample-size calculation, stopping rule, privacy review and separate environment.

Both interfaces preview the exact total on selection. The scripted decision ends at confirmation and does not model reconsideration after reading that preview. Someone who checks the preview and revises before confirming could perform equally well with either display.
