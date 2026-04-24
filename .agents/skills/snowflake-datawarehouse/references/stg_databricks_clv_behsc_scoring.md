## Overview

Detailed guidance for using `prod_analytics.prod_source.stg_databricks_ds_clv_behsc_scoring` table, including schema, business meaning, joins, and query examples.

---

## Keys
- One row per customer_id per obs_date. Each row represents the behavioural score and related features for a particular customer at a particular observation date.
- `customer_id`: Unique identifier for each customer. This is the primary key for the table.
- `obs_date`: The date for which the behavioural score is recorded.

---

## Important business rules
- The behavioural score is calculated based on various features derived from customer transaction and repayment history, account status, and other behavioural indicators. The score is designed to predict the customer's credit risk and likelihood of default.
- There are two underlying models for the behavioural score: one for customers in the Clean segment and another for customers not in the Clean segment. The `flag_clean` column indicates which model is used for scoring each customer.
- The `flag_exclusion` column indicates whether a customer was excluded from scoring due to certain criteria (e.g., insufficient data, recent account opening, etc.). Excluded customers will not have a valid behavioural score.
- The table only provides customer_id as the score is on customer level. To get account level score, join with `prod_analytics.prod_prep.dim_account` table on account_id to get the corresponding customer_id for each account, and then join with this table to get the behavioural score for each account. Note that one customer can have multiple accounts, and thus multiple rows in the final joined result.

---

## Common Query Patterns

### 1. Get an account's bscore on a specific date

```sql
SELECT 
    a.account_id,
    b.customer_id,
    b.obs_date,
    b.final_score as behavioural_score  
FROM PROD_ANALYTICS.prod_MART.dim_account a
JOIN PROD_ANALYTICS.prod_source.stg_databricks_ds_clv_behsc_scoring b
    ON lower(a.customer_id) = lower(b.customer_id)
WHERE a.account_id = 'specific_account_id'
    AND b.obs_date = 'specific_date';
```