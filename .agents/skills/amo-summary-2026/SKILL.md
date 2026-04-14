---
name: amo-summary-2026
description: the explanation of the AMO summary 2026 Sqlite database
---

The database contains a single table called `amo_summary_2026`. This table contains students who received `Honourable Mention` or above awards in the AMO Summary exam 2026. The table contains the following columns:
- `Name`: this is the first name of the students
- `Surname`: this is the last name of the students
- `Year`: this is a numeric column indicates which year the student was when they took the exam
- `School`: this is the school name where the student studied when they took the exam
- `State`: this is the state where the student lives
- `Total Score`: this is the score of the exam. `Honourable Mention` students don't have the scores.
- `Award`: this is the award column. The awards are:
	* `Honourable Mention`
	* `Bronze`
	* `Silver`
	* `Gold`
	* `Gold with Perfect Score`