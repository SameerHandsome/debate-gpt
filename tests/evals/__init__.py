# Eval suite (Day 6) — scaffold only.
#
# Real-eval tests (test_judge_consistency.py, test_position_bias.py,
# eval_report.py) hit the live LLMs and write to eval_results.csv. They
# are Day 6 scope per PRD §9.4 and are not collected by the Day 5
# `pytest` run. They are excluded from `testpaths` discovery so the Day 5
# suite stays fast and offline.
