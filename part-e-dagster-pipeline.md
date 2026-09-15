# Part E - Daily Dagster Pipeline Design

The pipeline runs once per day and processes one UTC day at a time:

```text
Yesterday's bookings
        ↓
Validate upstream data
        ↓
Categorize each booking with the LLM
        ↓
Load successful rows to ClickHouse
        ↓
Store failed rows separately for retry/debugging
```

I would model the pipeline as daily-partitioned Dagster assets:

```text
raw_bookings
      ↓
validated_bookings
      ↓
categorized_bookings
     ↙          ↘
successful      failed
bookings        bookings
    ↓               ↓
ClickHouse       quarantine
```

## (a) Assets and daily partitioning

I would use a `DailyPartitionsDefinition` in UTC so each run represents one calendar day.

```python
from dagster import DailyPartitionsDefinition

daily_partitions = DailyPartitionsDefinition(
    start_date="2026-01-01",
    timezone="UTC",
)
```

For a partition such as `2026-09-14`, the ingestion step reads bookings using a half-open interval:

```text
2026-09-14 00:00:00 UTC <= created_at < 2026-09-15 00:00:00 UTC
```

This avoids overlapping records between adjacent days.

The main assets are:

- `raw_bookings`: read the selected day's bookings from MySQL.
- `validated_bookings`: validate schema and business rules before any LLM call.
- `categorized_bookings`: run the LLM categorizer for each valid booking.
- `clickhouse_bookings`: publish successful results for reporting.
- `rejected_bookings`: store failed LLM rows or invalid records for investigation and retry.

Example ingestion pseudocode:

```python
@asset(partitions_def=daily_partitions)
def raw_bookings(context, mysql):
    window = context.partition_time_window

    return mysql.fetch_all(
        """
        SELECT
            id,
            property_id,
            property_type,
            checkin_date,
            checkout_date,
            status,
            total_amount,
            currency,
            source,
            created_at
        FROM bookings
        WHERE created_at >= :start
          AND created_at < :end
        """,
        {
            "start": window.start,
            "end": window.end,
        },
    )
```

I would select explicit columns instead of `SELECT *`, so upstream schema changes do not silently change the pipeline input.

## (b) Idempotency

Re-running yesterday's partition must not create duplicate ClickHouse rows.

I would write each run to a staging area first, validate it, then replace the target day's partition atomically.

```text
process 2026-09-14
        ↓
write to staging
        ↓
validate staging rows
        ↓
replace ClickHouse partition 2026-09-14
```

If the same date is rerun, the new valid partition replaces the previous one instead of appending duplicate rows.

The logical key is:

```text
partition_date + booking_id
```

A failed run never updates the visible reporting table because publication only happens after validation succeeds.

I would also reuse successful LLM results when the booking input and prompt version have not changed, using a cache key such as:

```text
booking_id + source_fingerprint + prompt_version
```

This avoids paying for the same LLM work again during a rerun.

## (c) Partial LLM failure

The LLM step should handle failures per row instead of failing the whole daily batch.

Each booking gets either a successful classification or a structured failure result:

```json
{
  "booking_id": 124,
  "categorization_status": "failed",
  "error_code": "llm_timeout",
  "attempt_count": 3,
  "prompt_version": "v1"
}
```

If 5% of LLM calls fail:

```text
95% successful rows
        ↓
publish to ClickHouse

5% failed rows
        ↓
write to quarantine
        ↓
retry or investigate separately
```

The successful 95% should not be discarded because of row-local failures.

I would record metrics such as total rows, successful rows, failed rows, retry count, and completion rate. As an initial operating rule, a small failure rate such as 5% is allowed to publish, while a much larger failure rate, for example above 10%, blocks publication because it is more likely to indicate a systemic issue. The threshold should later be tuned from production history and business tolerance.

## (d) Detecting bad upstream data

Before calling the LLM or publishing to ClickHouse, the pipeline should run blocking data-quality checks.

Important checks include:

- booking ID is present and unique;
- required fields are not null;
- checkout date is after check-in date;
- `status`, `currency`, and `property_type` contain known values;
- `total_amount` is non-negative;
- row counts remain within an expected range;
- source totals reconcile with ingested totals.

For example, if the normal daily booking count is around 10,000 and today's partition suddenly contains 4,700 rows, that should be treated as an upstream anomaly.

An initial row-count rule could be:

```text
current row count >= 70% of the trailing 7-day median
```

Likewise, if a critical field changes from a normal 0% null rate to 100% null, the partition must not continue.

The failure behavior is:

```text
bad upstream partition
        ↓
STOP
        ↓
do not call the LLM
do not publish to ClickHouse
alert the data owner
```

This is different from an individual LLM failure. One failed classification should go to quarantine while the rest continue, but a broken upstream partition should block the entire publish step before it can poison reporting.

## Operational visibility

For each daily partition I would emit:

- input and validated row counts;
- invalid-row count and null rates;
- LLM success, failure, and retry counts;
- completion rate;
- pipeline duration;
- prompt version;
- ClickHouse publication status.

This makes it clear whether a failure came from source ingestion, validation, LLM enrichment, or ClickHouse publication.

## Summary

The design addresses the four main requirements:

1. **Daily assets and partitions:** each UTC day is processed independently.
2. **Idempotency:** staging plus partition replacement prevents duplicate loads on reruns.
3. **Partial failure:** successful LLM rows continue, while failed rows are quarantined and retried separately.
4. **Upstream protection:** blocking data-quality checks stop bad partitions before they reach the LLM or ClickHouse.

The exact numeric thresholds, such as 70% row-count tolerance or 10% LLM failure rate, are initial operating assumptions and should be calibrated using real production history.
