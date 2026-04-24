## Overview

Detailed guidance for using `prod_analytics.prod_source.stg_batchoperations_account_daily_summary`, including schema, business meaning, joins, and query examples.

---

## Key Features

### Primary Key
- SURROGATE_KEY : Generated using MD5 hash of account_id and arrears_date
- (ACCOUNT_ID, ARREARS_DATE) tuple: unique on these two columns together

### Incremental Strategy
- Incremental Field: data_loaded_timestamp (sourced from _airbyte_extracted_at )
- Lookback: 1 day
- Schema Change Handling: sync_all_columns - automatically syncs new columns

---

## Usage Notes

### When to Use This Model
- Daily account arrears analysis
- Tracking account payment behavior over time
- Monitoring accounts with payment issues
- Historical arrears trend analysis

### Important Considerations
1. Daily Granularity : This model provides a daily snapshot of account arrears
2. Incremental Updates : New data is appended based on the Airbyte extraction timestamp
3. Historical Backfill : On full refresh, includes historical data from stg_backfill_zip_account_daily_summary for dates before 2022-08-23
4. Surrogate Key : Each unique combination of account_id and arrears_date creates one record

### How to check whether an account is in arrears or not on a given snapshot date:

1. If account_status = 5, then the account is written-off (WO). WO accounts are considered in arrears with Days Past Due (DPD) at least 180.
2. Otherwise we should use this condition to tell whether an account is in arrears or not: account_status = 7 AND arrears_days > 0 AND arrears_balance > 0 AND arrears_balance <= net_balance. If account is in arrears, take the arrears_days value as the Days Past Due (DPD) value.

### How to create DPD buckets

#### For product_id 1 (Zip Pay) and 7 (Zip Plus)

```sql
select 
    batch.*,
    case when batch.account_status = 5 then 'a.WO'
         when batch.account_status <> 4 and batch.arrears_balance <= 0 then 'b.Current'
         when batch.account_status <> 4 and (batch.arrears_balance > 0 and batch.arrears_balance <= 25) then 'c.Arrears_Balance<=25'
         when batch.account_status <> 4 and (batch.arrears_balance > 25 and batch.arrears_days <= 0) then 'd.DPD<=0&Arrears_Balance>25'
         when batch.account_status <> 4 and batch.arrears_balance > 25 and datediff('month', dateadd('day', -batch.arrears_days, batch.arrears_date), dateadd(day, -1, batch.arrears_date)) = 1 then 'f.1MPD' -- Need to compare the actual month-end date
         when batch.account_status <> 4 and batch.arrears_balance > 25 and datediff('month', dateadd('day', -batch.arrears_days, batch.arrears_date), dateadd(day, -1, batch.arrears_date)) = 2 then 'g.2MPD'
         when batch.account_status <> 4 and batch.arrears_balance > 25 and datediff('month', dateadd('day', -batch.arrears_days, batch.arrears_date), dateadd(day, -1, batch.arrears_date)) = 3 then 'h.3MPD'
         when batch.account_status <> 4 and batch.arrears_balance > 25 and datediff('month', dateadd('day', -batch.arrears_days, batch.arrears_date), dateadd(day, -1, batch.arrears_date)) = 4 then 'i.4MPD'
         when batch.account_status <> 4 and batch.arrears_balance > 25 and datediff('month', dateadd('day', -batch.arrears_days, batch.arrears_date), dateadd(day, -1, batch.arrears_date)) = 5 then 'j.5MPD'
         when batch.account_status <> 4 and batch.arrears_balance > 25 and datediff('month', dateadd('day', -batch.arrears_days, batch.arrears_date), dateadd(day, -1, batch.arrears_date)) = 6 then 'k.6MPD'
         when batch.account_status <> 4 and batch.arrears_balance > 25 and datediff('month', dateadd('day', -batch.arrears_days, batch.arrears_date), dateadd(day, -1, batch.arrears_date)) >= 7 then 'l.>=7MPD'
         when batch.account_status <> 4 and batch.arrears_balance > 25 and batch.arrears_days > 0 then 'e.XMPD'
    end as dpd_bucket
from prod_source.stg_batchoperations_account_daily_summary batch
```

#### For product_id 2 (Zip Money) and 8 (Zip Personal Loan)

```sql
select 
    batch.*,
    case when batch.account_status = 5 then 'a.WO'
         when batch.account_status <> 4 and batch.arrears_balance <= 0 then 'b.Current'
         when batch.account_status <> 4 and (batch.arrears_balance > 0 and batch.arrears_balance <= 25) then 'c.Arrears_Balance<=25'
         when batch.account_status <> 4 and (batch.arrears_balance > 25 and batch.arrears_days <= 0) then 'd.DPD<=0&Arrears_Balance>25'
         when batch.account_status <> 4 and batch.arrears_balance > 25 and batch.arrears_days between 1 and 30 then 'e.01-30DPD'
         when batch.account_status <> 4 and batch.arrears_balance > 25 and batch.arrears_days between 31 and 60 then 'f.31-60DPD'
         when batch.account_status <> 4 and batch.arrears_balance > 25 and batch.arrears_days between 61 and 90 then 'g.61-90DPD'
         when batch.account_status <> 4 and batch.arrears_balance > 25 and batch.arrears_days between 91 and 120 then 'h.91-120DPD'
         when batch.account_status <> 4 and batch.arrears_balance > 25 and batch.arrears_days between 121 and 150 then 'i.121-150DPD'
         when batch.account_status <> 4 and batch.arrears_balance > 25 and batch.arrears_days between 151 and 180 then 'j.151-180DPD'
         when batch.account_status <> 4 and batch.arrears_balance > 25 and batch.arrears_days between 181 and 360 then 'k.181-360DPD'
         when batch.account_status <> 4 and batch.arrears_balance > 25 and batch.arrears_days > 360 then 'l.>360DPD'
    end as dpd_bucket
from prod_source.stg_batchoperations_account_daily_summary batch
```

---

## Example Query

### 1.This query retrieves accounts with arrears in the last 30 days, ordered by most recent date and highest arrears days.
```sql
SELECT
    account_id,
    arrears_date,
    arrears_days,
    arrears_balance,
    net_balance,
    account_status,
    loan_status
FROM PROD_ANALYTICS.prod_SOURCE.stg_batchoperations_account_daily_summary
WHERE arrears_date >= CURRENT_DATE - 30 AND arrears_days > 0 AND arrears_balance > 0 AND arrears_balance >= net_balance
ORDER BY arrears_date DESC, arrears_days DESC;
```