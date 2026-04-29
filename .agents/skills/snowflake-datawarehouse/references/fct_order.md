## 1. Overview

`PROD_PREP.FCT_ORDER` is the **primary fact table for purchase/order analysis** at Zip. Each row represents a single customer order (one transaction at one merchant), covering all Zip products and all checkout channels — online, in-store, VCN (virtual card), gift cards, bill payments, and Tap & Zip.

This is typically the **first table to reach for** when answering questions about:
- Revenue and GMV trends
- Merchant performance
- Customer purchase behaviour
- Funnel or checkout channel analysis
- VCN / open-loop card spend
- Cohort and repeat-purchase analysis

> **Order grain vs ledger grain:** `FCT_ORDER` has one row per order. For fee/instalment/repayment analysis, use `FCT_TRANSACTION` instead — it has one row per ledger entry per order.

---

## 2. Table Location

| Property | Value |
|---|---|
| **Full name** | `PROD_ANALYTICS.PROD_PREP.FCT_ORDER` |
| **Schema** | `PROD_PREP` (dimensional modelling layer) |
| **Materialization** | Incremental (`unique_key = ORDER_ID`) |
| **Refresh cadence** | Hourly |

---

## 3. Schema

### Primary Keys & Identifiers

| Column | Type | Description |
|---|---|---|
| `ORDER_ID` | VARCHAR | **Primary key.** Unique order identifier. |
| `CHECKOUT_ID` | VARCHAR | Snowplow checkout session ID — links to web/app event streams. |
| `OPERATION_REQUEST_ID` | VARCHAR | Links to the checkout/request payload in `stg_zmdb_operation_request`. Also used to join `FCT_ORDER_STATUS`. |
| `ACCOUNT_ID` | VARCHAR | The Zip account that made the purchase. Joins to `DIM_ACCOUNT`. |
| `CONSUMER_ID` | VARCHAR | Consumer record linked to the account. |
| `CUSTOMER_ID` | VARCHAR | External customer identifier (lowercase). |
| `MERCHANT_ID` | VARCHAR | Merchant where order was placed. Joins to `DIM_MERCHANT`. |
| `BRANCH_ID` | VARCHAR | Merchant branch identifier. |
| `OPEN_LOOP_MERCHANT_ID` | VARCHAR | VCN open-loop merchant identifier (for virtual card transactions). |

### Timestamps

| Column | Type | Description |
|---|---|---|
| `ORDER_TIMESTAMP` | TIMESTAMP_NTZ | Order created time in **Australia/Sydney** timezone. Use this for AU business reporting. |
| `ORDER_TIMESTAMP_UTC` | TIMESTAMP_NTZ | Order created time in **UTC**. Use for cross-region or technical comparisons. |
| `DATA_LOADED_TIMESTAMP` | TIMESTAMP_NTZ | Airbyte ingestion timestamp — when the row arrived in the warehouse. Not the order time. |

### Order Attributes

| Column | Type | Description |
|---|---|---|
| `ORDER_AMOUNT` | NUMBER | Total order value in AUD. |
| `ORDER_METHOD` | VARCHAR | `'In-Store'` or `'Online'`. |
| `PAYMENT_METHOD` | VARCHAR | `'Pay Now'` or `'Pay Later'`. |
| `FUNNEL_TYPE` | VARCHAR | Checkout channel — `Bills`, `Gift Cards`, `Single Use Card`, `T&Z Card`, `Subscription Card`, `Barcode`, `Online`, `Dashboard Instore`, etc. |
| `PLATFORM` | VARCHAR | Platform used to place the order (e.g. `iOS`, `Android`, `Web`). |
| `IS_TOKENISED` | BOOLEAN | Whether the checkout used tokenised (digital wallet) payment. |

### Gift Card & Biller Fields

| Column | Type | Description |
|---|---|---|
| `GIFT_CARD_NAME` | VARCHAR | Cleaned gift card name (populated for `FUNNEL_TYPE = 'Gift Cards'`). |
| `BILLER_NAME` | VARCHAR | Biller name for bill payment orders (`FUNNEL_TYPE = 'Bills'`). |

### VCN (Virtual Card Network) Fields

| Column | Type | Description |
|---|---|---|
| `VCN_MERCHANT_NAME` | VARCHAR | Raw VCN merchant name from the card network. |
| `VCN_MERCHANT_NAME_CLEAN` | VARCHAR | Cleaned/normalised VCN merchant name. |
| `VCN_CARD_TYPE` | VARCHAR | `Multi Use`, `Single Use`, or `Subscriptions`. |
| `VCN_CARD_SOURCE` | VARCHAR | Where the card was issued — `Chrome Extension`, `Web Wallet`, `App (Cards Tab)`, etc. |
| `VCN_MERCHANT_CATEGORY_CODE` | VARCHAR | MCC code from the card network. |
| `VCN_MERCHANT_CATEGORY` | VARCHAR | Human-readable MCC description. |
| `VCN_MCC_INDUSTRY` | VARCHAR | Zip's industry classification for the MCC. |
| `VCN_MCC_SUB_CATEGORY` | VARCHAR | Zip's sub-category classification for the MCC. |

### Consolidated Merchant Fields

| Column | Type | Description |
|---|---|---|
| `CONSOLIDATED_MERCHANT_ID` | VARCHAR | Normalised merchant grouping ID — maps VCN + in-store + online to one entity. |
| `CONSOLIDATED_MERCHANT_NAME` | VARCHAR | Normalised merchant name (use this for merchant-level reporting over raw `MERCHANT_ID`). |
| `CONSOLIDATED_MERCHANT_TYPE` | VARCHAR | Merchant type classification. |

### Flags

| Column | Type | Description |
|---|---|---|
| `FLAG_TRANSACTION_FEE` | BOOLEAN | `TRUE` if an international transaction fee applied (VCN orders). |
| `FLAG_TNZ_EVERYDAY_SPEND` | BOOLEAN | `TRUE` if this is a T&Z card transaction at an everyday merchant (Coles, Woolworths, etc.). |

### Customer Intelligence

| Column | Type | Description |
|---|---|---|
| `CUSTOMER_SESSION_ID` | VARCHAR | Biocatch session ID for fraud/risk analysis. |

### Purchase Protection

| Column | Pattern | Description |
|---|---|---|
| `PP_*` | Various | Purchase protection policy fields. Prefix all purchase-protection columns. |

---

## 4. Common Query Patterns

### 4.1 Daily GMV by product

```sql
SELECT
    DATE_TRUNC('day', ORDER_TIMESTAMP)  AS order_date,
    PAYMENT_METHOD,
    COUNT(*)                            AS order_count,
    SUM(ORDER_AMOUNT)                   AS gmv
FROM PROD_ANALYTICS.PROD_PREP.FCT_ORDER
WHERE ORDER_TIMESTAMP >= '2025-01-01'
  AND ORDER_TIMESTAMP <  '2026-01-01'
GROUP BY 1, 2
ORDER BY 1, 2;
```

### 4.2 Orders with their final status

Join `FCT_ORDER_STATUS` on `OPERATION_REQUEST_ID` to get the resolved order state (approved, declined, cancelled, refunded, etc.):

```sql
SELECT
    o.ORDER_ID,
    o.ORDER_TIMESTAMP,
    o.ORDER_AMOUNT,
    o.MERCHANT_ID,
    os.ORDER_STATUS
FROM PROD_ANALYTICS.PROD_PREP.FCT_ORDER       o
JOIN PROD_ANALYTICS.PROD_PREP.FCT_ORDER_STATUS os
  ON o.OPERATION_REQUEST_ID = os.OPERATION_REQUEST_ID
WHERE o.ORDER_TIMESTAMP >= DATEADD('day', -30, CURRENT_DATE)
  AND os.ORDER_STATUS = 'Completed';
```

### 4.3 Top 20 merchants by GMV (last 90 days)

```sql
SELECT
    m.MERCHANT_NAME,
    COUNT(*)            AS order_count,
    SUM(o.ORDER_AMOUNT) AS gmv
FROM PROD_ANALYTICS.PROD_PREP.FCT_ORDER    o
JOIN PROD_ANALYTICS.PROD_PREP.DIM_MERCHANT m
  ON o.MERCHANT_ID = m.MERCHANT_ID
WHERE o.ORDER_TIMESTAMP >= DATEADD('day', -90, CURRENT_DATE)
GROUP BY 1
ORDER BY 3 DESC
LIMIT 20;
```

### 4.4 Cohort repeat-purchase analysis (Nth order per account at merchant)

`DIM_XTH_ORDER` tracks which order number this is for a given account × merchant pair:

```sql
SELECT
    DATE_TRUNC('month', o.ORDER_TIMESTAMP) AS cohort_month,
    x.XTH_ORDER_NUMBER,
    COUNT(*)                               AS order_count,
    SUM(o.ORDER_AMOUNT)                    AS gmv
FROM PROD_ANALYTICS.PROD_PREP.FCT_ORDER     o
JOIN PROD_ANALYTICS.PROD_PREP.DIM_XTH_ORDER x
  ON  o.ORDER_ID   = x.ORDER_ID
  AND o.MERCHANT_ID = x.MERCHANT_ID
WHERE o.ORDER_TIMESTAMP >= '2025-01-01'
GROUP BY 1, 2
ORDER BY 1, 2;
```

### 4.5 VCN spend breakdown by MCC industry

```sql
SELECT
    VCN_MCC_INDUSTRY,
    VCN_CARD_TYPE,
    COUNT(*)            AS order_count,
    SUM(ORDER_AMOUNT)   AS spend
FROM PROD_ANALYTICS.PROD_PREP.FCT_ORDER
WHERE ORDER_TIMESTAMP >= DATEADD('month', -3, CURRENT_DATE)
  AND FUNNEL_TYPE IN ('Single Use Card', 'T&Z Card', 'Subscription Card')
GROUP BY 1, 2
ORDER BY 4 DESC;
```

### 4.6 New vs returning customers (using DIM_ACCOUNT first-order metadata)

```sql
SELECT
    DATE_TRUNC('week', o.ORDER_TIMESTAMP)                                  AS week,
    IFF(o.ORDER_TIMESTAMP = a.FIRST_ORDER_TIMESTAMP, 'New', 'Returning')   AS customer_type,
    COUNT(DISTINCT o.CONSUMER_ID)                                          AS unique_customers,
    SUM(o.ORDER_AMOUNT)                                                    AS gmv
FROM PROD_ANALYTICS.PROD_PREP.FCT_ORDER  o
JOIN PROD_ANALYTICS.PROD_PREP.DIM_ACCOUNT a
  ON o.ACCOUNT_ID = a.ACCOUNT_ID
WHERE o.ORDER_TIMESTAMP >= DATEADD('month', -6, CURRENT_DATE)
GROUP BY 1, 2
ORDER BY 1, 2;
```

### 4.7 Online vs in-store split by funnel type

```sql
SELECT
    ORDER_METHOD,
    FUNNEL_TYPE,
    COUNT(*)          AS order_count,
    SUM(ORDER_AMOUNT) AS gmv,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY ORDER_METHOD), 2) AS pct_of_channel
FROM PROD_ANALYTICS.PROD_PREP.FCT_ORDER
WHERE ORDER_TIMESTAMP >= DATEADD('day', -30, CURRENT_DATE)
GROUP BY 1, 2
ORDER BY 1, 3 DESC;
```

### 4.8 Full enriched order view (all dimensions)

```sql
SELECT
    o.ORDER_ID,
    o.ORDER_TIMESTAMP,
    o.ORDER_AMOUNT,
    o.FUNNEL_TYPE,
    o.ORDER_METHOD,
    o.PAYMENT_METHOD,
    o.PLATFORM,
    os.ORDER_STATUS,
    m.MERCHANT_NAME,
    a.PRODUCT                   AS zip_product,
    a.CREDIT_LIMIT,
    a.ORIGINATION_MERCHANT_ID,
    a.FIRST_ORDER_TIMESTAMP,
    x.XTH_ORDER_NUMBER
FROM PROD_ANALYTICS.PROD_PREP.FCT_ORDER         o
JOIN PROD_ANALYTICS.PROD_PREP.FCT_ORDER_STATUS  os ON o.OPERATION_REQUEST_ID = os.OPERATION_REQUEST_ID
JOIN PROD_ANALYTICS.PROD_PREP.DIM_MERCHANT       m ON o.MERCHANT_ID           = m.MERCHANT_ID
JOIN PROD_ANALYTICS.PROD_PREP.DIM_ACCOUNT        a ON o.ACCOUNT_ID            = a.ACCOUNT_ID
LEFT JOIN PROD_ANALYTICS.PROD_PREP.DIM_XTH_ORDER x ON o.ORDER_ID              = x.ORDER_ID
                                                   AND o.MERCHANT_ID           = x.MERCHANT_ID
WHERE o.ORDER_TIMESTAMP >= DATEADD('day', -7, CURRENT_DATE)
LIMIT 1000;
```

---

## 8. Gotchas & Best Practices

### Always filter on ORDER_TIMESTAMP, not DATA_LOADED_TIMESTAMP
`DATA_LOADED_TIMESTAMP` is the Airbyte ingestion time, not the business event time. All business reporting should filter on `ORDER_TIMESTAMP` (Sydney) or `ORDER_TIMESTAMP_UTC`.

```sql
-- ✅ Correct
WHERE ORDER_TIMESTAMP >= '2025-01-01'

-- ❌ Wrong — this is the warehouse load time, not when the order happened
WHERE DATA_LOADED_TIMESTAMP >= '2025-01-01'
```

### Use CONSOLIDATED_MERCHANT_NAME for merchant reporting, not raw MERCHANT_ID
The same real-world merchant can have multiple `MERCHANT_ID` values (different branches, online vs in-store, VCN vs traditional). `CONSOLIDATED_MERCHANT_NAME` / `CONSOLIDATED_MERCHANT_ID` maps these to a single canonical entity.

```sql
-- ✅ Correct — groups all JB Hi-Fi entries together
GROUP BY CONSOLIDATED_MERCHANT_NAME

-- ❌ Fragile — may split one merchant across multiple rows
GROUP BY MERCHANT_ID
```

### FCT_ORDER_STATUS join is on OPERATION_REQUEST_ID, not ORDER_ID
This is a common mistake. The two tables share `OPERATION_REQUEST_ID`, not `ORDER_ID`.

```sql
-- ✅ Correct
JOIN FCT_ORDER_STATUS os ON o.OPERATION_REQUEST_ID = os.OPERATION_REQUEST_ID

-- ❌ Wrong — no ORDER_ID column in FCT_ORDER_STATUS
JOIN FCT_ORDER_STATUS os ON o.ORDER_ID = os.ORDER_ID
```

### DIM_XTH_ORDER requires a compound key join
Always include both `ORDER_ID` AND `MERCHANT_ID` when joining `DIM_XTH_ORDER`. Omitting `MERCHANT_ID` will fan-out rows.

```sql
-- ✅ Correct
JOIN DIM_XTH_ORDER x ON o.ORDER_ID = x.ORDER_ID AND o.MERCHANT_ID = x.MERCHANT_ID

-- ❌ Wrong — will produce duplicates if a customer visited multiple merchants
JOIN DIM_XTH_ORDER x ON o.ORDER_ID = x.ORDER_ID
```

### VCN columns are NULL for non-VCN orders
`VCN_MERCHANT_NAME`, `VCN_CARD_TYPE`, `VCN_MERCHANT_CATEGORY_CODE`, etc. are only populated for VCN funnel types (`'Single Use Card'`, `'T&Z Card'`, `'Subscription Card'`). Always filter or handle NULLs appropriately.

```sql
-- ✅ Safe VCN query
WHERE FUNNEL_TYPE IN ('Single Use Card', 'T&Z Card', 'Subscription Card')
  AND VCN_MERCHANT_NAME IS NOT NULL
```

### ORDER_TIMESTAMP is in Sydney time (AEDT/AEST)
Zip's reporting convention uses Australia/Sydney. Be careful with month/day boundaries — a UTC midnight query will cut your AU day at 10am or 11am (depending on DST). Use `ORDER_TIMESTAMP_UTC` only if you explicitly need UTC alignment.

### FCT_ORDER does NOT include transaction type detail
If you need to distinguish between purchase, fee, repayment, interest, or reward transactions, you must join or switch to `FCT_TRANSACTION`. `FCT_ORDER` captures only the originating order event.

### Incremental model — historical backfills may lag
Because `FCT_ORDER` is incremental (`unique_key = ORDER_ID`), a source data backfill will upsert correctly but only at the next hourly run. If you suspect data gaps in a specific window, check the dbt pipeline logs for failed runs.