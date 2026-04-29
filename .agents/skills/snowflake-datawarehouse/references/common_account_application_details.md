## Overview

`PROD_MART.COMMON_ACCOUNT_APPLICATION_DETAILS` is the **central AU application-level mart table** — one row per consumer that has started an application. It combines application metadata, underwriting decisions, credit bureau data, banking statement features, account lifecycle metrics, and cross-product behavioural signals into a single wide table.

| Property | Value |
|---|---|
| **Full path** | `PROD_ANALYTICS.PROD_MART.COMMON_ACCOUNT_APPLICATION_DETAILS` |
| **Grain** | One row per `consumer_id` (unique, not null) |

> **All applications that were ever started are included**, not just approved or registered ones. Use `flag_*` and timestamp columns to filter to the population you need.

---

## Primary Key

| Column | Type | Notes |
|---|---|---|
| `consumer_id` | INTEGER | Unique, not null. One row per consumer. |

> **Important:** Because the grain is `consumer_id`, a consumer with multiple applications across products appears **once**. The table reflects the most recent application state for that consumer. When you need per-application granularity, join back to `dim_account_application` on `application_id`.

---

## Column Catalogue

### 1. Identifiers

| Column | Description |
|---|---|
| `consumer_id` | Primary key. Zip internal consumer identifier. |
| `application_id` | The application record ID from the monolith. |
| `customer_id` | The customer identifier (may differ from consumer_id for migrated accounts). |
| `account_id` | The account ID (populated once an account is provisioned). |

---

### 2. PII — Sensitive Data Masked 🔒

These columns have `masking_policy: sensitive_data` applied. Values are obfuscated for non-privileged roles.

| Column |
|---|
| `email_address` |
| `current_phone_number` |
| `first_name` |
| `last_name` |

---

### 3. Demographics

| Column | Description |
|---|---|
| `country` | Customer country (AU for this table). |
| `gender` | Customer gender. |
| `date_of_birth` | Date of birth. |
| `age` | Age calculated from `date_of_birth` and `application_timestamp`. |
| `state` | Australian state. |

---

### 4. Product & Account Status

| Column | Description |
|---|---|
| `product` | Zip product: `Zip Pay`, `Zip Money`, `Zip Plus`, `Zip Personal Loan`. |
| `account_type` | Account type classification. |
| `account_status` | Current account status (e.g. `Registered`, `Closed`, `Cancelled`). |
| `account_status_reason` | Reason for current account status. |
| `credit_profile_state` | Credit profile state from the monolith (e.g. `ApplicationCompleted`, `Registered`, `Inactive`). |
| `application_flow` | The application flow/journey type. |
| `current_application_section` | The section the application was in when last updated. |
| `current_application_section_timestamp` | Timestamp of the last application section update. |

---

### 5. Credit Terms

| Column | Description |
|---|---|
| `credit_limit` | Approved credit limit at registration. |
| `requested_credit_limit` | Credit limit requested by the applicant. |
| `first_credit_limit` | First ever credit limit assigned. |
| `loan_term` | Loan term in months (ZM / ZPlus / ZPL). |
| `interest_rate` | Interest rate applied. |
| `loan_purpose` | Declared loan purpose (ZM / ZPL). |

---

### 6. Income & Employment

| Column | Description |
|---|---|
| `annual_income` | Applicant declared annual income. |
| `residential_status` | Declared residential status (e.g. renting, mortgage). |
| `employment_status` | Declared employment status. |
| `verified_monthly_income` | Verified monthly income from banking analysis. |
| `verified_monthly_salary` | Verified salary portion of verified income. |
| `verified_monthly_benefits` | Verified benefits portion of verified income. |
| `post_refer_income` | Income as adjusted by the underwriter post-referral. |
| `post_refer_capacity` | HEM capacity as adjusted by the underwriter post-referral. |
| `underwriting_capacity` | HEM capacity at auto-decisioning. |
| `declared_income_at_specified_frequency` | Declared income at the stated frequency. |
| `income_frequency` | Declared income frequency: Annual, Weekly, Fortnightly, Monthly. |
| `monthly_salary_income` | Monthly income from salary only. |
| `total_monthly_income_from_salary_and_other` | Total monthly income from salary and other sources. |
| `monthly_salary_credits_in_banking` | Monthly salary credits derived from banking statement. |
| `monthly_benefits_credits_in_banking` | Monthly benefits credits derived from banking statement. |
| `monthly_other_credits_in_banking` | Monthly other credits derived from banking statement. |
| `MONTHS_AT_CURRENT_EMPLOYER` | Declared months at current employer. |
| `UNEMPLOYED_DECLARED_OR_INFERED` | Customer is unemployed — declared or inferred via banking. |
| `hem_expense` | HEM (Household Expenditure Measure) expense used in decisioning. |
| `capacity_using_banking_income_for_ZP` | Capacity for ZP applications using banking income. |

---

### 7. Application Lifecycle Timestamps

> All timestamps are UTC. A `NULL` means that state was never reached.

| Column | Description |
|---|---|
| `application_timestamp` | When the application was created (started). |
| `application_month` | Month-truncated date of `application_timestamp`. Use for efficient date-range filtering instead of `DATE_TRUNC()`. |
| `application_in_progress_timestamp` | When the application entered in-progress state. |
| `submission_timestamp` | When the application was submitted for decisioning. |
| `referred_timestamp` | When the application was referred to underwriting. |
| `verified_timestamp` | When identity was verified. |
| `verified_identity_timestamp` | Verified identity specific timestamp. |
| `verified_social_timestamp` | Verified social specific timestamp. |
| `approved_timestamp` | When the application was approved. |
| `declined_timestamp` | When the application was declined. |
| `registered_timestamp` | When the account was registered (activated). |
| `cancelled_timestamp` | When the application was cancelled. |
| `expired_timestamp` | When the application expired. |
| `write_off_timestamp` | When the account was written off. |
| `provision_request_timestamp` | When VCN provisioning was requested. |
| `provision_success_timestamp` | When VCN provisioning succeeded. |
| `first_transaction_timestamp` | Timestamp of first captured transaction. |
| `first_mobile_app_timestamp` | Timestamp of first mobile app usage. |
| `banking_detail_timestamp` | When banking details were submitted. |
| `staff_action_timestamp` | When a staff member opened and actioned the application. |
| `risk_fraud_timestamp` | When the account was flagged for fraud. |
| `risk_nfd_timestamp` | When the account entered NFD (Not For Distribution) status. |

Section-level timestamps (when each step of the application funnel was completed):
`timestamp_limitselection`, `timestamp_profile`, `timestamp_identification`, `timestamp_banking`, `timestamp_acknowledgement`, `timestamp_smsverification`, `timestamp_paymentmethod`, `timestamp_documentverification`, `timestamp_bankverification`, `timestamp_productselect`, `timestamp_contract`, `timestamp_dateofbirth`, `timestamp_businessdetails`

---

### 8. Application Flags

All flag columns are `0` / `1` integers (boolean).

| Column | Description |
|---|---|
| `flag_submitted` | Application was submitted. |
| `flag_referred` | Application was referred to underwriting. |
| `flag_automated` | Application was auto-decisioned (not manually reviewed). |
| `flag_approved` | Application was approved. |
| `flag_declined` | Application was declined. |
| `flag_registered` | Account was registered. |
| `flag_application_with_checkout` | Application was linked to a merchant checkout. |
| `flag_cancelled_inaction` | Application was cancelled due to inaction. |
| `flag_exclusive_origination_merchant` | Application originated at an exclusive merchant. |
| `flag_existing_account_holder` | Customer already holds an account at time of application. |
| `flag_bank_connection` | Banking was connected (open banking). |
| `flag_new_to_bureau` | Customer has no prior credit file. |
| `flag_idmatrix` | IDMatrix was run. |
| `flag_idmatrix_approve` | IDMatrix returned approve. |
| `flag_idmatrix_reject` | IDMatrix returned reject. |
| `flag_idmatrix_decline` | IDMatrix returned decline. |
| `flag_contract_variation_ever` | Account ever had a contract variation. |
| `flag_cld_ever` | Account ever had a CLD (Credit Limit Decrease). |
| `flag_decline_income` | Application declined due to `CheckIncome` rule. |
| `flag_decline_employment` | Application declined due to `EmploymentStability` rule. |

---

### 9. Underwriting & Risk Scores

| Column | Description |
|---|---|
| `bureau_score` | Veda/Equifax credit score at time of application. |
| `business_eca_score` | Business ECA score. |
| `model_score` | Primary model score used in decisioning. |
| `model_name` | Name of the decisioning model. |
| `policy_name` | Credit policy applied. |
| `high_risk_rule` | High-risk rule that triggered (if any). |
| `module_decline_reason` | Module that triggered decline. |
| `rule_decline_reason` | Specific rule that triggered decline. |
| `bank_score` | Bank statement model score. |
| `bank_rating` | Bank statement model risk rating. |
| `application_rating` | Application model risk rating. |
| `combined_application_and_bank_rating` | Combined rating from application and bank models. |
| `risk_score` | Overall risk score. |
| `dun_and_bradstreet_score` | D&B score (business applications). |
| `identity_score_total` | Total identity score. |
| `risk_score_total` | Total risk score. |
| `underwriting_model_bad_flag` | Model-predicted bad flag. |
| `Decision_by_UW` | Was the final decision made by a human underwriter? |
| `decline_rules_triggered` | List of all decline rules triggered. |
| `refer_rules_triggered` | List of all refer rules triggered. |
| `downsell_rules_triggered` | List of all downsell rules triggered. |
| `rds_bank_score_2022` | RDS validation — bank model 2022 score. |
| `rds_bank_score_2020` | RDS validation — bank model 2020 score. |
| `rds_zp_app_score_2022` | RDS validation — ZP app model 2022 score. |
| `rds_zp_app_score_2020` | RDS validation — ZP app model 2020 score. |
| `rds_zm_app_score_2022` | RDS validation — ZM app model 2022 score. |
| `latest_credit_score_at_time_of_UW` | Latest credit score at the time of underwriting. |
| `date_latest_credit_score_from` | Date of the latest credit score used. |
| `hem_used_for_auto_appr` | Whether HEM was considered for auto approval (ZM/ZPlus only). |

Behavioural score lists (arrays of historical scores):

| Column | Description |
|---|---|
| `clv_scores_list` | CLV behavioural scores as a list. |
| `clv_scores_lag_list` | Lagged CLV behavioural scores as a list. |
| `clv_raw_scores_list` | CLV raw scores as a list. |
| `clv_raw_scores_lag_list` | Lagged CLV raw scores as a list. |
| `zplus_scores_list` | Zip Plus bscores as a list. |
| `zp_scores_list` | Zip Pay bscores as a list. |
| `zp_x_prod_bscore_list_from_rule` | ZP cross-product bscores used in rule at decisioning. |
| `zm_x_prod_bscore_list_from_rule` | ZM cross-product bscores used in rule at decisioning. |
| `zplus_x_prod_bscore_list_from_rule` | Z+ cross-product bscores used in rule at decisioning. |
| `zploan_x_prod_bscore_list_from_rule` | ZPLoan cross-product bscores used in rule at decisioning. |

---

### 10. Veda Credit Bureau Fields

All `veda_*` columns are sourced from the Veda/Equifax credit file pulled at time of application.

| Column | Description |
|---|---|
| `veda_age_of_file_in_months` | Age of credit file in months. |
| `veda_months_at_address` | Months at current address per credit file. |
| `veda_months_at_employer` | Months at current employer per credit file. |
| `veda_no_defaults` | Total defaults on credit file. |
| `veda_total_value_of_outstanding_defaults` | Total value of outstanding defaults. |
| `veda_defaults_12` | Defaults in last 12 months. |
| `veda_no_defaults_12_unpaid` | Unpaid defaults in last 12 months. |
| `veda_no_defaults_24_unpaid` | Unpaid defaults in last 24 months. |
| `veda_no_defaults_36_unpaid` | Unpaid defaults in last 36 months. |
| `veda_no_defaults_12_paid` | Paid defaults in last 12 months. |
| `veda_months_since_last_default` | Months since last default. |
| `veda_total_no_credit_enquiries` | Total credit enquiries on file. |
| `veda_no_credit_enquiries_1` | Credit enquiries in last 1 month. |
| `veda_no_credit_enquiries_3` | Credit enquiries in last 3 months. |
| `veda_no_credit_enquiries_6` | Credit enquiries in last 6 months. |
| `veda_no_credit_enquiries_12` | Credit enquiries in last 12 months. |
| `veda_no_credit_enquiries_60` | Credit enquiries in last 60 months. |
| `veda_months_since_last_enquiry` | Months since most recent enquiry. |
| `veda_no_telco_and_utility_defaults` | TLU defaults on file. |
| `veda_no_telco_and_utility_enquiries` | TLU enquiries on file. |
| `veda_no_bankruptcies` | Number of bankruptcies. |
| `veda_no_writs_and_summons` | Number of writs and summons. |
| `veda_no_judgements` | Number of judgements. |
| `veda_adverse_on_file_yn` | Adverse factors on credit file: `Y` or `N`. |
| `veda_no_known_identities` | Number of known identities linked to the credit file. |
| `vedabanperiod` | Customer is within a Veda ban period. |
| `MONTHS_SINCE_LAST_NONTLU_DEFAULT` | Months since latest non-TLU default as of application. |
| `NO_MORTGAGE_ENQUIRIES` | Total mortgage credit enquiries ever. |
| `NO_MORTGAGE_ENQUIRIES_L1M` | Mortgage enquiries in last 1 month. |
| `NO_PAYDAY_ENQUIRIES` | Total payday credit enquiries ever. |
| `NO_PAYDAY_ENQUIRIES_L3M` | Payday enquiries in last 3 months. |
| `NO_PAYDAY_ENQUIRIES_L12M` | Payday enquiries in last 12 months. |
| `possible_match_files_indicator` | `Y` if a possible match credit file is present. |

---

### 11. Banking Statement Features

All `banking_*` columns are derived from open banking / Pocketbook / Illion statement analysis at time of underwriting.

**Aggregate flags:**

| Column | Description |
|---|---|
| `banking_no_dishonours` | Number of dishonours on banking statement. |
| `banking_no_sacc_dishonours` | Number of SACC dishonours on banking statement. |
| `banking_no_payday_loans` | Number of payday loans on banking statement. |
| `banking_value_of_debt_collections` | Value of debt collections on banking statement. |
| `banking_provider` | Third-party banking provider (e.g. Yodlee, Illion). |
| `Banking_First_date` | Earliest transaction date on statement. |
| `Banking_Last_date` | Latest transaction date on statement. |
| `total_credit_benefits` | Total benefits credits from banking statement. |
| `total_credit` | Total credits from banking statement. |
| `banking_Total_Value_of_Debits` | Total debit value across all categories. |
| `banking_Total_Value_of_Credits` | Total credit value across all categories. |
| `Available_Balance` | Available balance aggregated from bank account. |
| `number_of_months_banking` | Months of banking history on the statement. |

**Categorised debit & credit columns** follow the pattern `banking_{Category}_Debits` and `banking_{Category}_Credits`. Categories include (but are not limited to):

`ATM`, `Automotive`, `Centrelink`, `Childrens_Retail`, `Credit_Card_Repayments`, `Debt_Collection`, `Debt_Consolidation`, `Dining_Out`, `Dishonour`, `Education`, `Entertainment`, `Gambling`, `Grocery`, `Health`, `Insurance`, `Rent`, `SACC_Loan`, `Non_SACC_Loans`, `Superannuation`, `Telecommunications`, `Transport`, `Travel`, `Utilities`, `Wages`, `Other`

---

### 12. Cross-Product Fields

Prefix `ZPLUS_`, `ZM_`, `ZP_` indicate data for the customer's **other** Zip product accounts at time of application.

Key pattern (repeated for each prefix):

| Column Pattern | Description |
|---|---|
| `{PREFIX}_CONSUMER_ID` | Consumer ID in that product. |
| `{PREFIX}_SPOT_FRAUD_FLAG` | Currently flagged for fraud in the other product. |
| `{PREFIX}_SPOT_SUSP_FRAUD_FLAG` | Currently suspected fraud in the other product. |
| `{PREFIX}_EVER_FRAUD_FLAG` | Ever flagged for fraud in the other product. |
| `{PREFIX}_MAX_DAYS_DELQ_L12M` | Max days delinquent in last 12 months in the other product. |
| `{PREFIX}_SCORE` | Behavioural score in the other product. |
| `{PREFIX}_RISK_LEVEL` | Behavioural risk grade in the other product. |
| `{PREFIX}_PREDICTED` | Predicted probability of default from behavioural model. |
| `{zp/zm/zplus}_indicator_for_declined_app_l6m` | Declined application in last 6 months in that product. |

---

### 13. Attribution & Campaign

| Column | Description |
|---|---|
| `application_attribution` | Top-level attribution: `Marketing`, `Merchant`, or `Direct`. |
| `application_attribution_detail` | Detail: campaign name (Marketing), merchant name (Merchant), or `Direct - App` / `Direct - Web`. |
| `application_campaign_name` | Marketing campaign name. |
| `application_utm_campaign` | UTM campaign parameter. |
| `application_utm_source` | UTM source parameter. |
| `attribution_channel` | Attribution channel. |
| `attribution_partner_name` | Attribution partner name. |
| `attribution_campaign` | Attribution campaign. |
| `attribution_campaign_id` | Attribution campaign ID. |
| `attribution_agency` | Attribution agency. |
| `attribution_keyword` | Attribution keyword. |
| `attribution_timestamp` | Attribution event timestamp. |

---

### 14. Merchant & Origination

| Column | Description |
|---|---|
| `origination_merchant_id` | Merchant ID where the application originated. |
| `origination_merchant_name` | Merchant name at origination. |
| `origination_partner_type` | Partner type (e.g. `Bills`, `eComm`, `IRL`). |
| `origination_method` | Origination method. |
| `origination_branch_id` | Branch ID for in-store origination. |
| `inferred_origination_merchant_id` | Inferred merchant ID (from first transaction). |
| `inferred_origination_merchant_name` | Inferred merchant name. |
| `inferred_origination_merchant_industry` | Inferred merchant industry. |
| `inferred_origination_merchant_sub_category` | Inferred merchant sub-category. |

---

### 15. Financial Metrics (Post-Registration)

| Column | Description |
|---|---|
| `captured_amount` | Total transaction amount captured. |
| `captured_count` | Total number of captured transactions. |
| `captured_count_last_90_days` | Transactions captured in last 90 days. |
| `arrears_days` | Current arrears days. |
| `net_balance` | Current net balance. |
| `max_arrears_days` | Maximum arrears days ever. |
| `max_net_balance` | Maximum net balance ever. |
| `max_arrears_days_from_daily` | Max arrears days from daily data (more accurate than month-end). |
| `merchant_fee_amount` | Merchant fee revenue. |
| `transaction_fee_amount` | Transaction fee revenue. |
| `establishment_fee_amount` | Establishment fee charged. |
| `late_fee_amount` | Late fees charged. |
| `monthly_fee_amount` | Monthly account fees charged. |
| `instalment_extension_fee_amount` | Instalment extension fee revenue. |
| `interest_amount` | Interest charged. |
| `write_off_amount` | Amount written off. |
| `repayment_amount` | Total repayments made. |
| `vcn_interchange_revenue` | VCN interchange revenue. |
| `Bills_surcharge` | Merchant fees where partner type is Bills. |
| `ECL` | Expected Credit Loss amount. |
| `net_balance_for_ecl` | Net balance from the ECL model. |
| `ecl_date` | Date of last ECL model run. |
| `summed_net_bal` | Summed net balance for periods with outstanding limit (cost of funds). |
| `disbursement_time` | Time the underwriter disbursed funds to customer (ZM/ZPlus/ZPL). |

---

## Common Query Patterns

### Filter to a specific product and outcome

```sql
SELECT
    consumer_id,
    application_id,
    age,
    state,
    credit_limit,
    bureau_score,
    application_timestamp,
    registered_timestamp
FROM PROD_ANALYTICS.PROD_MART.COMMON_ACCOUNT_APPLICATION_DETAILS
WHERE product = 'Zip Money'
  AND flag_registered = 1
  AND application_timestamp >= '2024-01-01'
```

### Approval funnel analysis

```sql
SELECT
    product,
    DATE_TRUNC('month', application_timestamp)  AS month,
    COUNT(*)                                     AS applications,
    SUM(flag_submitted)                          AS submitted,
    SUM(flag_approved)                           AS approved,
    SUM(flag_declined)                           AS declined,
    SUM(flag_registered)                         AS registered,
    ROUND(SUM(flag_registered) / NULLIF(SUM(flag_submitted), 0) * 100, 2) AS conversion_rate_pct
FROM PROD_ANALYTICS.PROD_MART.COMMON_ACCOUNT_APPLICATION_DETAILS
WHERE application_timestamp >= DATEADD('month', -12, CURRENT_DATE)
GROUP BY 1, 2
ORDER BY 1, 2
```

### Credit risk profile of approved applicants

```sql
SELECT
    product,
    CASE
        WHEN bureau_score < 500  THEN '< 500'
        WHEN bureau_score < 600  THEN '500–599'
        WHEN bureau_score < 700  THEN '600–699'
        WHEN bureau_score < 800  THEN '700–799'
        ELSE '800+'
    END AS bureau_score_band,
    COUNT(*)                AS applicants,
    AVG(credit_limit)       AS avg_approved_limit,
    SUM(flag_registered)    AS registered
FROM PROD_ANALYTICS.PROD_MART.COMMON_ACCOUNT_APPLICATION_DETAILS
WHERE flag_approved = 1
  AND bureau_score IS NOT NULL
GROUP BY 1, 2
ORDER BY 1, 2
```

### Identify applications declined due to income

```sql
SELECT
    consumer_id,
    application_id,
    product,
    declined_timestamp,
    module_decline_reason,
    rule_decline_reason,
    annual_income,
    verified_monthly_income,
    employment_status
FROM PROD_ANALYTICS.PROD_MART.COMMON_ACCOUNT_APPLICATION_DETAILS
WHERE flag_declined = 1
  AND flag_decline_income = 1
  AND application_timestamp >= '2024-01-01'
```

### Banking risk indicators

```sql
SELECT
    consumer_id,
    product,
    banking_no_dishonours,
    banking_no_payday_loans,
    banking_no_sacc_dishonours,
    banking_value_of_debt_collections,
    banking_Gambling_Debits,
    total_credit,
    banking_Total_Value_of_Debits
FROM PROD_ANALYTICS.PROD_MART.COMMON_ACCOUNT_APPLICATION_DETAILS
WHERE flag_bank_connection = 1
  AND flag_submitted = 1
```

### Cross-product fraud signals

```sql
SELECT
    consumer_id,
    product,
    application_timestamp,
    ZPLUS_SPOT_FRAUD_FLAG,
    ZM_SPOT_FRAUD_FLAG,
    ZP_SPOT_FRAUD_FLAG,
    ZPLUS_EVER_FRAUD_FLAG,
    ZM_EVER_FRAUD_FLAG,
    ZP_EVER_FRAUD_FLAG
FROM PROD_ANALYTICS.PROD_MART.COMMON_ACCOUNT_APPLICATION_DETAILS
WHERE (
    ZPLUS_SPOT_FRAUD_FLAG = 1
    OR ZM_SPOT_FRAUD_FLAG = 1
    OR ZP_SPOT_FRAUD_FLAG = 1
)
```

### Attribution breakdown for new registrations

```sql
SELECT
    application_attribution,
    application_attribution_detail,
    product,
    COUNT(*)                AS registrations,
    AVG(credit_limit)       AS avg_limit
FROM PROD_ANALYTICS.PROD_MART.COMMON_ACCOUNT_APPLICATION_DETAILS
WHERE flag_registered = 1
  AND registered_timestamp >= DATEADD('month', -3, CURRENT_DATE)
GROUP BY 1, 2, 3
ORDER BY 4 DESC
```

### Look up a customer by email

```sql
-- Note: email_address is masked for non-privileged roles
SELECT
    consumer_id,
    customer_id,
    product,
    credit_profile_state,
    account_status,
    application_timestamp,
    registered_timestamp,
    credit_limit
FROM PROD_ANALYTICS.PROD_MART.COMMON_ACCOUNT_APPLICATION_DETAILS
WHERE email_address = 'customer@example.com'
```

---

## Joins to Other Tables

| Join target | Join key | Notes |
|---|---|---|
| `PROD_PREP.DIM_ACCOUNT_APPLICATION` | `application_id` | Per-application granularity (if needed). |
| `PROD_PREP.FCT_ORDER` | `account_id` | Order-level data. |

---


## Real-World Usage Patterns

### Approval rate by product and month

```sql
SELECT
    DATE_TRUNC('month', application_timestamp::DATE)     AS summary_month,
    product,
    SUM(flag_approved)
        / NULLIF(SUM(flag_approved) + SUM(flag_declined), 0) AS approval_rate
FROM PROD_ANALYTICS.PROD_MART.COMMON_ACCOUNT_APPLICATION_DETAILS
WHERE summary_month >= DATEADD('month', -36, CURRENT_DATE)
  AND product IN ('Zip Money', 'Zip Pay', 'Zip Plus', 'Zip Personal Loan')
GROUP BY 1, 2
ORDER BY 1, 2
```

### Registration rate (approved → registered conversion)

```sql
SELECT
    DATE_TRUNC('month', application_timestamp::DATE) AS month_dt,
    product,
    SUM(CASE WHEN registered_timestamp IS NOT NULL THEN 1 ELSE 0 END)  AS num_registered,
    SUM(CASE WHEN approved_timestamp  IS NOT NULL THEN 1 ELSE 0 END)   AS num_approved,
    SUM(CASE WHEN registered_timestamp IS NOT NULL THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN approved_timestamp IS NOT NULL THEN 1 ELSE 0 END), 0) AS registration_rate
FROM PROD_ANALYTICS.PROD_MART.COMMON_ACCOUNT_APPLICATION_DETAILS
WHERE country = 'AU'
  AND submission_timestamp IS NOT NULL
GROUP BY 1, 2
```

### Categorise declines by bureau score band

```sql
SELECT
    consumer_id,
    application_id,
    product,
    declined_timestamp,
    bureau_score,
    CASE
        WHEN bureau_score IS NULL  THEN '01. Declined prior to bureau pull'
        WHEN bureau_score < 450    THEN '02. High-risk — below 450'
        WHEN product = 'Zip Money'
             AND referred_timestamp IS NOT NULL THEN '03. Referred'
        WHEN bureau_score < 550    THEN '04. Medium-high risk 450–549'
        ELSE '99. Other'
    END                          AS decline_category,
    decline_rules_triggered
FROM PROD_ANALYTICS.PROD_MART.COMMON_ACCOUNT_APPLICATION_DETAILS
WHERE product IN ('Zip Personal Loan', 'Zip Money', 'Zip Plus', 'Zip Pay')
  AND country = 'AU'
  AND application_month >= DATEADD('month', -12, CURRENT_DATE)
  AND declined_timestamp  IS NOT NULL
  AND approved_timestamp  IS NULL
```

### Credit limit distribution for approved + registered applications

```sql
SELECT
    product,
    first_credit_limit,
    COUNT(*) AS applications
FROM PROD_ANALYTICS.PROD_MART.COMMON_ACCOUNT_APPLICATION_DETAILS
WHERE country = 'AU'
  AND flag_approved    = 1
  AND flag_registered  = 1
  AND application_month >= DATEADD('month', -36, CURRENT_DATE)
GROUP BY 1, 2
ORDER BY 1, 2
```

---

## Important Notes & Gotchas

1. **One row per consumer, not per application.** If you need application-level granularity (e.g. a customer with multiple product applications), join to `PROD_PREP.DIM_ACCOUNT_APPLICATION` on `application_id` instead of using this table directly.

2. **NZ customers are excluded.** Use `PROD_MART.COMMON_ACCOUNT_APPLICATION_DETAILS_NZ` for New Zealand data.

3. **All application states are included.** Abandoned, expired, and cancelled applications are in this table. Always apply appropriate `flag_*` or timestamp filters to restrict to your intended cohort.

4. **PII columns are masked.** `email_address`, `first_name`, `last_name`, `current_phone_number` require elevated data access roles. Queries against these columns will return masked values unless the correct Snowflake role is active.

5. **Banking features are only populated when banking was connected.** Filter by `flag_bank_connection = 1` before analysing `banking_*` columns, or null-check them.

6. **Cross-product fields reflect state at application time**, not current state. A `ZPLUS_SPOT_FRAUD_FLAG = 1` means the customer was flagged at the time they applied for the current product.

7. **Timestamps are UTC.** Convert to AEST (`AT TIME ZONE 'Australia/Sydney'`) for display or day-boundary analysis.

8. **Veda fields reflect the credit pull at application time**, not the customer's current credit file state.

9. **`max_arrears_days_from_daily` is preferred over `max_arrears_days`** for accurate arrears analysis — the comment in the source SQL notes it uses daily data rather than month-end snapshots.

10. **`ECL`, `net_balance_for_ecl`, `ecl_date`** reflect the most recent ECL model run, which may lag by up to one day.

11. **The table is materialised as a full table rebuild** on a large warehouse. For exploratory work, add `LIMIT` clauses or filter by `application_timestamp` to avoid full-table scans.