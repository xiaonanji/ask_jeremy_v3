## Overview

`PROD_ANALYTICS.PROD_SOURCE.STG_ZMDB_CONSUMER_ATTRIBUTE_HISTORY` is an **SCD Type 2 (Slowly Changing Dimension)** staging table that tracks the full historical record of attributes assigned to consumers in the ZipMoney platform (ZMDB). It is built from the source `zm_consumerattribute` table via Airbyte CDC, and is refreshed **hourly**.

Use this table when you need **point-in-time** or **historical** attribute analysis. For current-state-only queries, prefer the non-history sibling: `PROD_SOURCE.STG_ZMDB_CONSUMER_ATTRIBUTE` (a view that wraps this table, filtering for active records only).

---

## Table Location

| Property | Value |
|---|---|
| **Database** | `PROD_ANALYTICS` |
| **Schema** | `PROD_SOURCE` |
| **Table** | `STG_ZMDB_CONSUMER_ATTRIBUTE_HISTORY` |
| **Full Reference** | `PROD_ANALYTICS.PROD_SOURCE.STG_ZMDB_CONSUMER_ATTRIBUTE_HISTORY` |
| **Primary Key** | `ID` |
| **SCD2 Unique Key** | `SCD_ID` |
| **Refresh Frequency** | Hourly |

---

## Schema

| Column | Type | Description |
|---|---|---|
| `ID` | NUMBER | Source system primary key (maps to `zm_consumerattribute.id`) |
| `SCD_ID` | VARCHAR | SCD2 surrogate key — unique per version row |
| `CONSUMER_ID` | NUMBER | FK to `STG_ZMDB_CONSUMER.ID`. Identifies the consumer this attribute is assigned to |
| `ATTRIBUTE_ID` | NUMBER | FK to `STG_ZMDB_ATTRIBUTE.ID`. The type of attribute assigned (e.g. Fraud, Financial Hardship) |
| `ACTIVE` | BOOLEAN | Whether this attribute assignment is active in the source system |
| `VALID_FROM` | TIMESTAMP | When this version of the record became effective |
| `VALID_TO` | TIMESTAMP | When this version was superseded. **`'9999-12-31'` = still current** |
| `_AB_CDC_DELETED_AT` | TIMESTAMP | Set when the source row was deleted via CDC. NULL = not deleted |
| `_AB_CDC_UPDATED_AT` | TIMESTAMP | CDC timestamp of the last source change |
| `_AB_CDC_LSN` | VARCHAR | CDC log sequence number |

---

## Understanding SCD2 Behaviour

This table is built using the `scd2_zip_v1` dbt macro (incremental model). Every time a consumer's attribute is created, modified, or deactivated in the source system, a new row is written with updated `VALID_FROM`/`VALID_TO` bounds.

**Key rules:**

- **Current record sentinel:** `VALID_TO = '9999-12-31'` means the row is the **current active version**
- **Historical record:** `VALID_TO < '9999-12-31'` means the row has been superseded
- **Deleted record:** `_AB_CDC_DELETED_AT IS NOT NULL` means the row was hard-deleted in the source
- To get the **latest state only**, filter: `valid_to = '9999-12-31' AND _ab_cdc_deleted_at IS NULL`
- To query the state **at a specific point in time**, filter: `VALID_FROM <= :date AND VALID_TO > :date`

> ⚠️ **Critical:** Unlike some SCD2 tables, the sentinel for "current" is `VALID_TO = '9999-12-31'`, **NOT** `VALID_TO IS NULL`. Filtering for `IS NULL` will return zero results.

> ⚠️ **Always scope queries** with a `VALID_TO` condition or a date range. Without it you get all historical versions and will inflate consumer counts.

---

## Known Attribute IDs (`STG_ZMDB_ATTRIBUTE`)

| `ATTRIBUTE_ID` | Name | Notes |
|---|---|---|
| 1 | Fraud | Consumer flagged as fraudulent |
| 2 | Suspected Fraud | Consumer flagged as suspected fraud |
| 3–6 | Other risk attributes | See `STG_ZMDB_ATTRIBUTE` for full list |
| 8 | Financial Hardship | Consumer has a financial hardship arrangement |
| 9 | No Further Drawdown | Restricts further purchases on the account |
| 10, 14, 17, 18, 100, 104, 213, 214, 232, 255 | Various | See `STG_ZMDB_ATTRIBUTE` for full list |

> For the full canonical list, always query: `SELECT id, name, category, type FROM PROD_ANALYTICS.PROD_SOURCE.STG_ZMDB_ATTRIBUTE`

---

## Common Query Patterns

### 1. Get current active attributes for a specific consumer

```sql
SELECT
    h.consumer_id,
    h.attribute_id,
    a.name            AS attribute_name,
    a.category        AS attribute_category,
    h.active,
    h.valid_from
FROM PROD_ANALYTICS.PROD_SOURCE.STG_ZMDB_CONSUMER_ATTRIBUTE_HISTORY h
JOIN PROD_ANALYTICS.PROD_SOURCE.STG_ZMDB_ATTRIBUTE a
    ON h.attribute_id = a.id
WHERE h.consumer_id = 12345
  AND h.valid_to = '9999-12-31'
  AND h._ab_cdc_deleted_at IS NULL;
```

---

### 2. Point-in-time query — what attributes were active on a specific date?

```sql
SELECT
    h.consumer_id,
    h.attribute_id,
    a.name     AS attribute_name,
    h.valid_from,
    h.valid_to
FROM PROD_ANALYTICS.PROD_SOURCE.STG_ZMDB_CONSUMER_ATTRIBUTE_HISTORY h
JOIN PROD_ANALYTICS.PROD_SOURCE.STG_ZMDB_ATTRIBUTE a
    ON h.attribute_id = a.id
WHERE h.valid_from <= '2024-01-01'
  AND h.valid_to    > '2024-01-01'
  AND h._ab_cdc_deleted_at IS NULL;
```

---

### 3. Fraud flag history for a specific consumer (most recent first)

```sql
SELECT
    consumer_id,
    attribute_id,
    active,
    valid_from,
    valid_to
FROM PROD_ANALYTICS.PROD_SOURCE.STG_ZMDB_CONSUMER_ATTRIBUTE_HISTORY
WHERE consumer_id  = 12345
  AND attribute_id IN (1, 2)    -- 1 = Fraud, 2 = Suspected Fraud
ORDER BY valid_from DESC;
```

---

### 4. Check if a consumer had Financial Hardship active during a fee period

```sql
SELECT
    h.consumer_id,
    h.attribute_id,
    h.valid_from,
    h.valid_to
FROM PROD_ANALYTICS.PROD_SOURCE.STG_ZMDB_CONSUMER_ATTRIBUTE_HISTORY h
WHERE h.attribute_id = 8        -- Financial Hardship
  AND h.consumer_id = (
      SELECT consumer_id
      FROM PROD_ANALYTICS.PROD_SOURCE.STG_ZMDB_CONSUMERACCOUNT
      WHERE account_id = 2534906
  )
  AND h.valid_from <= '2024-06-30'
  AND h.valid_to    > '2024-06-01'
ORDER BY h.valid_from DESC;
```

---

### 5. All consumers currently carrying a Fraud attribute (bulk)

```sql
SELECT
    h.consumer_id,
    a.name       AS attribute_name,
    h.valid_from AS flagged_since
FROM PROD_ANALYTICS.PROD_SOURCE.STG_ZMDB_CONSUMER_ATTRIBUTE_HISTORY h
JOIN PROD_ANALYTICS.PROD_SOURCE.STG_ZMDB_ATTRIBUTE a
    ON h.attribute_id = a.id
WHERE h.attribute_id IN (1, 2)
  AND h.valid_to = '9999-12-31'
  AND h._ab_cdc_deleted_at IS NULL;
```

---

### 6. Using the current-state view (simpler, no VALID_TO filter needed)

```sql
-- STG_ZMDB_CONSUMER_ATTRIBUTE is a view over the history table
-- It pre-applies: valid_to = '9999-12-31' AND _ab_cdc_deleted_at IS NULL
SELECT
    ca.consumer_id,
    ca.attribute_id,
    a.name AS attribute_name,
    ca.active
FROM PROD_ANALYTICS.PROD_SOURCE.STG_ZMDB_CONSUMER_ATTRIBUTE ca
JOIN PROD_ANALYTICS.PROD_SOURCE.STG_ZMDB_ATTRIBUTE a
    ON ca.attribute_id = a.id
WHERE ca.attribute_id IN (1, 2);
```

---

## Current State vs History — Which to Use?

| Use Case | Table to Use |
|---|---|
| "Does this consumer have a fraud flag **today**?" | `STG_ZMDB_CONSUMER_ATTRIBUTE` (view) |
| "When was fraud flag first applied to this consumer?" | `STG_ZMDB_CONSUMER_ATTRIBUTE_HISTORY` |
| "What attributes were active on this consumer on 1 Jan 2024?" | `STG_ZMDB_CONSUMER_ATTRIBUTE_HISTORY` |
| "How many consumers have Financial Hardship **right now**?" | `STG_ZMDB_CONSUMER_ATTRIBUTE` (view) |
| "Fee audit — was hardship active when we charged this fee?" | `STG_ZMDB_CONSUMER_ATTRIBUTE_HISTORY` |
| "All historical changes to a consumer's fraud status" | `STG_ZMDB_CONSUMER_ATTRIBUTE_HISTORY` |
| "Consumer attribute joined with account and customer" | `PROD_PREP.MAP_CONSUMER_TO_CONSUMER_ATTRIBUTE` |

---

## Gotchas & Best Practices

1. **`VALID_TO = '9999-12-31'`, not NULL** — current records use the sentinel `9999-12-31`, not a null. Filtering `VALID_TO IS NULL` will return nothing.
2. **Always filter `_AB_CDC_DELETED_AT IS NULL`** when querying current state — CDC-deleted records are retained in the table but should be excluded.
3. **`ACTIVE` ≠ current** — a row can have `ACTIVE = FALSE` and still be the current version (`VALID_TO = '9999-12-31'`) if the attribute was explicitly deactivated without being deleted. These are two separate concepts.
4. **Don't hardcode attribute names** — always join to `STG_ZMDB_ATTRIBUTE` for canonical names. IDs are stable; names may change.
5. **Prefer the view for current-state queries** — `STG_ZMDB_CONSUMER_ATTRIBUTE` pre-applies the correct `VALID_TO` and CDC deleted-at filters. Use the history table only when you need time-travel.
6. **Use `MAP_CONSUMER_TO_CONSUMER_ATTRIBUTE` for enriched data** — if you need attribute data joined to account/customer context or derived flags (write-off, bscore, collector referred), use this `PROD_PREP` model instead of joining yourself.
7. **This is a PROD_SOURCE table** — no business-rule transforms are applied here. For curated, rule-applied models, look upstream in `PROD_PREP`.