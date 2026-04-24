## Overview
Detailed guidance for using `prod_analytics.prod_prep.dim_underwriting_bank_model_validation` table, including schema, business meaning, joins, and query examples.

The table contains historical origination and credit limit increase applications and the bank scores generated at application time for the decisioning. The table can be used to retrieve application point bank scores and to evaluate bank score performance (Gini, KS, PSI, etc)

---

## Keys
- Unique key is `BANK_STATEMENT_REQUEST_ID`. For origination applications (`REASON`='Origination'), sometimes there can be more than one records. In this case, we can always take the one with the latest `SUBMISSION_TIME` as the final score record. For CLI applicaitons (`REASON`='LimitIncrease'), we don't have the limit increase ID to link to the limit increase record. The `APPLICATION_ID` for credit limit increase applications are still the origination application ID and cannot be used to identify the credit limit application.
- `APPLICATION_ID` is the unique identifier for origination applications. For CLI applications, this column still shows the origination application ID and cannot be used to identify the credit limit application.
- `CONSUMER_ID` is the unique identifier for the consumer. Note that CONSUMER_ID is not ACCOUNT_ID when joining with other tables.

---

## Important Filtering Considerations

**For 2022 bank score:** Only use the `BANK_SCORE_2022` and related features to evaluate the current bank score in production (version 2022). The 2020 bank score is a legacy one and is currently not in production. Refer to skill `bank_score_2022_model.md` for detailed model instruction for 2022 bank score model.

**Reason Filter:** To evaluate the model performance on origination applications, filter by `REASON` = 'Origination'. To evaluate model performance on limit increase applications, filter by `REASON` = 'LimitIncrease'.

---

## How to use this table

### 1. Get records for origination applications within last 3 months

```sql
SELECT 
    consumer_id,
    application_id,
    product,
    submission_time,
    bank_score_2022,
    bank_score_2020,
    bank_2022_num_tot_dishonours_l3m,
    bank_2022_amt_wages_l3m
FROM prod_prep.dim_underwriting_bank_model_validation
WHERE submission_time >= DATEADD(month, -3, CURRENT_DATE())
    AND product = 'Zip Money' AND reason = 'Origination'
ORDER BY submission_time DESC;
```

### 2. Get average bank score by product and reason within last 1 month

```sql
SELECT 
    product,
    reason,
    AVG(bank_score_2022) as avg_bank_score_2022,
    COUNT(*) as application_count
FROM prod_prep.dim_underwriting_bank_model_validation
WHERE submission_time >= DATEADD(month, -1, CURRENT_DATE())
GROUP BY product, reason
ORDER BY product, reason;
```

### 3. Dedup

Sometimes customer can submit bank statements more than once within one application. This results in multiple records with the same `application_id`. To dedup, we can always keep the bank score from the latest submission. Note that this is only applicable for origination applications. For limit increase applications, we cannot dedup by `application_id` as it is not the unique identifier of limit increase applications.

```sql
select
    *
from prod_prep.dim_underwriting_bank_model_validation
where reason = 'Origination'
qualify row_number() over (partition by application_id order by submission_time desc) = 1 
```

---

## Joining other tables

1. Not all applications got approved. If you want to review the performance of the bank score, you would need to filter out those applications that didn't convert to accounts. You can join with `prod_mart.common_account_application_details` table to get the details of the application and use `flag_registered` flag to tell whether the account has opened from the origination application or not:

```sql
select
    t0.*
from prod_prep.dim_underwriting_bank_model_validation t0
left outer join prod_mart.common_account_application_details t1 on t0.application_id = t1.application_id
where t0.reason = 'Origination' and t1.flag_registered = 1
;
```

2. If you need to get account performance data, you will need to join `prod_source.stg_batchoperations_account_daily_summary` table (refer to `stg_batchoperations_account_daily_summary,md` for more usage instruction). Note that `consumer_id` is not `account_id`. Although they both are unique account identifier, they are different things. In order to join with the `prod_source.stg_batchoperations_account_daily_summary` table to get account performance, you need to first get the `account_id` from the orignation `application_id`. This can be done by joining `prod_mart.common_account_application_details` table with `application_id`. Only the registered applications have valid `account_id`. Then you can join the `prod_source.stg_batchoperations_account_daily_summary` table with `account_id`:

```sql
select
    t0.*,
    t1.account_id,
    max(case when batch.account_status = 7 AND batch.arrears_balance > 0 AND batch.arrears_balance <= batch.net_balance then batch.arrears_days
             when batch.account_status = 5 then 180 end) as worst_dpd
from prod_prep.dim_underwriting_bank_model_validation t0
left outer join prod_mart.common_account_application_details t1 on t0.application_id = t1.application_id
left outer join prod_source.stg_batchoperations_account_daily_summary batch on t1.account_id = batch.account_id and batch.arrears_date >= to_date(t0.SUBMISSION_TIME)
where t0.reason = 'Origination' and t1.flag_registered = 1
;
```