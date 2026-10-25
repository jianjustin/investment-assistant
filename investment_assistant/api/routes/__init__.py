from . import status, watchlist, runs, jobs, settings, research, filings, us_research, workbench

ALL_ROUTERS = [
    status.router, watchlist.router, runs.router, jobs.router,
    settings.router, research.router, filings.router, us_research.router,
    workbench.router,
]
