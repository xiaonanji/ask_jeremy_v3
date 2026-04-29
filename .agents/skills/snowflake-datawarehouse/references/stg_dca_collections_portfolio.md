## Overview

`PROD_ANALYTICS.PROD_SOURCE.STG_DCA_COLLECTIONS_PORTFOLIO` is a **monthly incremental snapshot** of all accounts eligible for — or currently under — referral to a Debt Collection Agency (DCA). It is the single source of truth for monthly DCA referral decisions across all Australian Zip products.

On the **3rd of each month**, this model runs against the end-of-prior-month account state and:
1. Identifies accounts meeting balance and DPD eligibility criteria
2. Applies a layered set of exclusion rules (bankruptcy, hardship, settled, statute-barred, etc.)
3. Randomly assigns eligible accounts to a collector (ARMA, Indebted, or In-house) using product-specific splits
4. Outputs one row per account per collector per month — the file that Credit Ops uploads directly to each DCA

- **Materialization:** Incremental (partitioned by `month`)
- **Unique key:** `(account_id, collector_id, month)`
- **Row grain:** One row per account × collector × month
- **Expected row count:** 12,000–16,000 rows per current month

---

## Schema

| Column | Type | Description |
|---|---|---|
| `account_id` | string | Unique account identifier. PK component. |
| `statement_of_work_id` | string | UUID identifying the statement of work for the product. Product-specific constant — null/empty for ZipPLoan. |
| `due_date` | date | Snapshot date — the last day of the previous month. |
| `balance` | number | Account balance **in cents**. Uses `arrears_balance` for active accounts; uses `net_balance` for written-off accounts. Minimum value: 1,000 cents ($10). |
| `consumer_id` | string | Customer identifier. |
| `first_name` | string | Customer's first name. |
| `middle_name` | string | Customer's middle name. |
| `last_name` | string | Customer's last name. |
| `dob` | date | Customer's date of birth. |
| `email` | string | Customer's email address. |
| `phone_number` | string | Customer's phone number (mobile, most recent active). |
| `address_line_1` | string | Street number. |
| `address_line_2` | string | Street name. |
| `city` | string | Suburb / city. |
| `state` | string | Australian state. |
| `post_code` | string | Postal code. |
| `country_code` | string | Country code. Always `AU` — NZ accounts are explicitly excluded. |
| `arrears_days` | integer | Number of days the account is in arrears at snapshot date. |
| `is_written_off` | integer | `1` if the account has been written off, `0` otherwise. |
| `early_stage` | integer | `1` if the account is an early-stage collection referral, `0` for late-stage. |
| `collector_id` | integer | Assigned collector. See reference table below. |
| `product` | string | Product type in **lowercase**. See reference table below. |
| `has_successful_rds` | boolean | `true` if the account has a valid payment method and made a successful payment in the last 2 months. Accounts with `true` are excluded from new referrals. |
| `month` | timestamp_ntz | The month this snapshot covers — the last day of the prior month as a timestamp. **Use this column for period filtering.** |
| `updated_timestamp` | timestamp_ntz | UTC timestamp when the record was written. |
| `data_loaded_timestamp` | timestamp_ntz | UTC timestamp when the data was loaded into Snowflake. |

---

## Reference: `collector_id` Values

| `collector_id` | DCA |
|---|---|
| `0` | Indebted |
| `1` | ARMA |
| `2` | In-house |

---

## Reference: `product` Values

| `product` | Zip Product |
|---|---|
| `zippay` | Zip Pay |
| `zipmoney` | Zip Money |
| `zipplus` | Zip Plus |
| `ziploan` | Zip Personal Loans |

> **Note:** `product` is always **lowercase** in this table (stored as `lower(product)` from the source). Do not filter with `'Zip Pay'` or `'ZipPay'` — use `'zippay'`.

---

## Eligibility Criteria

Accounts must meet **all** of the following to appear in this table:

| Condition | ZipPay | ZipMoney / ZipPlus / ZipPLoan |
|---|---|---|
| Net balance threshold | ≥ $100 | ≥ $100 |
| DPD threshold (non-written-off) | ≥ 89 DPD AND arrears balance ≥ $100 | ≥ 181 DPD AND arrears balance ≥ $100 |
| Written-off (bypasses DPD check) | ✓ | ✓ |
| Account status | Open (1), Suspended (2), Written Off (5, 7) | Open (1), Suspended (2), Written Off (5, 7) |
| Country | AU only | AU only |

---

## Exclusion Filters Applied

Accounts are **excluded** if any of the following flags are set. These flags are computed internally in the model but are **not exposed** as columns in the output — they are applied as WHERE conditions in the `monthly_report` CTE:

| Exclusion | Description |
|---|---|
| `has_successful_rds = true` | Valid payment method + successful payment in last 2 months |
| Consumer attribute flags | Deceased, bankrupt, Part IX/X, AFCA, fraud, hardship, settled, uncontactable, vulnerable customer, long-term arrangement, LOA/LTA |
| `already_ref_to_dca_flg = 1` | Account is already active in ARMA or Indebted's latest portfolio |
| `sold_account_flg = 1` | Account has been sold (funding program IDs 17–22) |
| `stat_barred_flg = 1` | Statute-barred: >3 years last payment (NT) or >6 years (all other states) |
| `account_settled_flag = 1` | Closed as "Settled" by either ARMA or Indebted |
| `no_contact_details_flg = 1` | No email AND no phone number on file |
| `adhoc_exclusion_flg = 1` | Listed in the active ad-hoc exclusion table (`stg_dca_adhoc_referral_exclusion`) |
| `excl_small_bal_flg = 1` | Balance or net balance < $100 on current run date |
| `country_id IS NULL` | Unknown country |
| NZ accounts | `country_code = 'NZ'` — hard-coded exclusion at final SELECT |

---

## Collector Assignment Logic

New referrals are randomly allocated to collectors using `UNIFORM()`. Previous referrals re-use their last assigned collector.

| Product | Written-Off Split | Non-Written-Off Split | ML Override |
|---|---|---|---|
| ZipPay | 60% ARMA / 40% Indebted | 40% Indebted / 40% ARMA / 20% In-house | `stg_databricks_ds_zp_late_stage_dca_referral_scoring` adjusts in-house ↔ external split |
| ZipMoney | 60% ARMA / 40% Indebted | 50% Indebted / 50% ARMA | None |
| ZipPlus | 50% ARMA / 50% Indebted | 50% Indebted / 50% ARMA | None |
| ZipPLoan | 60% ARMA / 40% Indebted | 50% Indebted / 50% ARMA | None |

---

## Example Queries

### 1. All accounts referred to ARMA in the most recent month
```sql
SELECT
    account_id          AS account_ref,
    NULLIF(statement_of_work_id, '') AS statement_of_work_id,
    due_date,
    balance,
    consumer_id         AS customer_ref,
    first_name, middle_name, last_name,
    dob, email, phone_number,
    address_line_1, address_line_2,
    city, state, post_code, country_code,
    arrears_days,
    is_written_off
FROM PROD_ANALYTICS.PROD_SOURCE.STG_DCA_COLLECTIONS_PORTFOLIO
WHERE month = DATE_TRUNC('month', CURRENT_DATE) - 1
  AND (has_successful_rds = FALSE OR has_successful_rds IS NULL)
  AND product = 'zippay'
  AND collector_id = 1   -- ARMA
```

### 2. All accounts referred to Indebted for ZipMoney in the most recent month
```sql
SELECT
    account_id          AS account_ref,
    NULLIF(statement_of_work_id, '') AS statement_of_work_id,
    due_date,
    balance,
    consumer_id         AS customer_ref,
    first_name, middle_name, last_name,
    dob, email, phone_number,
    address_line_1, address_line_2,
    city, state, post_code, country_code,
    arrears_days,
    is_written_off
FROM PROD_ANALYTICS.PROD_SOURCE.STG_DCA_COLLECTIONS_PORTFOLIO
WHERE month = DATE_TRUNC('month', CURRENT_DATE) - 1
  AND (has_successful_rds = FALSE OR has_successful_rds IS NULL)
  AND product = 'zipmoney'
  AND collector_id = 0   -- Indebted
```

### 3. Early-stage referrals across all collectors (used in daily payment files)
```sql
SELECT
    account_id,
    early_stage
FROM PROD_ANALYTICS.PROD_SOURCE.STG_DCA_COLLECTIONS_PORTFOLIO
WHERE (has_successful_rds = FALSE OR has_successful_rds IS NULL)
  AND month > '2022-01-31'
  AND collector_id IN (0, 1)   -- Indebted and ARMA
  AND early_stage = 1
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY account_id
    ORDER BY month DESC
) = 1
```

### 4. DCA referral events for arrears analytics
```sql
SELECT
    account_id,
    'REFER'                                  AS event,
    due_date,
    CASE
        WHEN collector_id = 0 THEN 'INDEBTED'
        WHEN collector_id = 1 THEN 'ARMA'
        WHEN collector_id = 2 THEN 'IN-HOUSE'
        ELSE 'NA'
    END                                      AS dca,
    month                                    AS event_date,
    arrears_days,
    early_stage
FROM PROD_ANALYTICS.PROD_SOURCE.STG_DCA_COLLECTIONS_PORTFOLIO
```

### 5. Monthly referral volume by product and collector
```sql
SELECT
    DATE_TRUNC('month', month)               AS referral_month,
    product,
    CASE
        WHEN collector_id = 0 THEN 'Indebted'
        WHEN collector_id = 1 THEN 'ARMA'
        WHEN collector_id = 2 THEN 'In-house'
    END                                      AS collector,
    COUNT(DISTINCT account_id)               AS num_accounts_referred,
    SUM(balance) / 100.0                     AS total_balance_dollars,
    AVG(arrears_days)                        AS avg_arrears_days,
    SUM(is_written_off)                      AS written_off_count
FROM PROD_ANALYTICS.PROD_SOURCE.STG_DCA_COLLECTIONS_PORTFOLIO
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 4 DESC
```

---

## Key Gotchas

1. **`balance` is in cents.** The column stores `100 * net_balance` or `100 * arrears_balance`. Divide by 100 to get dollar amounts: `balance / 100.0`.

2. **`product` is always lowercase.** Filter on `'zippay'`, `'zipmoney'`, `'zipplus'`, `'ziploan'` — not title case. This differs from most other tables in the warehouse.

3. **`month` is a `TIMESTAMP_NTZ`, not a `DATE`.** Use `DATE_TRUNC('month', month)` or cast to `::date` when joining against date columns. The value is always the last day of the prior month at midnight UTC (e.g. `2026-03-31 00:00:00`).

4. **Incremental model — historical months are fixed, current month is rebuilt.** The pre-hook deletes and rewrites the current month's partition on each run. Do not rely on `updated_timestamp` to detect changed rows in historical months — they will not be updated.

5. **`has_successful_rds` can be `NULL`.** This occurs for accounts with no payment method. Downstream models filter `has_successful_rds = FALSE OR has_successful_rds IS NULL` — do not use `has_successful_rds != TRUE` without a null-safe comparison.

6. **One row per `(account_id, collector_id, month)`.** An account can appear twice in the same month if it was referred to two collectors (e.g. early-stage and late-stage handling). Always check if you need `DISTINCT account_id` for account-level analysis.

7. **NZ accounts are excluded.** The final SELECT has `WHERE UPPER(country_code) != 'NZ'`. This table covers AU only.

8. **`statement_of_work_id` is an empty string (not NULL) for ZipPLoan.** Downstream models handle this with `NULLIF(statement_of_work_id, '')`. Apply the same pattern when exposing this column.

9. **This table contains PII.** `first_name`, `last_name`, `dob`, `email`, `phone_number`, and address fields are all present. The S3 unload uses the `PII_RISK_DATASCIENCE` stage. Handle with appropriate access controls.
