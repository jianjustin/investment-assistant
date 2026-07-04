from . import status, market, tickers, strategies, hermes, watchlist, runs, jobs, settings, research

ALL_ROUTERS = [
    status.router, market.router, tickers.router, strategies.router,
    hermes.router, watchlist.router, runs.router, jobs.router,
    settings.router, research.router,
]
