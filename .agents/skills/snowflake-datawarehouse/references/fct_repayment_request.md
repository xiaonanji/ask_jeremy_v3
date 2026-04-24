## Overview
Detailed guidance for using `prod_analytics.prod_prep.fct_repayment_request` table, including schema, business meaning, joins, and query examples.

---

## Query Guidelines

### Primary Keys

- **REPAYMENT_REQUEST_ID**: Unique identifier for each repayment request (Primary key)

### Common Filters

- **REPAYMENT_STATUS**: Filter by 'Pending', 'Captured', or 'Failed'
  - status = 'Captured' for successful payments
  - status = 'Failed' for failed payments
  - status = 'Pending' for in-progress payments
- **REPAYMENT_REASON**: Common values include 'Scheduled', 'Arrears', 'Additional', 'Refund', 'Retry', 'Pay Now', 'Copayment', 'Dormant Card Check'
- **REPAYMENT_SOURCE**: Values include
  - 'RDS Run Repayment': Company auto direct debit arrears repayments, sometimes called `R-runs`
  - 'LTA (Direct)'
  - 'ARMA': this is an external Debt Collection Agent (DCA). If a payment source is marked as this, it means the payment is a collection from this agent.
  - 'Indebted': this is another external Debt Collection Agent (DCA)
  - 'Debt Agreements (Part IX)'
  - 'Direct (Other)'
- **PRODUCT**: Filter by Zip product: 'Zip Pay', 'Zip Money', 'Zip Plus'
- **REPAYMENT_GATEWAY**: Gateway provider:
  - 'Adyen'
  - 'Fat Zebra'
  - 'Flo2Cash'
  - 'Stripe'
  - 'Not Set'

### Date Filtering
Use `REPAYMENT_REQUEST_TIMESTAMP_LTZ` for time-based analysis:

```sql
-- Last 30 days
WHERE REPAYMENT_REQUEST_TIMESTAMP_LTZ >= DATEADD(day, -30, CURRENT_DATE())

-- Specific date range
WHERE REPAYMENT_REQUEST_TIMESTAMP_LTZ BETWEEN '2024-01-01' AND '2024-01-31'

-- Current month
WHERE DATE_TRUNC('month', REPAYMENT_REQUEST_TIMESTAMP_LTZ) = DATE_TRUNC('month', CURRENT_DATE())
```

### Amount Analysis
- `REPAYMENT_AMOUNT`: Use for sum, average, or aggregate calculations
- Consider filtering out refunds if analyzing revenue:

```
WHERE REPAYMENT_REASON != 'Refund'
```

### Success vs Failure Analysis

```sql
-- Successful payments only
WHERE REPAYMENT_STATUS = 'Captured'

-- Failed payments with categorized reasons
WHERE REPAYMENT_STATUS = 'Failed' 
  AND REPAYMENT_FAILURE_REASON_CLEAN IS NOT NULL
```

### Payment Method Analysis
- Use **REPAYMENT_METHOD** for high-level categorization:
  - 'Bank Account', also known as BSB payment method
  - 'Debit Card'
  - 'Credit Card'
  - 'Apple Pay'
  - 'Unknown'
- Use **REPAYMENT_SCHEME** for card network analysis:
  - 'Visa'
  - 'Mastercard'
  - 'Bank Account'
  - 'BPAY'
  - 'Apple Pay'
  - 'Unknown'

## Example Query Patterns

1. Total Captured Repayments by Date

```sql
SELECT 
    DATE(REPAYMENT_REQUEST_TIMESTAMP_LTZ) AS repayment_date,
    COUNT(*) AS transaction_count,
    SUM(REPAYMENT_AMOUNT) AS total_amount
FROM prod_analytics.prod_prep.fct_repayment_request
WHERE REPAYMENT_STATUS = 'Captured'
  AND REPAYMENT_REQUEST_TIMESTAMP_LTZ >= DATEADD(day, -30, CURRENT_DATE())
GROUP BY 1
ORDER BY 1 DESC;
```

2. Failure Rate by Payment Method

```sql
SELECT 
    REPAYMENT_METHOD,
    COUNT(*) AS total_attempts,
    SUM(CASE WHEN REPAYMENT_STATUS = 'Failed' THEN 1 ELSE 0 END) AS failed_count,
    SUM(CASE WHEN REPAYMENT_STATUS = 'Captured' THEN 1 ELSE 0 END) AS success_count,
    ROUND(SUM(CASE WHEN REPAYMENT_STATUS = 'Failed' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS failure_rate_pct
FROM prod_analytics.prod_prep.fct_repayment_request
WHERE REPAYMENT_REQUEST_TIMESTAMP_LTZ >= DATEADD(day, -30, CURRENT_DATE())
GROUP BY 1
ORDER BY 4 DESC;
```

3. Top Failure Reasons

```sql
SELECT 
    REPAYMENT_FAILURE_REASON_CLEAN,
    COUNT(*) AS failure_count,
    SUM(REPAYMENT_AMOUNT) AS failed_amount,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct_of_failures
FROM prod_analytics.prod_prep.fct_repayment_request
WHERE REPAYMENT_STATUS = 'Failed'
  AND REPAYMENT_FAILURE_REASON_CLEAN IS NOT NULL
  AND REPAYMENT_REQUEST_TIMESTAMP_LTZ >= DATEADD(day, -30, CURRENT_DATE())
GROUP BY 1
ORDER BY 2 DESC
LIMIT 10;
```

4. Repayment Volume by Product and Reason

```sql
SELECT 
    PRODUCT,
    REPAYMENT_REASON,
    COUNT(*) AS transaction_count,
    SUM(REPAYMENT_AMOUNT) AS total_amount,
    AVG(REPAYMENT_AMOUNT) AS avg_amount
FROM prod_analytics.prod_prep.fct_repayment_request
WHERE REPAYMENT_STATUS = 'Captured'
  AND REPAYMENT_REQUEST_TIMESTAMP_LTZ >= DATEADD(day, -30, CURRENT_DATE())
GROUP BY 1, 2
ORDER BY 1, 4 DESC;
```

5. Gateway Performance Comparison

```sql
SELECT 
    REPAYMENT_GATEWAY,
    COUNT(*) AS total_attempts,
    SUM(CASE WHEN REPAYMENT_STATUS = 'Captured' THEN 1 ELSE 0 END) AS successful,
    SUM(CASE WHEN REPAYMENT_STATUS = 'Failed' THEN 1 ELSE 0 END) AS failed,
    ROUND(SUM(CASE WHEN REPAYMENT_STATUS = 'Captured' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS success_rate_pct,
    SUM(CASE WHEN REPAYMENT_STATUS = 'Captured' THEN REPAYMENT_AMOUNT ELSE 0 END) AS total_captured_amount
FROM prod_analytics.prod_prep.fct_repayment_request
WHERE REPAYMENT_REQUEST_TIMESTAMP_LTZ >= DATEADD(day, -30, CURRENT_DATE())
  AND REPAYMENT_GATEWAY != 'Not Set'
GROUP BY 1
ORDER BY 2 DESC;
```

6. Repayment Trends by Collection Source

```sql
SELECT 
    DATE_TRUNC('week', REPAYMENT_REQUEST_TIMESTAMP_LTZ) AS week_start,
    REPAYMENT_SOURCE,
    COUNT(*) AS transaction_count,
    SUM(CASE WHEN REPAYMENT_STATUS = 'Captured' THEN REPAYMENT_AMOUNT ELSE 0 END) AS captured_amount
FROM prod_analytics.prod_prep.fct_repayment_request
WHERE REPAYMENT_REQUEST_TIMESTAMP_LTZ >= DATEADD(day, -90, CURRENT_DATE())
GROUP BY 1, 2
ORDER BY 1 DESC, 4 DESC;
```

7. Default Payment Method Usage

```sql
SELECT 
    DEFAULT_REPAYMENT_METHOD_FLAG,
    REPAYMENT_METHOD,
    COUNT(*) AS transaction_count,
    ROUND(SUM(CASE WHEN REPAYMENT_STATUS = 'Captured' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS success_rate_pct
FROM prod_analytics.prod_prep.fct_repayment_request
WHERE REPAYMENT_REQUEST_TIMESTAMP_LTZ >= DATEADD(day, -30, CURRENT_DATE())
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC;
```

8. Written-off Account Repayments

```sql
SELECT 
    ACCOUNT_WRITEOFF_BEFORE_PAYMENT_FLAG,
    COUNT(DISTINCT ACCOUNT_ID) AS unique_accounts,
    COUNT(*) AS transaction_count,
    SUM(CASE WHEN REPAYMENT_STATUS = 'Captured' THEN REPAYMENT_AMOUNT ELSE 0 END) AS total_captured
FROM prod_analytics.prod_prep.fct_repayment_request
WHERE REPAYMENT_REQUEST_TIMESTAMP_LTZ >= DATEADD(day, -30, CURRENT_DATE())
GROUP BY 1
ORDER BY 1;
```

## Important Notes and Considerations

### Data Quality
- **FINGERPRINT_TOKEN** is a sensitive field with masking policy applied - use with caution
- **PAYMENT_METHOD_ID** can be NULL for Apple Pay and External Collections - this is expected behavior
- **REPAYMENT_FAILURE_REASON** is only populated when REPAYMENT_STATUS is 'Failed'

### Payment Status Codes
When analyzing status, note the raw status code (repayment_status_raw) mappings:
- 0 = processing
- 1 = Authorised but not finalized
- 2 = Captured
- 3 = Declined
- 4 = Failed
- 5 = Refunded
- 6 = Dishonoured, only for BSB or bank account payments

### Channel Interpretation
- **CHANNEL** = 'Administration' typically indicates system batch runs
- The majority of scheduled repayments will have this channel value

### Response Codes
- **NETWORK_RESPONSE_CODE** may or may NOT honour ISO 8583 standards
- For ISO 8583 compliant response codes, use network_response_code_iso field (if available)
- Only Credit Card and Debt Card payments have network response code.
- Some important response codes:
  - '51': insufficient funds, or not sufficient funds, or NSF
  - '05': do not honour. This is a generic failed response code. Most of the time it means insufficient funds.
  - '04': Pick up card (no fraud)
  - '07': Pick up card, special condition (fraud account)
  - '12': invalid transaction
  - '14': invalid account number (no such number)
  - '15': No such issuer (first 8 digits of card's account number do not relate to an issuing idenfier)
  - '41': Lost card, pick up
  - '43': Stolen card, pick up
  - '46': Closed account
  - '57': Transaction not permitted to cardholder
  - 'R0': Stop payment order
  - 'R1': Revocation of authorization order
  - 'R3': Revocation of all authorizations order
  - '03': invalid merchant
  - '19': Re-enter transaction
  - '59': suspected fraud
  - '61': exceeds approval amount limit
  - '62': restricted card (card invalid in region or country)
  - '65': exceeds withdrawal frequency limit
  - '75': allowable number of PIN-entry tries exceeded
  - '78': Blocked
  - '86': Cannot verify PIN
  - '91': issuer or switch inoperative
  - '93': transaction cannot be completed - violation of law
  - '96': system malfunction
  - 'N3': cash service not available
  - 'N4': Cash request exceeds issuer or approved limit
  - '14': invalid account number (no such number)
  - '54': expired card or expiration date missing
  - '55': PIN incorrect or missing
  - '70': PIN data required
  - '82': negative online CAM, dCVV, iCVV or CVV results
  - '1A': additional customer authentication required
  - 'N7': decline for CVV2 failure
- The following network response codes are called "hard declined" code. If a payment returns one of these response codes, the payment method should be invalidated: ['04','07','12','14','15','39','41','43','46','54','57','75','R0','R1','R3']. The rest response codes are called "soft declined" code. They don't trigger payment method invalidation.

### Amount Considerations
- All amounts are in dollars (currency specified by **payment_currency** field)
- Consider excluding refunds when calculating revenue: `WHERE REPAYMENT_REASON != 'Refund'`

### Internal blocks
- For Credit Card and Debt Card payments, when the payment gateway value is 'Not Set', it means the payment is blocked by Company due to various reasons such as schema compliance detection. Internal blocked payments always have failed status. But these payments are failed not because of customer fault. The payments are failed as they are blocked by our internal systems.
- Some payments such as Apple pay or Bpay don't have gateway. These payments should not be treated as blocked payments. We only block payments from Credit Cards and Debit Cards.

### Bank (BSB) payments
- Bank payments are always marked as captured initially. Some of the bank payments may be bounced back as dishonoured within 3-5 business days. Only then the payment status will be updated to dishonoured. So if user is asking for information related to captured BSB payments, a common practice is to exclude BSB payments within last 5 calendar days, to avoid falsely classify them as captures. However, failed BSB payments always mean fails. So failed recent (within 5 days) BSB payments don't need to be excluded.

### Payment auto retries
When a system triggered scheduled payment is failed, the system automatically triggers another attempt from other registered payment method(s). These attempts can be treated as "retries". One can identify retries from reference number column - it always contains substring 'AltMethod'. A fuzzy matching like `where reference_number like '%AltMethod%'` can be used to identify retries. Retries always happen within few seconds of the initial failed and with the same repayment reason and amount. When user asks to count the total number/amount of failed scheduled payments, we should pay attention: on one hand, we don't want to include the failed retries as this will result in overcounting the fails. On the other hand, if the initial scheduled payment has failed but one of the retries succeeds, then the initial payment can be treated as success.

### Best Practices
1. Always filter by date range to improve query performance
2. Use REPAYMENT_STATUS = 'Captured' for confirmed successful payments
3. Use REPAYMENT_REASON_DETAILED for more granular analysis than REPAYMENT_REASON
4. Join with dim_account table on ACCOUNT_ID for additional account-level attributes
5. Consider the PRODUCT field when analyzing different Zip product lines

## Related Tables
- **prod_analytics.prod_prep.dim_account**: Join on ACCOUNT_ID for account-level details
- **prod_analytics.prod_source.stg_zmpaydb_payments**: Source table for payment data
- **prod_analytics.prod_source.stg_zmpaydb_payment_methods**: Source for payment method details
- **prod_analytics.prod_source.stg_zmpaydb_payment_status**: Source for payment status information