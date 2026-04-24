## Overview

Detailed guidance for using `prod_analytics.prod_mart.zm_cli_daily_monitoring_reporting`, including schema, business meaning, joins, and query examples.

---

## Keys
- One row per credit limit increase request per decisioning rule result. This means a single CLI request may have multiple rows if multiple rules were evaluated.
- `cli_id` (same as `credit_profile_limit_update_id`): Unique identifier for each credit limit increase application. This is the primary key for the table.
- `rule_id`: Unique identifier for each rule evaluated for the CLI application. Since each application can have multiple rules evaluated, this is not a unique key in the table.
- `rule_result_id`: Unique identifier for each rule result. Since each CLI application can have multiple rules evaluated, this is not a unique key in the table.

To get unique CLI requests, use:
```sql
SELECT DISTINCT 
    credit_profile_limit_update_id
FROM PROD_ANALYTICS.prod_MART.zm_cli_daily_monitoring_reporting;
```

---

## Important business rules
- Each rule is linked to the corresponding application. The rule's result can be found from column `STATUS` (numeric) or `STATUS_STR` (string). Each rule has a name `RULE_NAME` and the belonging module `MODULE_DESCRIPTION`.
- Some rules are declined rules, that is, if an application hits any declined rules, the `STATUS_STR` is 'Decline', the application is auto declined. Some rules are referred rules. When the refer rules are hit the `STATUS_STR` is 'Refer'. Normally any hit refer rule has a negative `RULE_SCORE`. If an application hits no declined rules but some referred rules, the total `RULE_SCORE` will be summed. If the final summed rule score is < 350, that is, if the application hits more than three refer rules with -100 scores, the application is also auto declined. Else the application is referred for manual decisioning.
- The `RESULT` column contains the description of the run result of an individual rule. Unfortunately the result is description rather than numerical so regular expression is needed to extract the numeric result. For example, 'NumberOfPayDayLoansJson' rule has result like 'The Applicant has 5 SACC'. Regular expression is needed to extract numeric value 5 to tell how many SACC loan does the applicant has. The 'DecisioningMicroServiceCheckBankAndBehaviorScore' rule's result is 'BankScore 0.11942658865124513 is less than 0.0333 and bigger (or equal) than 0.052'. Regular expression is needed to extract the BankScore value from this description. Two important numeric rule results have already been extracted and saved as columns for use: `BANK_SCORE` is the bank score grades for the application and `MONTHLY_INCOME_BUCKET` is the monthly income in buckets.
- Some rules may result in 'Refer' but the rule_score is 0. These rules are on listen mode and shouldn't be considered as real refer rules. Only the rules that result in 'Refer' status AND has a negative rule_score should be treated as actual refer rules.

---

## Key metrics
- Total number of CLI applications, aka through-the-door (TTD) applications
- Number of applications pending for decisioning
- Number of decisioned applications
- Number of approved applications: approved + accepted
- Number of accepted applications: exclude approved but not accepted ones
- Number of approved applications: exclude accpeted ones
- Number of declined applications: auto declines + manual declines
- Number of auto decisioned applications: auto approved&accepted + auto declined
- Number of auto approved applications: auto approved + auto accepted
- Number of auto declined applications
- Number of referred decisioned applications: referred approved&accepted + referred declined
- Number of referred approved applications: referred approved&accepted
- Number of referred declined applications
- Auto approval rate: auto approved / auto decisioned
- Refer approval rate: referred approved / referred decisioned
- Automation rate: auto decisioned / total number of applications
- Overall approval rate: total approved / total number of applications
- Acceptance rate: accepted (exclude approved not accepted) / (approved+accepted)
- Limit increased: requested limit - initial limit

---

## Important Filtering Considerations

**Date Range:** The model filters data with `submit_time_stamp >= '2026-02-27'` (note: this appears to be a future date and may be a typo in the model - verify the intended start date)

**Product Filter:** Only includes records where `product = 'Zip Money'`

**CLI Eligibility:** Only includes records where `initial_credit_limit < requested_credit_limit` (actual increase requests)

---

## Common Query Patterns

### 1. Daily CLI Volume by Outcome

```sql
SELECT 
    submit_date,
    cl_category,
    COUNT(distinct cli_id) as cli_count,
    SUM(requested_credit_limit - initial_credit_limit) as total_increase_requested
FROM PROD_ANALYTICS.prod_MART.zm_cli_daily_monitoring_reporting
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
```

### 2. Auto vs Manual Decisioning Rate

When calculating decisioning rates, exclude the pending applications:

```sql
SELECT 
    submit_date,
    COUNT(distinct case when flag_auto_decisioned = 1 then cli_id end) as auto_decisions,
    COUNT(distinct case when flag_manual_decisioned = 1 then cli_id end) as manual_decisions,
    ROUND(100.0 * auto_decisions / COUNT(distinct cli_id), 2) as auto_decision_rate_pct
FROM PROD_ANALYTICS.prod_MART.zm_cli_daily_monitoring_reporting
where flag_pending = 0
GROUP BY 1
ORDER BY 1 DESC;
```

### 3. Rule Performance Analysis

```sql
SELECT 
    rule_name,
    status_str,
    COUNT(distinct cli_id) as rule_executions,
    AVG(rule_score) as avg_score
FROM PROD_ANALYTICS.prod_MART.zm_cli_daily_monitoring_reporting
WHERE rule_name IS NOT NULL
GROUP BY 1, 2
ORDER BY 3 DESC;
```

### 4. Approval Rate by Risk Segment

```sql
SELECT 
    bscore_grade,
    time_on_book,
    COUNT(distinct cli_id) as total_applications,
    COUNT(distinct case when flag_approved = 1 then cli_id end) as approved_count,
    ROUND(100.0 * COUNT(case when flag_approved = 1 then cli_id end) / COUNT(distinct cli_id), 2) as approval_rate_pct
FROM PROD_ANALYTICS.prod_MART.zm_cli_daily_monitoring_reporting
GROUP BY 1, 2
ORDER BY 1, 2;
```

### 5. Repeat CLI Behavior (Last 6 Months)

```sql
SELECT 
    CASE WHEN flag_applied_cli_l6m = 1 THEN 'Repeat Applicant(L6M)' ELSE 'First Time(L6M)' END as applicant_type,
    count(distinct case when flag_approved = 1 then cli_id end) as num_applications_approved,
    count(distinct case when flag_declined = 1 then cli_id end) as num_applications_declined,
    COUNT(distinct cli_id) as num_applications_total
FROM PROD_ANALYTICS.prod_MART.zm_cli_daily_monitoring_reporting
GROUP BY 1;
```