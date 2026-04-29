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

## Hard table policy

Only use tables that are explicitly listed in the "Key Tables in the Data Warehouse" section below and have an existing reference markdown file.

Do not search for or discover additional warehouse tables with SHOW, LIST, INFORMATION_SCHEMA, ACCOUNT_USAGE, naming guesses, or inferred table names. If none of the referenced tables covers the requested business logic, ask the user which table reference should be added or confirmed.

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

### common_account_application_details
- Full name: `prod_analytics.prod_mart.common_account_application_details`
- Description: The **central AU application-level mart table** — one row per consumer that has started an application. It combines application metadata, underwriting decisions, credit bureau data, banking statement features, account lifecycle metrics, and cross-product behavioural signals into a single wide table.
- Best for: Get application-level information for a particular consumer.
- Reference: `references/common_account_application_details.md`

### dim_account
- Full name: `prod_analytics.prod_prep.dim_account`
- Description:  The **primary account dimension** in Zip's Snowflake analytics platform. It provides the **current state** of every account across all AU and NZ products (Zip Pay, Zip Money, Zip Plus, Zip Biz, Zip Personal Loan).
- Best for: Get account-level information for a particular account. This table can also be used to get customer-to-account relationships (e.g. linked accounts, parent/child accounts).
- Reference: `references/dim_account.md`

### risk_credit_changes
- Full name: `prod_analytics.prod_mart.risk_credit_changes`
- Description: This is a daily-refreshed mart table that contains the **complete history of credit limit changes** across all Zip products (Zip Pay, Zip Money, Zip Plus). Each row represents a single credit limit change event — either a Credit Limit Decrease (CLD) or Credit Limit Increase (CLI) — for a customer account.
- Best for: Analyzing credit changes and their impact on account behavior and risk profiles.
- Reference: `references/risk_credit_changes.md`

### stg_dca_collections_portfolio
- Full name: `prod_analytics.prod_source.stg_dca_collections_portfolio`
- Description: This is a **monthly incremental snapshot** of all accounts eligible for — or currently under — referral to a Debt Collection Agency (DCA). It is the single source of truth for monthly DCA referral decisions across all Australian Zip products.
- Best for: Analyzing external collection agency's (DCA) collections performance and tracking delinquent accounts.
- Reference: `references/stg_dca_collections_portfolio.md`

### fct_order
- Full name: `prod_analytics.prod_prep.fct_order`
- Description: This is the **primary fact table for purchase/order analysis** at Zip. Each row represents a single customer order (one transaction at one merchant), covering all Zip products and all checkout channels — online, in-store, VCN (virtual card), gift cards, bill payments, and Tap & Zip.
- Best for: Analyzing purchase/order patterns and customer behavior.
- Reference: `references/fct_order.md`

### stg_zmdb_consumer_attribute_history
- Full name: `prod_analytics.prod_source.stg_zmdb_consumer_attribute_history`
- Description: This is an **SCD Type 2 (Slowly Changing Dimension)** staging table that tracks the full historical record of attributes assigned to consumers in the ZipMoney platform (ZMDB). It is built from the source `zm_consumerattribute` table via Airbyte CDC, and is refreshed **hourly**.
- Best for: Use this table when you need **point-in-time** or **historical** attribute analysis. For current-state-only queries, prefer the non-history sibling: `prod_source.stg_zmdb_consumer_attribute` (a view that wraps this table, filtering for active records only).
- Reference: `references/stg_zmdb_consumer_attribute_history.md`

---

## Gocha
1. when using DAYOFWEEK() to extract day of week, note that in Snowflake, Sunday is 0 and Saturday is 6.
