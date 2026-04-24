---
name: snowflake-datawarehouse
description: This skill provides an overview of the key data warehouse tables, their descriptions, and links to detailed skills for each table. It serves as a guide for analysts and data scientists to understand the available data sources and how to utilize them effectively in their analyses.
---

## How to get table schema

Run the following sql query to get the schema of a specific table:

```sql
DESC TABLE <full_table_name>;
```

It returns a table containing the following key columns:
- name: column name
- type: data type of the column
- null?: whether the column can contain null values
- comment: the descriptions of the column

---

## Key Tables in the Data Warehouse

### dim_underwriting_bank_model_validation
- Full name: `prod_analytics.prod_prep.dim_underwriting_bank_model_validation`
- Description: This table contains the bank score model output and related features used for origination and limit increase applications. It includes the latest bank score, the legacy bank score, and key features used in the 2022 bank score model.
- Reference: `references/dim_underwriting_bank_model_validation.md`

### zm_cli_daily_monitoring_reporting
- Full name: `prod_analytics.prod_mart.zm_cli_daily_monitoring_reporting`
- Description: This table contains each credit limit increase application as a record, with key information such as consumer_id, application_id, product, submission_time, and the latest bank score.
- Best for: Monitoring credit limit increase applications, generating monitoring reports and key metrics, and analyzing application trends.
- Reference: `references/zm_cli_daily_monitoring_reporting.md`

### fct_repayment_request
- Full name: `prod_analytics.prod_prep.fct_repayment_request`
- Description: This table contains one record for each repayment request, including both successful and failed requests. Key fields include account_id, consumer_id, repayment_request_id, product, request_time, amount, and status of the repayment request.
- Best for: Repayment related query and analysis, analyzing repayment patterns, tracking repayment requests, and generating reports on repayment activity.
- Reference: `references/fct_repayment_request.md`

### stg_batchoperations_account_daily_summary
- Full name: `prod_analytics.prod_source.stg_batchoperations_account_daily_summary`
- Description: The table contains daily snapshot data (account status, arrears days aka days past due or DPD, arrears balance, net balance, loan limit) of all accounts.
- Best for: Tracking account status and delinquency status over time. It can be used for daily account arrears analysis.
- Reference: `references/stg_batchoperations_account_daily_summary.md`

### stg_databricks_ds_clv_behsc_scoring
- Full name: `prod_analytics.prod_source.stg_databricks_ds_clv_behsc_scoring`
- Description: The table contains daily snapshot data of CLV (Customer level view) behaviour score (sometimes written as b-score or bscore).
- Best for: Get a CLV bscore for a particular customer (customer_id) at a particular date (obs_date). It can be used for customer behaviour analysis and CLV related analysis.
- Reference: `references/stg_databricks_ds_clv_behsc_scoring.md`

---

## Gocha
1. when using DAYOFWEEK() to extract day of week, note that in Snowflake, Sunday is 0 and Saturday is 6.