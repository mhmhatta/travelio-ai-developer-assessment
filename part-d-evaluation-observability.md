# Part D - Evaluation and Observability

## 1. Evaluation set

I would begin with 1,000 privacy-reviewed and de-identified messages:

- 600 stratified random samples from real production traffic. This preserves
  natural language, typos, code-switching, message length, and class mix.
- 250 targeted samples for rare intents and safety-sensitive slices, especially
  urgent maintenance, ambiguous payment questions, and unknown cases.
- 150 hard cases: prompt injection, conflicting conversation context, relative
  dates, unsupported unit types, mixed intent, and very short messages.

The initial split would be 600 development examples, 200 regression examples,
and 200 final holdout examples. The 200-example regression set becomes a
versioned golden set: two trained annotators label it independently using a
written guide, and a third person adjudicates disagreements. I would track
inter-annotator agreement because ambiguous labels cap achievable model
performance; persistent disagreement means the taxonomy or policy needs work,
not just the prompt.

Rare classes must be oversampled so their confidence intervals are useful.
However, I would report both macro metrics on the balanced evaluation set and
prevalence-weighted metrics using the real production distribution. This avoids
both failure modes: hiding rare-intent errors and overstating their traffic
impact.

New production failures and human overrides enter a review queue. Confirmed
examples can join future development sets, but a frozen regression version is
never edited in place. Guest text requires access control, retention limits,
de-identification, and privacy approval before labeling.

## 2. Metrics

### Routing quality

- Precision, recall, and F1 for every intent.
- Macro F1 so each intent has equal influence.
- Prevalence-weighted F1 to estimate traffic-wide impact.
- Confusion matrix, inspected by language and ambiguity slice.
- Unsafe auto-route rate: incorrect results where `needs_human=false`.
- High-urgency false-negative rate, because missing an urgent maintenance issue
  costs more than escalating a benign one.

### Extraction quality

- Exact match and field-level precision/recall for location and unit type.
- Exact match for ISO date value and date kind.
- Urgency macro F1 and high-urgency recall.
- Whole-object exact match as a strict end-to-end signal, not the only score.

### Reliability and operations

- JSON/Pydantic validation failure rate.
- Retry and exhausted-retry rates by failure category.
- Human-escalation rate and false-escalation rate.
- p50, p95, and p99 latency.
- Provider token and cost estimates when replacing the mock client.

Overall accuracy is misleading because common booking inquiries can dominate
the score. A model that predicts `booking_inquiry` for nearly everything may
look accurate while failing every rare extension or urgent maintenance case.
Accuracy also treats a harmless human escalation and an unsafe missed emergency
as equally wrong, although their business costs are very different.

Confidence is not accuracy unless calibrated against labeled outcomes. I would
measure expected calibration error and reliability curves before using a
confidence threshold as more than a routing heuristic.

## 3. Regression process

Every result stores prompt version, schema version, model version, and runtime
configuration. A prompt or model candidate runs against the same frozen golden
set and slice definitions as the current production version.

A candidate must meet these release gates:

- No regression in high-urgency recall.
- No per-intent F1 decrease greater than 2 percentage points.
- Macro F1 does not decrease.
- Unsafe auto-route rate does not increase.
- Invalid-output rate stays below 0.5%.
- p95 latency remains within the agreed service-level objective.

I would review changed predictions, not only aggregate metrics. This catches a
candidate that improves ten easy examples while breaking one severe case.
Passing candidates run in shadow mode on current traffic, then a 5% canary with
automatic rollback thresholds. One change per experiment keeps causality clear.

The holdout set is opened only for release decisions. Repeated tuning against
it would turn it into another development set and make the estimate optimistic.

## 4. Production monitoring

### Immediate service signals

- Request volume and HTTP status rate.
- Timeout, malformed-output, unknown-intent, retry, and exhausted-retry rates.
- Repository failures.
- p50, p95, and p99 latency by prompt/model version.
- Human-escalation and low-confidence rates.

These detect provider, schema, and infrastructure problems within minutes. An
alert should compare both an absolute threshold and a recent baseline so low
traffic does not create noisy percentages.

### Input and output drift

- Intent and urgency distributions by day.
- Language mix, message length, context length, and missing-context rates.
- Confidence distribution and calibration drift.
- Entity presence and null rates by field.
- Population stability index or another simple drift score for stable numeric
  features, backed by sample review rather than treated as proof.

Changes may be legitimate seasonality or campaigns, so drift triggers diagnosis,
not an automatic model rollback.

### Delayed quality signals

Join predictions to human overrides, final support queue, maintenance priority,
and resolved ticket category. Monitor disagreement and unsafe auto-route rates
by intent, language, property, and prompt/model version. Sample a fixed number
of non-escalated messages for regular audit; reviewing only escalations creates
selection bias and misses confidently wrong automation.

Dashboards must never contain raw guest messages. They use counts, rates,
latency, version identifiers, and de-identified slice metadata. Raw-text review
belongs in a restricted workflow with explicit retention and access policies.

