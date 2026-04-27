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

The comment column is particularly useful as it provides the business meaning of the column, which can help analysts understand how to use the column in their analysis.

Also notice that some table reference markdown file also provides a Table Schema section. If the comment column in the table schema returned by the DESC TABLE command is not descriptive enough, you can refer to the Table Schema section in the reference markdown file for more detailed descriptions of the columns.

---

## Key Tables in the Data Warehouse

Note that for each table below, there is a reference markdown file that provides more detailed information about the table, including its schema, key columns, and example queries. You should dynamically refer to the needed markdown files for a deeper understanding of the target table and how to use it effectively in your analysis.

### dim_underwriting_bank_model_validation
- Full name: `prod_analytics.prod_prep.dim_underwriting_bank_model_validation`
- Description: This table contains the bank score model output and related features used for origination and limit increase applications. It includes the latest bank score, the legacy bank score, and key features used in the 2022 bank score model.
- Reference: `references/dim_underwriting_bank_model_validation.md`

### cli_daily_monitoring_reporting
- Full name: `prod_analytics.prod_mart.cli_daily_monitoring_reporting`
- Description: This table contains records per credit limit increase application per rule.
- Best for: Monitoring credit limit increase applications, generating monitoring reports and key metrics, and analyzing application trends.
- Reference: `references/cli_daily_monitoring_reporting.md`

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