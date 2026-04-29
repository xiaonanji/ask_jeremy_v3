# Skill: `prod_mart.risk_credit_changes`

## Overview

`PROD_ANALYTICS.PROD_MART.RISK_CREDIT_CHANGES` is a daily-refreshed mart table that contains the **complete history of credit limit changes** across all Zip products (Zip Pay, Zip Money, Zip Plus). Each row represents a single credit limit change event — either a Credit Limit Decrease (CLD) or Credit Limit Increase (CLI) — for a customer account.

It is the authoritative source for risk teams and data science models to analyse credit limit change patterns, and is a key feature input into behavioural scoring, DPD recovery, and debt collection referral models.

- **Materialization:** Table
- **Refresh cadence:** Daily at 14:00 UTC (`tags: daily_run`)
- **Row grain:** One row per credit limit change event per account

---

## Schema

| Column | Type | Description |
|---|---|---|
| `lower_customer_id` | string | Lowercase UUID of the customer. Join key to customer-level tables. |
| `account_id` | string | Account identifier. Join key to `dim_account`. |
| `consumer_id` | string | Consumer identifier from the core platform. |
| `credit_profile_limit_update_id` | string | Unique ID of the credit limit update record in the source system (`stg_zmdb_credit_profile_limit_update`). Null for holdout records. |
| `product` | string | Product associated with the account. Values include `Zip Pay`, `Zip Money`, `Zip Plus`, `ZipTrade`, `ZipTradePlus`. |
| `credit_limit_change_yyyymmdd` | date | Date the credit limit change status was recorded (the latest status event date). Despite the `yyyymmdd` suffix, this is a `DATE` column. |
| `credit_limit_change_submit_approve_yyyymmdd` | date | Date the change was first submitted or approved. Used in all downstream model lookback windows. **Null for holdout records.** Despite the `yyyymmdd` suffix, this is a `DATE` column. |
| `from_credit_limit` | number | Credit limit before the change. |
| `to_credit_limit` | number | Credit limit after the change. |
| `cld_rule` | string | Rule code that triggered a system-driven CLD (e.g. `R07.zp_bureau_segment_1`). Null for manual or CLI events. |
| `crm_comment` | string | Free-text CRM comment describing the reason for the change. Parsed to derive `cl_category`. |
| `cl_category` | string | Categorised type of the credit limit change. See category reference below. |
| `flag_holdout` | integer | `1` if this record originates from a holdout dataset (not a live transaction), `0` otherwise. |
| `run_date` | date | The date the dbt model last ran (`current_date`). Do **not** use this column for historical filtering. |

---

## `cl_category` Reference

The `cl_category` column is derived by parsing the `crm_comment` / `submit_approve_comments` text. There are 12 possible values:

| Category | Type | Description |
|---|---|---|
| `01.ZP 2K CLD` | CLD | Zip Pay accounts reduced to a $2,000 limit |
| `02.Backbook CLD` | CLD | Compulsory CLD applied to the existing customer backbook |
| `03.Dormancy CLD` | CLD | CLD triggered by account inactivity |
| `04.Unprofitable CLD` | CLD | CLD for bureau segment 1 (`R07`) customers deemed unprofitable |
| `05.Bureau wash CLD` | CLD | CLD following a credit bureau account review |
| `06.Risk driven compulsory CLD` | CLD | Mandatory CLD triggered by a risk-based assessment |
| `07.Customer requested CLD` | CLD | Customer initiated the decrease themselves |
| `08.Accepted CLI` | CLI | Credit Limit Increase accepted by the customer |
| `09.Approved not accepted CLI` | CLI | CLI was approved but the customer has not yet accepted |
| `10.Cancelled CLI` | CLI | CLI offer was cancelled |
| `11.Declined CLI` | CLI | CLI request was declined |
| `99.Others` | Unknown | Could not be mapped to any of the above categories |

> **Compulsory CLDs** (categories `02`–`06`) are the most used risk signal. Downstream models typically filter `cl_category IN ('02.Backbook CLD', '03.Dormancy CLD', '05.Bureau wash CLD', '06.Risk driven compulsory CLD')` over a 12-month lookback window.

---

## Common Query Patterns

### 1. All compulsory CLDs in the last 12 months (standard risk filter)

```sql
SELECT
    lower_customer_id,
    consumer_id,
    product,
    cl_category,
    credit_limit_change_submit_approve_yyyymmdd,
    from_credit_limit,
    to_credit_limit
FROM PROD_ANALYTICS.PROD_MART.RISK_CREDIT_CHANGES
WHERE cl_category IN (
    '02.Backbook CLD',
    '03.Dormancy CLD',
    '05.Bureau wash CLD',
    '06.Risk driven compulsory CLD'
)
AND credit_limit_change_submit_approve_yyyymmdd >= DATEADD(MONTH, -12, CURRENT_DATE)
AND flag_holdout = 0
```

### 2. Most recent credit change per consumer (latest state)

```sql
SELECT *
FROM PROD_ANALYTICS.PROD_MART.RISK_CREDIT_CHANGES
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY consumer_id
    ORDER BY credit_limit_change_submit_approve_yyyymmdd DESC NULLS LAST
) = 1
```

### 3. Monthly CLD volume by category and product

```sql
SELECT
    DATE_TRUNC('month', credit_limit_change_submit_approve_yyyymmdd) AS month,
    product,
    cl_category,
    COUNT(*)                                         AS num_changes,
    AVG(from_credit_limit - to_credit_limit)         AS avg_limit_reduction
FROM PROD_ANALYTICS.PROD_MART.RISK_CREDIT_CHANGES
WHERE cl_category LIKE '%CLD%'
  AND flag_holdout = 0
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 4 DESC
```

### 4. CLI acceptance rate by product

```sql
SELECT
    product,
    COUNTIF(cl_category = '08.Accepted CLI')                             AS accepted,
    COUNTIF(cl_category = '09.Approved not accepted CLI')                AS approved_not_accepted,
    COUNTIF(cl_category = '11.Declined CLI')                             AS declined,
    COUNTIF(cl_category = '08.Accepted CLI')
        / NULLIF(COUNTIF(cl_category IN (
            '08.Accepted CLI', '09.Approved not accepted CLI', '11.Declined CLI'
        )), 0)                                                           AS acceptance_rate
FROM PROD_ANALYTICS.PROD_MART.RISK_CREDIT_CHANGES
WHERE flag_holdout = 0
GROUP BY 1
```

---

## Key Gotchas

1. **`yyyymmdd` suffix ≠ integer.** Despite the column naming convention, `credit_limit_change_yyyymmdd` and `credit_limit_change_submit_approve_yyyymmdd` are `DATE` columns (cast via `date(...)` in the model), not integers. Use standard `DATE` comparison operators.

2. **Null `credit_limit_change_submit_approve_yyyymmdd` for holdouts.** Holdout records (`flag_holdout = 1`) do not have a submission/approval timestamp. Filtering on this column without accounting for nulls will silently exclude holdout rows.

3. **`run_date` is always today.** `run_date = current_date` at model execution time. It is not the change date — do not use it for historical analysis or to check data freshness.

4. **One row per change event, not per account.** A customer can have multiple rows. Always apply a `QUALIFY ROW_NUMBER()` window or explicit aggregation when you need a single value per customer.

5. **`cl_category = '99.Others'`** indicates the change could not be mapped by the comment-parsing logic. This may represent edge cases or data quality issues in the source `crm_comment` field.

6. **`credit_profile_limit_update_id` is null for holdout records.** Do not join on this column without filtering `flag_holdout = 0` first.

7. **Product name inconsistencies across consumers.** Behavioural scoring notebooks reference values like `'Zip Pay'`, `'Zip Money'`, `'ZipPay'`, `'ZipMoney'`. Verify exact values in your environment before filtering on `product`.
