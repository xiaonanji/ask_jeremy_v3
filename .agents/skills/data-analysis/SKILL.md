---
name: data-analysis
description: How to perform data analysis using SQL and data warehouse tables, including best practices, common techniques, and example queries.
---

## Identify task type

Always check the type of task as the first step. If the task is an open investigation question, follow the steps outlined in the "If user asks open investigation questions" section below. If the task is a simple data extraction task, follow the steps outlined in the "If user asks for simple data extraction tasks" section below.

A key sign of an open investigation question is that the user is asking "why" or "how" questions that require analysis and interpretation of data, rather than just retrieving specific data points. For example, "Why did the bank score drop for a certain application?" or "How does the distribution of bank scores look like for different products?" are open investigation questions. On the other hand, "What is the bank score for application ID 12345?" or "How many applications were submitted in the last month?" are simple data extraction tasks.

## Investigation task instruction

If user asks open investigation questions, follow the following steps to perform the task:

1. Always design the plans for investigation before execution.
2. Carry out each step of the plan, check the results, and adjust the plan if necessary before moving to the next step.
3. If a step is to verify a hypothesis, make sure to clearly state the hypothesis and the expected results before running the query.
4. Always check the data quality and consistency before drawing conclusions from the analysis.
5. Pay attention to seasonality, trends, and outliers in the data, and consider them in the analysis.
6. When drafting the final findings and conclusions, make sure to clearly state the insights derived from the data, the supporting evidence, and any limitations or assumptions in the analysis.

## Data extraction task instruction

If user asks for simple data extraction tasks, follow the following steps:

1. Clarify the data requirements and the expected output format with the user before writing the query.
2. Always design the plans for data extraction before execution. Consider the most efficient way to retrieve the data, such as filtering, aggregating, or joining tables.
3. Carry out each step of the plan, check the results, and adjust the plan if necessary before moving to the next step.