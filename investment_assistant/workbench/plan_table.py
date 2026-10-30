"""`python -m investment_assistant.workbench.plan_table show --session D`: the plan table in the terminal (v2.9 §9.2).

A thin shell over ``plan_views.main`` (read-only): the three groups of 「今日」 (entry / holding / ended) without the page.
"""
from investment_assistant.workbench.plan_views import main

if __name__ == '__main__':
    raise SystemExit(main())
