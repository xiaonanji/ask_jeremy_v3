# Skill: PROD_ANALYTICS.PROD_PREP.DIM_ACCOUNT

## Overview

`PROD_ANALYTICS.PROD_PREP.DIM_ACCOUNT` is the **primary account dimension** in Zip's Snowflake analytics platform. It provides the **current state** of every account across all AU and NZ products (Zip Pay, Zip Money, Zip Plus, Zip Biz, Zip Personal Loan).

- **Grain:** One row per `account_id` — current snapshot only (not historical)
- **Primary Key:** `account_id` (unique, not null)
- **Refresh cadence:** Hourly (`hourly_run` dbt tag)

---

## Column Reference

### Identity & Consumer Linkage

| Column | Data Type | Description |
|---|---|---|
| `account_id` | NUMBER(38,0) | **PK.** Unique numeric identifier for the account |
| `consumer_id` | NUMBER(38,0) | FK to the consumer/customer record |
| `customer_id` | VARCHAR | Lowercase-normalised string identifier for the customer |
| `public_consumer_id` | VARCHAR | Public-facing consumer identifier |
| `application_id` | NUMBER(38,0) | FK to the originating credit application |
| `dual_account_flag` | BOOLEAN | True if the consumer holds both a Zip Pay and Zip Money account |
| `primary_flag` | BOOLEAN | True if this is the consumer's primary account |

---

### Product

| Column | Data Type | Description |
|---|---|---|
| `product` | VARCHAR | Product name. Values: `Zip Pay`, `Zip Money`, `Zip Plus`, `Zip Biz`, `Zip Business Trade`, `Zip Business Trade Plus`, `Zip Personal Loan` |
| `product_group` | VARCHAR | Higher-level product grouping |
| `product_country` | VARCHAR | Country of the product — `AU` or `NZ` |
| `account_type` | VARCHAR | Account type description (from `stg_zmdb_account_type`) |
| `reference_code` | VARCHAR | Account type reference code used for product sub-classification |

---

### Origination & Merchant

| Column | Data Type | Description |
|---|---|---|
| `origination_merchant_id` | NUMBER(38,0) | Merchant through which the account was acquired (0 = direct/none) |
| `origination_branch_id` | NUMBER(38,0) | Branch through which the account was acquired |
| `origination_merchant_name` | VARCHAR | Name of the origination merchant. `'Direct'` if no merchant |
| `flag_exclusive_origination_merchant` | NUMBER(2,0) | 1 if the account is exclusive to the origination merchant |
| `first_merchant_id` | NUMBER(38,0) | Merchant ID of the first transaction |
| `first_merchant_name` | VARCHAR | Merchant name of the first transaction. `'Not Yet Transacted'` if no order placed |
| `first_merchant_industry` | VARCHAR | Industry of the first-transaction merchant |
| `first_merchant_sub_category` | VARCHAR | Sub-category of the first-transaction merchant |
| `first_order_timestamp` | TIMESTAMP_NTZ(9) | Timestamp of the account's first order |

---

### Account Status

| Column | Data Type | Description |
|---|---|---|
| `account_status` | VARCHAR(11) | Current operational state. Values: `Operational`, `Closed`, `Locked`, `WrittenOff` |
| `account_status_reason` | VARCHAR | Human-readable reason for non-operational status (e.g. `Deceased`, `AFCA`, `Bankrupt`, `Part IX`, `Fraud`, `Hardship`, `Arrears`, `Uncontactable`, `LOA`, `NFD`) |
| `account_status_lock_reason` | VARCHAR | Sub-type reason when status is `Locked` |
| `account_fraud_flag` | VARCHAR(23) | Fraud classification. Values: `No Fraud`, `Fraud`, `Suspected Fraud`, `Fraud & Suspected Fraud` |

**Status derivation logic:**
```sql
-- account_status is derived as:
CASE
    WHEN fpr.type = 2               THEN 'WrittenOff'
    WHEN acc.account_status = 4     THEN 'Closed'
    WHEN acc.account_status = 7     THEN 'Locked'
    ELSE                                 'Operational'
END
```

---

### Financial

| Column | Data Type | Description |
|---|---|---|
| `credit_limit` | FLOAT | Approved credit limit. For Zip Personal Loan (`classification = 5`), includes establishment fee |
| `net_balance` | FLOAT | Current outstanding balance |
| `arrears_balance` | FLOAT | Amount currently in arrears |
| `arrears_days` | NUMBER(38,0) | Number of days past due (from most recent daily batch summary) |
| `arrears_months` | NUMBER(9,0) | Months past due — derived from `arrears_days` and `arrears_date` |
| `delinquency_bucket` | VARCHAR | Delinquency classification (see logic below) |
| `arrears_hold_date` | TIMESTAMP_NTZ(9) | Future hold date; null if hold has expired |
| `writeoff_month` | VARCHAR | Month of write-off formatted as `MON-YYYY` (e.g. `JAN-2024`). Null if not written off |

**Delinquency bucket logic:**
- `'Current'` — no arrears or arrears_balance/net_balance ≤ $10
- **Zip Money** (DPD): `1-30 DPD`, `31-60 DPD`, `61-90 DPD`, `91-120 DPD`, `121-150 DPD`, `151-180 DPD`, `>180 DPD`
- **Zip Pay / Zip Plus / Zip Biz / Zip Personal Loan** (MPD): `1 MPD`, `2 MPD`, `3 MPD`, `4 MPD`, `5 MPD`, `6 MPD`, `>6 MPD`
- `'N/A'` — arrears_days > 360 (ZM) or arrears_months > 12 (ZP/Z+)

---

### Fees & Repayment Terms

| Column | Data Type | Description |
|---|---|---|
| `contracted_monthly_fee` | FLOAT | Monthly account-keeping fee per account type |
| `late_payment_fee` | FLOAT | Late payment fee per account type |
| `establishment_fee` | FLOAT | Establishment fee per account type |
| `repayment_minimum_monthly_amount` | FLOAT | Minimum monthly repayment amount (from account type config) |
| `repayment_minimum_percentage` | FLOAT | Minimum repayment as percentage of balance |
| `repayment_schedule_amount` | FLOAT | Customer's active repayment schedule amount |
| `repayment_schedule_frequency` | VARCHAR | Repayment frequency: `Weekly`, `Fortnightly`, `Monthly` |

---

### Funding Program

| Column | Data Type | Description |
|---|---|---|
| `funding_program_id` | FLOAT | FK to the funding program |
| `funding_program_name` | VARCHAR | Name of the funding program |

> Note: `writeoff_month` is only populated for accounts with `funding_program_id IN (6, 7, 9, 11, 14, 15, 16, 18, 19)`.

---

### Consumer Attributes & Flags

| Column | Data Type | Description |
|---|---|---|
| `consumer_attributes` | ARRAY | Array of all active attribute names for the account (e.g. `['Fraud', 'Hardship']`) |
| `hardship_flag` | NUMBER(1,0) | 1 if account has ever had hardship attribute (attribute_id = 8) |
| `hardship_pending_flag` | NUMBER(1,0) | 1 if account has hardship pending (attribute_id = 213) |
| `zip_plus_upgraded_from_zp` | VARCHAR(1) | `'Y'` if this Zip Plus account was upgraded from a Zip Pay account |
| `zip_pay_upgraded_to_zip_plus` | VARCHAR(1) | `'Y'` if this Zip Pay account was upgraded to Zip Plus |
| `re_aged_tag` | NUMBER(1,0) | 1 if the account has been re-aged |
| `re_age_date` | DATE | Date of re-age event |
| `re_age_reason` | VARCHAR | Reason for re-aging |
| `installment_account` | BOOLEAN | Whether the account had instalments opt-in enabled. **⚠️ Instalments retired Aug 2025**; flag being set to false during decommissioning. Reliable data from March 2023 onwards (ref TS-9623). |

---

### Timestamps

| Column | Data Type | Description |
|---|---|---|
| `registration_timestamp` | TIMESTAMP_NTZ(9) | When the account was registered/opened |
| `closed_timestamp` | TIMESTAMP_NTZ(9) | When the account was closed (null if open) |
| `credit_profile_open_timestamp` | TIMESTAMP_NTZ(9) | Most recent open state timestamp from credit profile state |
| `credit_profile_closed_timestamp` | TIMESTAMP_NTZ(9) | Most recent closed state timestamp from credit profile state |
| `created_at_ltz` | TIMESTAMP_NTZ(9) | Account creation timestamp (local time, stored as NTZ) |
| `last_modified_timestamp_utc` | TIMESTAMP_NTZ(9) | Latest modification time across all source entities — used as a data freshness indicator |

---

### PII / Address & Contact ⚠️ Masked

The following columns contain **PII** and are subject to masking policies. They may be masked or nulled depending on your Snowflake role.

| Column | Data Type | Masking Policy |
|---|---|---|
| `email_address` | VARCHAR | `sensitive_data` |
| `first_name` | VARCHAR | `sensitive_data` |
| `last_name` | VARCHAR | `sensitive_data` |
| `date_of_birth` | TIMESTAMP_NTZ(9) | `sensitive_timestamp` |
| `street_name_and_number` | VARCHAR | `sensitive_data` |
| `suburb` | VARCHAR | `sensitive_data` |
| `state` | VARCHAR | `sensitive_data` |
| `postcode` | VARCHAR | `sensitive_data` |
| `phone_number` | VARCHAR | `sensitive_data` |
| `residential_country` | VARCHAR | _(no masking)_ |

---

## Common Query Patterns

### Count active accounts by product
```sql
SELECT
    product,
    COUNT(*) AS account_count
FROM PROD_ANALYTICS.PROD_PREP.DIM_ACCOUNT
WHERE account_status = 'Operational'
GROUP BY product
ORDER BY account_count DESC;
```

### Accounts in arrears by delinquency bucket
```sql
SELECT
    product,
    delinquency_bucket,
    COUNT(*)          AS accounts,
    SUM(net_balance)  AS total_balance,
    SUM(arrears_balance) AS total_arrears
FROM PROD_ANALYTICS.PROD_PREP.DIM_ACCOUNT
WHERE delinquency_bucket <> 'Current'
GROUP BY product, delinquency_bucket
ORDER BY product, delinquency_bucket;
```

### Find all accounts for a specific customer
```sql
SELECT
    account_id,
    product,
    account_status,
    credit_limit,
    registration_timestamp
FROM PROD_ANALYTICS.PROD_PREP.DIM_ACCOUNT
WHERE customer_id = <customer_id>;
```

### Accounts opened in the last 30 days
```sql
SELECT *
FROM PROD_ANALYTICS.PROD_PREP.DIM_ACCOUNT
WHERE registration_timestamp >= DATEADD(day, -30, CURRENT_TIMESTAMP());
```

### Join to an order/transaction table
```sql
SELECT
    da.account_id,
    da.product,
    da.origination_merchant_name,
    o.order_id,
    o.order_amount
FROM PROD_ANALYTICS.PROD_PREP.DIM_ACCOUNT da
INNER JOIN PROD_ANALYTICS.PROD_PREP.<order_table> o
    ON da.account_id = o.account_id
WHERE da.account_status = 'Operational';
```

### Zip Plus accounts upgraded from Zip Pay
```sql
SELECT COUNT(*) AS upgraded_accounts
FROM PROD_ANALYTICS.PROD_PREP.DIM_ACCOUNT
WHERE product = 'Zip Plus'
  AND zip_plus_upgraded_from_zp = 'Y';
```

### Check for hardship / special attributes
```sql
SELECT
    account_id,
    consumer_attributes,
    hardship_flag,
    account_status_reason
FROM PROD_ANALYTICS.PROD_PREP.DIM_ACCOUNT
WHERE hardship_flag = 1
   OR ARRAY_CONTAINS('AFCA'::VARIANT, consumer_attributes);
```

---

## Key Caveats & Gotchas

1. **Current state only.** This table reflects the account's state _right now_.

2. **`account_status = 0` is excluded.** The SQL model filters out `account_status <> 0` from the source staging table. These are effectively invalid/ghost records.

3. **Arrears data is as-of latest batch run date.** `arrears_days`, `arrears_balance`, and `net_balance` come from `stg_batchoperations_account_daily_summary` and reflect the most recent `arrears_date`, not real-time.

4. **`delinquency_bucket` threshold is $10.** Accounts with `arrears_balance ≤ $10` or `net_balance ≤ $10` are classified as `'Current'` regardless of days past due.

5. **Zip Money uses DPD; all other products use MPD.** Do not compare delinquency buckets across products without accounting for this.

6. **`credit_limit` for Zip Personal Loan includes the establishment fee.** For ZPL (`consumer.classification = 5`), credit_limit = credit_profile credit_limit + establishment_fee.

7. **`writeoff_month` is only populated for specific funding programs** (IDs: 6, 7, 9, 11, 14, 15, 16, 18, 19).

8. **`installment_account` is unreliable after Aug 2025.** The instalments feature was retired and the flag is being set to false during decommissioning. Use with caution; data is only reliable from March 2023 onwards.

9. **PII columns are masked by role.** Fields such as `email_address`, `first_name`, `last_name`, `date_of_birth`, `phone_number`, and address fields are subject to Snowflake masking policies. Ensure your role has the appropriate access before referencing them.

10. **`consumer_attributes` is an ARRAY type.** Use `ARRAY_CONTAINS('value'::VARIANT, consumer_attributes)` to filter by specific attribute. Do not use `=` or `LIKE`.

11. **Product mapping uses `QUALIFY` for deduplication.** When an account type's `reference_code` matches the product mapping, that row wins over a generic match — this prevents duplicate rows per account.