---
name: bank-score-2022
description: Instructions on bank score 2022 model details.
---

## Overview
The 2022 bank score is a logistic regression model using dummy variable modelling approach. This document explains how the input features are binned and each bin's coefficient.

There are 14 features, breaking up into 52 dummy variables. Each feature has a slient dummy variable that gets 0 coefficient.

The model output is estimated probability of bad. The higher the output is, the more likely an account turns bad. This is important when calculating Gini or AUC (Area Under Curve)

## Parameters

### Intercept: -1.91506953

### bank_0002:

**Column name in PROD_ANALYTICS.prod_PREP.dim_underwriting_bank_model_validation**: `BANK_2022_AVAIL_BAL_TRANSACTION_ACC`

**Binning and coefficients:**

| BIN NAME | BINNING LOGIC | COEFFICIENT |
| --- | --- | --- |
| bank_0002_a_null | NaN | -0.61443605 |
| bank_0002_b_10 | x <= 10 | 0 |
| bank_0002_c_40 | 10 < x <= 40 | -0.33178761 |
| bank_0002_e_200 | 40 < x <= 200 | -0.62360056 |
| bank_2072_f_201 | x > 200 | -0.76348899 |


### bank_1073

**Column name in PROD_ANALYTICS.prod_PREP.dim_underwriting_bank_model_validation**: `BANK_2022_RATIO_AVG_DAILY_BAL_L3M_TO_TOT_CREDIT_L3M`

**Meaning:** Ratio of average daily savings balance over last 3 months to total credits into saving accounts over last 3 months.

**Binning and coefficients:**

| BIN NAME | BINNING LOGIC | COEFFICIENT |
| --- | --- | --- |
| bank_1073_a_null | NaN | -0.56503010 |
| bank_1073_b_015 | x <= 0.015 | 0 |
| bank_1073_c_05 | 0.015 < x <= 0.05 | -0.40293619 |
| bank_1073_d_075 | 0.05 < x <= 0.075 | -0.62062796 |
| bank_1073_e_10 | 0.075 < x <= 0.10 | -0.82678667 |
| bank_1073_f_30 | 0.10 < x <= 0.30 | -0.94670184 |
| bank_1073_g_31 | x > 0.30 | -1.07788428 |

### bank_2024

**Column name in PROD_ANALYTICS.prod_PREP.dim_underwriting_bank_model_validation**: `BANK_2022_NUM_DAYS_END_BAL_LT_10_L3M`

**Meaning:** Number of days in last 3 months where the combined end-of-day balance across transaction and saving accounts was below $10.

**Binning and coefficients:**

| BIN NAME | BINNING LOGIC | COEFFICIENT |
| --- | --- | --- |
| bank_2024_a_null | NaN | 0.03743078 |
| bank_2024_b_0 | x == 0 | 0 |
| bank_2024_c_30 | 0 < x <= 30 | 0.27183078 |
| bank_2024_d_31 | x > 30 | 0.79175127 |

### bank_2072

**Column name in PROD_ANALYTICS.prod_PREP.dim_underwriting_bank_model_validation**: `BANK_2022_RATIO_AVG_DAILY_BAL_L1M_TO_TOT_CREDIT_L1M`

**Meaning:** Ratio of average daily transaction+savings balance last 1 month to total credits into transaction+savings acocunts last 1 month.

**Binning and coefficients:**

| BIN NAME | BINNING LOGIC | COEFFICIENT |
| --- | --- | --- |
| bank_2072_a_null | NaN | -0.72076397 |
| bank_2072_b_03 | x <= 0.03 | 0 |
| bank_2072_c_05 | 0.03 < x <= 0.05 | -0.17966396 |
| bank_2072_d_10 | 0.05 < x <= 0.10 | -0.40462350 |
| bank_2072_e_15 | 0.10 < x <= 0.15 | -0.48013733 |
| bank_2072_f_25 | 0.15 < x <= 0.25 | -0.52917432 |
| bank_2072_g_50 | 0.25 < x <= 0.50 | -0.72880294 |
| bank_2072_h_51 | x > 0.50 | -1.01318825 |

### bank_2085

**Column name in PROD_ANALYTICS.prod_PREP.dim_underwriting_bank_model_validation**: `BANK_2022_NUM_INSURANCE_TRANSACTIONS_L3M`

**Meaning:** Number of insurance transactions in last 3 months

**Binning and coefficients:**

| BIN NAME | BINNING LOGIC | COEFFICIENT |
| --- | --- | --- |
| bank_2085_a_null | NaN | 0.03743078 |
| bank_2085_b_0 | x == 0 | 0 |
| bank_2085_c_2 | 0 < x <= 2 | 0.32276825 |
| bank_2085_d_5 | 2 < x <= 5 | -0.65078694 |
| bank_2085_e_10 | 5 < x <= 10 | -0.94167354 |
| bank_2085_f_11 | x > 10 | -1.10691671 |

### bank_2093

**Column name in PROD_ANALYTICS.prod_PREP.dim_underwriting_bank_model_validation**: `BANK_2022_NUM_DEBT_COLLECTION_TRANSACTIONS_L3M`

**Meaning:** Number of debt collection transactions in last 3 months

**Binning and coefficients:**

| BIN NAME | BINNING LOGIC | COEFFICIENT |
| --- | --- | --- |
| bank_2093_a_null | NaN | 0.03743078 |
| bank_2093_b_0 | x == 0 | 0 |
| bank_2093_c_1 | x > 0 | 0.05499711 |

### bank_2189

**Column name in PROD_ANALYTICS.prod_PREP.dim_underwriting_bank_model_validation**: `BANK_2022_NUM_PAYDAY_LOAN_PROVIDERS_L3M`

**Meaning:** Number of distinct payday loan providers in the last 3 months. More precisely, it counts the number of unique thirdParty values among transactions tagged as payday lender/SACC related.

**Binning and coefficients:**

| BIN NAME | BINNING LOGIC | COEFFICIENT |
| --- | --- | --- |
| bank_2189_a_null | NaN | 0.03743078 |
| bank_2189_b_0 | x == 0 | 0 |
| bank_2189_c_1 | x == 1 | 0.31760317 |
| bank_2189_d_2 | x > 1 | 0.72595970 |

### bank_2193

**Column name in PROD_ANALYTICS.prod_PREP.dim_underwriting_bank_model_validation**: `BANK_2022_NUM_PAYDAY_LOAN_DISHONOURS_L3M`

**Meaning:** Number of payday loan dishonours in last 3 months

**Binning and coefficients:**

| BIN NAME | BINNING LOGIC | COEFFICIENT |
| --- | --- | --- |
| bank_2193_a_null | NaN | 0.03743078 |
| bank_2193_b_0 | x == 0 | 0 |
| bank_2193_c_1 | x > 0 | 0.19508913 |

### bank_2197

**Column name in PROD_ANALYTICS.prod_PREP.dim_underwriting_bank_model_validation**: `BANK_2022_NUM_TOT_DISHONOURS_L3M`

**Meaning:** Number of total dishonour transactions in last 3 months

**Binning and coefficients:**

| BIN NAME | BINNING LOGIC | COEFFICIENT |
| --- | --- | --- |
| bank_2197_a_null | NaN | 0.03743078 |
| bank_2197_b_0 | x == 0 | 0 |
| bank_2197_c_2 | 0 < x <= 2 | 0.10194643 |
| bank_2197_d_5 | 2 < x <= 5 | 0.19696173 |
| bank_2197_e_6 | x > 5 | 0.51491751 |

### bank_2205

**Column name in PROD_ANALYTICS.prod_PREP.dim_underwriting_bank_model_validation**: `BANK_2022_AMT_WAGES_L3M`

**Meaning:** Total wage amount in last 3 months

**Binning and coefficients:**

| BIN NAME | BINNING LOGIC | COEFFICIENT |
| --- | --- | --- |
| bank_2205_a_null | NaN | 0.03743078 |
| bank_2205_b_1000 | x <= 1000 | 0 |
| bank_2205_c_10000 | 1000 < x <= 10000 | -0.29581302 |
| bank_2205_d_20000 | 10000 < x <= 20000 | -0.60038669 |
| bank_2205_e_20001 | x > 20000 | -0.98296361 |

### bank_2213

**Column name in PROD_ANALYTICS.prod_PREP.dim_underwriting_bank_model_validation**: `BANK_2022_NUM_CENTRELINK_L3M`

**Meaning:** Number of Centrelink transactions in last 3 months

**Binning and coefficients:**

| BIN NAME | BINNING LOGIC | COEFFICIENT |
| --- | --- | --- |
| bank_2213_a_null | NaN | 0.03743078 |
| bank_2213_b_0 | x == 0 | 0 |
| bank_2213_c_3 | 0 < x <= 3 | 0.13707419 |
| bank_2213_d_4 | x > 3 | 0.16595391 |

### bank_2277

**Column name in PROD_ANALYTICS.prod_PREP.dim_underwriting_bank_model_validation**: `BANK_2022_NUM_ATM_WITHDRAWALS_L3M`

**Meaning:** Number of ATM transactions in last 3 months

**Binning and coefficients:**

| BIN NAME | BINNING LOGIC | COEFFICIENT |
| --- | --- | --- |
| bank_2277_a_null | NaN | 0.03743078 |
| bank_2277_b_0 | x == 0 | 0 |
| bank_2277_c_10 | 0 < x <= 10 | 0.43985471 |
| bank_2277_d_20 | 10 < x <= 20 | 1.04723958 |
| bank_2277_e_30 | 20 < x <= 30 | 1.39422014 |
| bank_2277_f_31 | x > 30 | 1.48924862 |

### bank_2308

**Column name in PROD_ANALYTICS.prod_PREP.dim_underwriting_bank_model_validation**: `BANK_2022_NUM_JOBSEEKER_L3M`

**Meaning:** Number of JobSeeker transactions in the last 3 months

**Binning and coefficients:**

| BIN NAME | BINNING LOGIC | COEFFICIENT |
| --- | --- | --- |
| bank_2308_a_null | NaN | 0.03743078 |
| bank_2308_b_0 | x == 0 | 0 |
| bank_2308_c_5 | 0 < x <= 5 | 0.06769672 |
| bank_2308_d_6 | x > 5 | 0.56073297 |

### bank_5001

**Column name in PROD_ANALYTICS.prod_PREP.dim_underwriting_bank_model_validation**: `BANK_2022_NUM_HOME_LOAN_ACC`

**Meaning:** Number of home loan accounts found in bank statement

**Binning and coefficients:**

| BIN NAME | BINNING LOGIC | COEFFICIENT |
| --- | --- | --- |
| bank_5001_a_0 | x == 0 | 0 |
| bank_5001_b_1 | x > 0 | -0.99723406 |

## Example code to reproduce the scores from the input features from table

First, create the dummy variables from the input features.
Second, create the parameter columns from the dummy variables.
Third, add all parameters up to get the logodds.
Finally, convert the logodds to probability as final score output.

```sql
WITH src AS (
    SELECT
        t.*
    FROM prod_prep.dim_underwriting_bank_model_validation t
    where submission_time >= '2025-01-01'
),

bins AS (
    SELECT
        s.*,

        /* bank_0002 */
        CASE WHEN BANK_2022_AVAIL_BAL_TRANSACTION_ACC IS NULL THEN 1 ELSE 0 END AS bank_0002_a_null,
        CASE WHEN BANK_2022_AVAIL_BAL_TRANSACTION_ACC > 10  AND BANK_2022_AVAIL_BAL_TRANSACTION_ACC <= 40  THEN 1 ELSE 0 END AS bank_0002_c_40,
        CASE WHEN BANK_2022_AVAIL_BAL_TRANSACTION_ACC > 40  AND BANK_2022_AVAIL_BAL_TRANSACTION_ACC <= 200 THEN 1 ELSE 0 END AS bank_0002_e_200,
        CASE WHEN BANK_2022_AVAIL_BAL_TRANSACTION_ACC > 200 THEN 1 ELSE 0 END AS bank_0002_f_201,

        /* bank_1073 */
        CASE WHEN BANK_2022_RATIO_AVG_DAILY_BAL_L3M_TO_TOT_CREDIT_L3M IS NULL THEN 1 ELSE 0 END AS bank_1073_a_null,
        CASE WHEN BANK_2022_RATIO_AVG_DAILY_BAL_L3M_TO_TOT_CREDIT_L3M > 0.015 AND BANK_2022_RATIO_AVG_DAILY_BAL_L3M_TO_TOT_CREDIT_L3M <= 0.05  THEN 1 ELSE 0 END AS bank_1073_c_05,
        CASE WHEN BANK_2022_RATIO_AVG_DAILY_BAL_L3M_TO_TOT_CREDIT_L3M > 0.05  AND BANK_2022_RATIO_AVG_DAILY_BAL_L3M_TO_TOT_CREDIT_L3M <= 0.075 THEN 1 ELSE 0 END AS bank_1073_d_075,
        CASE WHEN BANK_2022_RATIO_AVG_DAILY_BAL_L3M_TO_TOT_CREDIT_L3M > 0.075 AND BANK_2022_RATIO_AVG_DAILY_BAL_L3M_TO_TOT_CREDIT_L3M <= 0.10  THEN 1 ELSE 0 END AS bank_1073_e_10,
        CASE WHEN BANK_2022_RATIO_AVG_DAILY_BAL_L3M_TO_TOT_CREDIT_L3M > 0.10  AND BANK_2022_RATIO_AVG_DAILY_BAL_L3M_TO_TOT_CREDIT_L3M <= 0.30  THEN 1 ELSE 0 END AS bank_1073_f_30,
        CASE WHEN BANK_2022_RATIO_AVG_DAILY_BAL_L3M_TO_TOT_CREDIT_L3M > 0.30 THEN 1 ELSE 0 END AS bank_1073_g_31,

        /* bank_2024 */
        CASE WHEN BANK_2022_NUM_DAYS_END_BAL_LT_10_L3M IS NULL THEN 1 ELSE 0 END AS bank_2024_a_null,
        CASE WHEN BANK_2022_NUM_DAYS_END_BAL_LT_10_L3M > 0 AND BANK_2022_NUM_DAYS_END_BAL_LT_10_L3M <= 30 THEN 1 ELSE 0 END AS bank_2024_c_30,
        CASE WHEN BANK_2022_NUM_DAYS_END_BAL_LT_10_L3M > 30 THEN 1 ELSE 0 END AS bank_2024_d_31,

        /* bank_2072 */
        CASE WHEN BANK_2022_RATIO_AVG_DAILY_BAL_L1M_TO_TOT_CREDIT_L1M IS NULL THEN 1 ELSE 0 END AS bank_2072_a_null,
        CASE WHEN BANK_2022_RATIO_AVG_DAILY_BAL_L1M_TO_TOT_CREDIT_L1M > 0.03 AND BANK_2022_RATIO_AVG_DAILY_BAL_L1M_TO_TOT_CREDIT_L1M <= 0.05 THEN 1 ELSE 0 END AS bank_2072_c_05,
        CASE WHEN BANK_2022_RATIO_AVG_DAILY_BAL_L1M_TO_TOT_CREDIT_L1M > 0.05 AND BANK_2022_RATIO_AVG_DAILY_BAL_L1M_TO_TOT_CREDIT_L1M <= 0.10 THEN 1 ELSE 0 END AS bank_2072_d_10,
        CASE WHEN BANK_2022_RATIO_AVG_DAILY_BAL_L1M_TO_TOT_CREDIT_L1M > 0.10 AND BANK_2022_RATIO_AVG_DAILY_BAL_L1M_TO_TOT_CREDIT_L1M <= 0.15 THEN 1 ELSE 0 END AS bank_2072_e_15,
        CASE WHEN BANK_2022_RATIO_AVG_DAILY_BAL_L1M_TO_TOT_CREDIT_L1M > 0.15 AND BANK_2022_RATIO_AVG_DAILY_BAL_L1M_TO_TOT_CREDIT_L1M <= 0.25 THEN 1 ELSE 0 END AS bank_2072_f_25,
        CASE WHEN BANK_2022_RATIO_AVG_DAILY_BAL_L1M_TO_TOT_CREDIT_L1M > 0.25 AND BANK_2022_RATIO_AVG_DAILY_BAL_L1M_TO_TOT_CREDIT_L1M <= 0.50 THEN 1 ELSE 0 END AS bank_2072_g_50,
        CASE WHEN BANK_2022_RATIO_AVG_DAILY_BAL_L1M_TO_TOT_CREDIT_L1M > 0.50 THEN 1 ELSE 0 END AS bank_2072_h_51,

        /* bank_2085 */
        CASE WHEN BANK_2022_NUM_INSURANCE_TRANSACTIONS_L3M IS NULL THEN 1 ELSE 0 END AS bank_2085_a_null,
        CASE WHEN BANK_2022_NUM_INSURANCE_TRANSACTIONS_L3M > 0 AND BANK_2022_NUM_INSURANCE_TRANSACTIONS_L3M <= 2 THEN 1 ELSE 0 END AS bank_2085_c_2,
        CASE WHEN BANK_2022_NUM_INSURANCE_TRANSACTIONS_L3M > 2 AND BANK_2022_NUM_INSURANCE_TRANSACTIONS_L3M <= 5 THEN 1 ELSE 0 END AS bank_2085_d_5,
        CASE WHEN BANK_2022_NUM_INSURANCE_TRANSACTIONS_L3M > 5 AND BANK_2022_NUM_INSURANCE_TRANSACTIONS_L3M <= 10 THEN 1 ELSE 0 END AS bank_2085_e_10,
        CASE WHEN BANK_2022_NUM_INSURANCE_TRANSACTIONS_L3M > 10 THEN 1 ELSE 0 END AS bank_2085_f_11,

        /* bank_2093 */
        CASE WHEN BANK_2022_NUM_DEBT_COLLECTION_TRANSACTIONS_L3M IS NULL THEN 1 ELSE 0 END AS bank_2093_a_null,
        CASE WHEN BANK_2022_NUM_DEBT_COLLECTION_TRANSACTIONS_L3M > 0 THEN 1 ELSE 0 END AS bank_2093_c_1,

        /* bank_2189 */
        CASE WHEN BANK_2022_NUM_PAYDAY_LOAN_PROVIDERS_L3M IS NULL THEN 1 ELSE 0 END AS bank_2189_a_null,
        CASE WHEN BANK_2022_NUM_PAYDAY_LOAN_PROVIDERS_L3M = 1 THEN 1 ELSE 0 END AS bank_2189_c_1,
        CASE WHEN BANK_2022_NUM_PAYDAY_LOAN_PROVIDERS_L3M > 1 THEN 1 ELSE 0 END AS bank_2189_d_2,

        /* bank_2193 */
        CASE WHEN BANK_2022_NUM_PAYDAY_LOAN_DISHONOURS_L3M IS NULL THEN 1 ELSE 0 END AS bank_2193_a_null,
        CASE WHEN BANK_2022_NUM_PAYDAY_LOAN_DISHONOURS_L3M > 0 THEN 1 ELSE 0 END AS bank_2193_c_1,

        /* bank_2197 */
        CASE WHEN BANK_2022_NUM_TOT_DISHONOURS_L3M IS NULL THEN 1 ELSE 0 END AS bank_2197_a_null,
        CASE WHEN BANK_2022_NUM_TOT_DISHONOURS_L3M > 0 AND BANK_2022_NUM_TOT_DISHONOURS_L3M <= 2 THEN 1 ELSE 0 END AS bank_2197_c_2,
        CASE WHEN BANK_2022_NUM_TOT_DISHONOURS_L3M > 2 AND BANK_2022_NUM_TOT_DISHONOURS_L3M <= 5 THEN 1 ELSE 0 END AS bank_2197_d_5,
        CASE WHEN BANK_2022_NUM_TOT_DISHONOURS_L3M > 5 THEN 1 ELSE 0 END AS bank_2197_e_6,

        /* bank_2205 */
        CASE WHEN BANK_2022_AMT_WAGES_L3M IS NULL THEN 1 ELSE 0 END AS bank_2205_a_null,
        CASE WHEN BANK_2022_AMT_WAGES_L3M > 1000  AND BANK_2022_AMT_WAGES_L3M <= 10000 THEN 1 ELSE 0 END AS bank_2205_c_10000,
        CASE WHEN BANK_2022_AMT_WAGES_L3M > 10000 AND BANK_2022_AMT_WAGES_L3M <= 20000 THEN 1 ELSE 0 END AS bank_2205_d_20000,
        CASE WHEN BANK_2022_AMT_WAGES_L3M > 20000 THEN 1 ELSE 0 END AS bank_2205_e_20001,

        /* bank_2213 */
        CASE WHEN BANK_2022_NUM_CENTRELINK_L3M IS NULL THEN 1 ELSE 0 END AS bank_2213_a_null,
        CASE WHEN BANK_2022_NUM_CENTRELINK_L3M > 0 AND BANK_2022_NUM_CENTRELINK_L3M <= 3 THEN 1 ELSE 0 END AS bank_2213_c_3,
        CASE WHEN BANK_2022_NUM_CENTRELINK_L3M > 3 THEN 1 ELSE 0 END AS bank_2213_d_4,

        /* bank_2277 */
        CASE WHEN BANK_2022_NUM_ATM_WITHDRAWALS_L3M IS NULL THEN 1 ELSE 0 END AS bank_2277_a_null,
        CASE WHEN BANK_2022_NUM_ATM_WITHDRAWALS_L3M > 0  AND BANK_2022_NUM_ATM_WITHDRAWALS_L3M <= 10 THEN 1 ELSE 0 END AS bank_2277_c_10,
        CASE WHEN BANK_2022_NUM_ATM_WITHDRAWALS_L3M > 10 AND BANK_2022_NUM_ATM_WITHDRAWALS_L3M <= 20 THEN 1 ELSE 0 END AS bank_2277_d_20,
        CASE WHEN BANK_2022_NUM_ATM_WITHDRAWALS_L3M > 20 AND BANK_2022_NUM_ATM_WITHDRAWALS_L3M <= 30 THEN 1 ELSE 0 END AS bank_2277_e_30,
        CASE WHEN BANK_2022_NUM_ATM_WITHDRAWALS_L3M > 30 THEN 1 ELSE 0 END AS bank_2277_f_31,

        /* bank_2308 */
        CASE WHEN BANK_2022_NUM_JOBSEEKER_L3M IS NULL THEN 1 ELSE 0 END AS bank_2308_a_null,
        CASE WHEN BANK_2022_NUM_JOBSEEKER_L3M > 0 AND BANK_2022_NUM_JOBSEEKER_L3M <= 5 THEN 1 ELSE 0 END AS bank_2308_c_5,
        CASE WHEN BANK_2022_NUM_JOBSEEKER_L3M > 5 THEN 1 ELSE 0 END AS bank_2308_d_6,

        /* bank_5001 */
        CASE WHEN BANK_2022_NUM_HOME_LOAN_ACC > 0 THEN 1 ELSE 0 END AS bank_5001_b_1

    FROM src s
),

coeffs AS (
    SELECT
        b.*,

        /* coefficient contribution columns */
        bank_0002_a_null * (-0.61443605) AS c_bank_0002_a_null,
        bank_0002_c_40   * (-0.33178761) AS c_bank_0002_c_40,
        bank_0002_e_200  * (-0.62360056) AS c_bank_0002_e_200,
        bank_0002_f_201  * (-0.76348899) AS c_bank_0002_f_201,

        bank_1073_a_null * (-0.56503010) AS c_bank_1073_a_null,
        bank_1073_c_05   * (-0.40293619) AS c_bank_1073_c_05,
        bank_1073_d_075  * (-0.62062796) AS c_bank_1073_d_075,
        bank_1073_e_10   * (-0.82678667) AS c_bank_1073_e_10,
        bank_1073_f_30   * (-0.94670184) AS c_bank_1073_f_30,
        bank_1073_g_31   * (-1.07788428) AS c_bank_1073_g_31,

        bank_2024_a_null * ( 0.03743078) AS c_bank_2024_a_null,
        bank_2024_c_30   * ( 0.27183078) AS c_bank_2024_c_30,
        bank_2024_d_31   * ( 0.79175127) AS c_bank_2024_d_31,

        bank_2072_a_null * (-0.72076397) AS c_bank_2072_a_null,
        bank_2072_c_05   * (-0.17966396) AS c_bank_2072_c_05,
        bank_2072_d_10   * (-0.40462350) AS c_bank_2072_d_10,
        bank_2072_e_15   * (-0.48013733) AS c_bank_2072_e_15,
        bank_2072_f_25   * (-0.52917432) AS c_bank_2072_f_25,
        bank_2072_g_50   * (-0.72880294) AS c_bank_2072_g_50,
        bank_2072_h_51   * (-1.01318825) AS c_bank_2072_h_51,

        bank_2085_a_null * ( 0.03743078) AS c_bank_2085_a_null,
        bank_2085_c_2    * (-0.32276825) AS c_bank_2085_c_2,
        bank_2085_d_5    * (-0.65078694) AS c_bank_2085_d_5,
        bank_2085_e_10   * (-0.94167354) AS c_bank_2085_e_10,
        bank_2085_f_11   * (-1.10691671) AS c_bank_2085_f_11,

        bank_2093_a_null * ( 0.03743078) AS c_bank_2093_a_null,
        bank_2093_c_1    * ( 0.05499711) AS c_bank_2093_c_1,

        bank_2189_a_null * ( 0.03743078) AS c_bank_2189_a_null,
        bank_2189_c_1    * ( 0.31760317) AS c_bank_2189_c_1,
        bank_2189_d_2    * ( 0.72595970) AS c_bank_2189_d_2,

        bank_2193_a_null * ( 0.03743078) AS c_bank_2193_a_null,
        bank_2193_c_1    * ( 0.19508913) AS c_bank_2193_c_1,

        bank_2197_a_null * ( 0.03743078) AS c_bank_2197_a_null,
        bank_2197_c_2    * ( 0.10194643) AS c_bank_2197_c_2,
        bank_2197_d_5    * ( 0.19696173) AS c_bank_2197_d_5,
        bank_2197_e_6    * ( 0.51491751) AS c_bank_2197_e_6,

        bank_2205_a_null   * ( 0.03743078) AS c_bank_2205_a_null,
        bank_2205_c_10000  * (-0.29581302) AS c_bank_2205_c_10000,
        bank_2205_d_20000  * (-0.60038669) AS c_bank_2205_d_20000,
        bank_2205_e_20001  * (-0.98296361) AS c_bank_2205_e_20001,

        bank_2213_a_null * ( 0.03743078) AS c_bank_2213_a_null,
        bank_2213_c_3    * ( 0.13707419) AS c_bank_2213_c_3,
        bank_2213_d_4    * ( 0.16595391) AS c_bank_2213_d_4,

        bank_2277_a_null * ( 0.03743078) AS c_bank_2277_a_null,
        bank_2277_c_10   * ( 0.43985471) AS c_bank_2277_c_10,
        bank_2277_d_20   * ( 1.04723958) AS c_bank_2277_d_20,
        bank_2277_e_30   * ( 1.39422014) AS c_bank_2277_e_30,
        bank_2277_f_31   * ( 1.48924862) AS c_bank_2277_f_31,

        bank_2308_a_null * ( 0.03743078) AS c_bank_2308_a_null,
        bank_2308_c_5    * ( 0.06769672) AS c_bank_2308_c_5,
        bank_2308_d_6    * ( 0.56073297) AS c_bank_2308_d_6,

        bank_5001_b_1    * (-0.99723406) AS c_bank_5001_b_1

    FROM bins b
),

scored AS (
    SELECT
        c.*,

        /* linear predictor / logit */
        (
            -1.91506953
            + c_bank_0002_a_null
            + c_bank_0002_c_40
            + c_bank_0002_e_200
            + c_bank_0002_f_201
            + c_bank_1073_a_null
            + c_bank_1073_c_05
            + c_bank_1073_d_075
            + c_bank_1073_e_10
            + c_bank_1073_f_30
            + c_bank_1073_g_31
            + c_bank_2024_a_null
            + c_bank_2024_c_30
            + c_bank_2024_d_31
            + c_bank_2072_a_null
            + c_bank_2072_c_05
            + c_bank_2072_d_10
            + c_bank_2072_e_15
            + c_bank_2072_f_25
            + c_bank_2072_g_50
            + c_bank_2072_h_51
            + c_bank_2085_a_null
            + c_bank_2085_c_2
            + c_bank_2085_d_5
            + c_bank_2085_e_10
            + c_bank_2085_f_11
            + c_bank_2093_a_null
            + c_bank_2093_c_1
            + c_bank_2189_a_null
            + c_bank_2189_c_1
            + c_bank_2189_d_2
            + c_bank_2193_a_null
            + c_bank_2193_c_1
            + c_bank_2197_a_null
            + c_bank_2197_c_2
            + c_bank_2197_d_5
            + c_bank_2197_e_6
            + c_bank_2205_a_null
            + c_bank_2205_c_10000
            + c_bank_2205_d_20000
            + c_bank_2205_e_20001
            + c_bank_2213_a_null
            + c_bank_2213_c_3
            + c_bank_2213_d_4
            + c_bank_2277_a_null
            + c_bank_2277_c_10
            + c_bank_2277_d_20
            + c_bank_2277_e_30
            + c_bank_2277_f_31
            + c_bank_2308_a_null
            + c_bank_2308_c_5
            + c_bank_2308_d_6
            + c_bank_5001_b_1
        ) AS logit_bad,

        /* raw probability of bad */
        1 / (1 + EXP(-(
            -1.91506953
            + c_bank_0002_a_null
            + c_bank_0002_c_40
            + c_bank_0002_e_200
            + c_bank_0002_f_201
            + c_bank_1073_a_null
            + c_bank_1073_c_05
            + c_bank_1073_d_075
            + c_bank_1073_e_10
            + c_bank_1073_f_30
            + c_bank_1073_g_31
            + c_bank_2024_a_null
            + c_bank_2024_c_30
            + c_bank_2024_d_31
            + c_bank_2072_a_null
            + c_bank_2072_c_05
            + c_bank_2072_d_10
            + c_bank_2072_e_15
            + c_bank_2072_f_25
            + c_bank_2072_g_50
            + c_bank_2072_h_51
            + c_bank_2085_a_null
            + c_bank_2085_c_2
            + c_bank_2085_d_5
            + c_bank_2085_e_10
            + c_bank_2085_f_11
            + c_bank_2093_a_null
            + c_bank_2093_c_1
            + c_bank_2189_a_null
            + c_bank_2189_c_1
            + c_bank_2189_d_2
            + c_bank_2193_a_null
            + c_bank_2193_c_1
            + c_bank_2197_a_null
            + c_bank_2197_c_2
            + c_bank_2197_d_5
            + c_bank_2197_e_6
            + c_bank_2205_a_null
            + c_bank_2205_c_10000
            + c_bank_2205_d_20000
            + c_bank_2205_e_20001
            + c_bank_2213_a_null
            + c_bank_2213_c_3
            + c_bank_2213_d_4
            + c_bank_2277_a_null
            + c_bank_2277_c_10
            + c_bank_2277_d_20
            + c_bank_2277_e_30
            + c_bank_2277_f_31
            + c_bank_2308_a_null
            + c_bank_2308_c_5
            + c_bank_2308_d_6
            + c_bank_5001_b_1
        ))) AS prob_bad

    FROM coeffs c
)

SELECT prob_bad, bank_score_2022 FROM scored where prob_bad;
```