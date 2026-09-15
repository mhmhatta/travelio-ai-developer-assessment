# Part C - Databases and Data Debugging

## C1 - MySQL

```sql
SELECT
    property_type,
    currency,
    AVG(
        total_amount
        / NULLIF(DATEDIFF(checkout_date, checkin_date), 0)
    ) AS average_nightly_revenue
FROM bookings
WHERE status = 'completed'
  AND created_at >= UTC_TIMESTAMP() - INTERVAL 90 DAY
  AND checkout_date > checkin_date
GROUP BY
    property_type,
    currency
ORDER BY
    property_type,
    currency;
```

Assumptions:

- “Average nightly revenue” means the average of each booking's nightly rate:
  `AVG(total_amount / nights)`. `SUM(total_amount) / SUM(nights)` would instead
  be a nights-weighted realized rate.
- The query groups by currency because adding or averaging IDR and USD directly
  is invalid. A single-currency result requires an effective-dated FX table and
  an explicit reporting currency.
- `checkout_date > checkin_date` and `NULLIF` prevent zero- or negative-night
  bookings from corrupting the denominator.
- “Created in the last 90 days” is a rolling 90-day UTC window, as requested;
  it is not a filter on stay dates.

## C2 - MongoDB

This version means the seven UTC calendar days including today. A rolling
168-hour window would instead use `new Date(Date.now() - 7 * 24 * 60 * 60 *
1000)`.

```javascript
const start = new Date();
start.setUTCHours(0, 0, 0, 0);
start.setUTCDate(start.getUTCDate() - 6);

db.messages.aggregate([
  {
    $match: {
      created_at: { $gte: start }
    }
  },
  {
    $group: {
      _id: {
        day: {
          $dateTrunc: {
            date: "$created_at",
            unit: "day",
            timezone: "UTC"
          }
        },
        intent: "$intent"
      },
      message_count: { $sum: 1 }
    }
  },
  {
    $project: {
      _id: 0,
      day: "$_id.day",
      intent: "$_id.intent",
      message_count: 1
    }
  },
  {
    $sort: {
      day: 1,
      intent: 1
    }
  }
]);
```

An index on `{ created_at: 1 }` supports the initial time-range filter. If this
aggregation is a frequent operational query, `{ created_at: 1, intent: 1 }`
may help coverage, subject to measurement against real cardinality and working
set size.

## C3 - GMV root-cause analysis

I would first confirm that this is a value problem rather than a reporting
filter or row-volume problem. This baseline isolates the discontinuity by day,
source, and currency:

```sql
SELECT
    DATE(created_at) AS booking_day,
    source,
    currency,
    COUNT(*) AS booking_count,
    SUM(total_amount) AS gmv,
    AVG(total_amount) AS average_booking_value,
    SUM(total_amount)
        / NULLIF(SUM(DATEDIFF(checkout_date, checkin_date)), 0)
        AS realized_revenue_per_night,
    AVG(DATEDIFF(checkout_date, checkin_date)) AS average_nights
FROM bookings
WHERE created_at >= UTC_DATE() - INTERVAL 21 DAY
GROUP BY
    DATE(created_at),
    source,
    currency
ORDER BY
    booking_day,
    source,
    currency;
```

### 1. Wrong amount scale or currency mapping for the new partner

The ingestion may store cents instead of major units, USD as IDR, or another
scaled value. That produces normal row counts and an immediate GMV drop at the
new ingestion boundary.

Confirm or kill:

```sql
SELECT
    source,
    currency,
    COUNT(*) AS booking_count,
    SUM(total_amount = 0) AS zero_amount_count,
    MIN(total_amount) AS minimum_amount,
    AVG(total_amount) AS average_amount,
    MAX(total_amount) AS maximum_amount,
    AVG(
        total_amount
        / NULLIF(DATEDIFF(checkout_date, checkin_date), 0)
    ) AS average_nightly_amount
FROM bookings
WHERE created_at >= UTC_DATE() - INTERVAL 21 DAY
  AND status = 'completed'
GROUP BY
    source,
    currency
ORDER BY
    source,
    currency;
```

Compare `partner_x` ratios against direct and OTA bookings for the same
currency, property type, and stay length. Ratios near `0.01`, `100`, or a
currency exchange rate are strong evidence. Then reconcile at least 20 raw
partner payloads and settlement amounts to stored `total_amount` and
`currency`; matching units and currencies kill this hypothesis.

### 2. The partner's “amount” means nightly or net value, not gross stay value

The new mapping may copy a per-night, post-commission, or post-discount field
into `total_amount`. Counts remain correct, but longer partner stays become
systematically undervalued.

Confirm or kill:

```sql
SELECT
    source,
    DATEDIFF(checkout_date, checkin_date) AS nights,
    COUNT(*) AS booking_count,
    AVG(total_amount) AS average_stored_amount,
    AVG(
        total_amount
        / NULLIF(DATEDIFF(checkout_date, checkin_date), 0)
    ) AS average_stored_nightly_amount
FROM bookings
WHERE created_at >= UTC_DATE() - INTERVAL 21 DAY
  AND status = 'completed'
  AND checkout_date > checkin_date
GROUP BY
    source,
    DATEDIFF(checkout_date, checkin_date)
ORDER BY
    source,
    nights;
```

If `partner_x.total_amount` stays almost flat as nights increase, the field is
probably nightly rather than stay-level. Inspect the partner contract and raw
payload field names (`gross`, `net`, `nightly`, taxes, fees, commission), then
recompute expected gross values for a sample. Agreement with stored gross
totals kills this hypothesis.

### 3. A real channel-mix shift lowered booking value

Partner bookings may replace direct/OTA volume with shorter stays, cheaper
property types, or deeper discounts. In that case the GMV drop is real rather
than a pipeline defect.

Confirm or kill:

```sql
SELECT
    DATE(created_at) AS booking_day,
    source,
    property_type,
    currency,
    DATEDIFF(checkout_date, checkin_date) AS nights,
    COUNT(*) AS booking_count,
    AVG(total_amount) AS average_booking_value,
    AVG(
        total_amount
        / NULLIF(DATEDIFF(checkout_date, checkin_date), 0)
    ) AS average_nightly_value
FROM bookings
WHERE created_at >= UTC_DATE() - INTERVAL 21 DAY
  AND status = 'completed'
  AND checkout_date > checkin_date
GROUP BY
    DATE(created_at),
    source,
    property_type,
    currency,
    DATEDIFF(checkout_date, checkin_date)
ORDER BY
    booking_day,
    source,
    property_type,
    nights;
```

Reweight post-Tuesday rows to the pre-Tuesday mix of source, property type,
currency, and stay length. If like-for-like nightly values are stable and the
40% drop is explained by mix, this hypothesis survives. If comparable cohorts
also drop sharply, kill it and return to ingestion semantics.

### Most likely root cause

Hypothesis 1 is most likely: `partner_x` amount scale or currency is mapped
incorrectly. Timing aligns exactly with a new ingestion boundary, while normal
booking volume says rows still arrive. I would pause partner GMV publication,
reconcile raw payloads to stored rows, correct the mapping, and idempotently
backfill affected bookings before re-enabling the report.

## C4 - ClickHouse bonus

The query becomes slow because the table is sorted only by `id`, while the query filters by `event_type` and groups by `created_at`.

As the table grows, ClickHouse cannot efficiently skip enough data for this query, so it has to scan more rows.

For this reporting use case, I would create a new table whose sort key matches the query pattern better:

```sql
CREATE TABLE events_v2
(
    id UInt64,
    event_type LowCardinality(String),
    created_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (event_type, created_at, id);
```

This makes queries that filter by `event_type` and time range more efficient.

For example:

```sql
SELECT
    toDate(created_at) AS day,
    count() AS event_count
FROM events_v2
WHERE event_type = 'booking'
  AND created_at >= now('UTC') - INTERVAL 90 DAY
GROUP BY day
ORDER BY day;
```

I would create and backfill a new table instead of trying to change the existing sort key directly.

If this daily report is queried very often, I would also consider storing a pre-aggregated daily result so the dashboard does not need to scan the raw events table every time.
