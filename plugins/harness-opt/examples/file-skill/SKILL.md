---
name: file-summary
description: Count lines and words in a supplied UTF-8 text file and write summary.json.
---
Read the requested UTF-8 text file. Write `summary.json` in the working directory
with integer `lines` and `words` fields. Count lines with Python str.splitlines()
and words with str.split(). Empty input produces both counts zero.
For a missing input, report the missing file and do not create summary.json.
Do not modify the input. Use Python's standard library.
