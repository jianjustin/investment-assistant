from . import status, market, tickers, strategies, hermes, watchlist, runs, jobs, settings, research  # noqa: F401

# FastAPI 路由表：后续任务逐域把重写为 APIRouter 的模块追加进来
ALL_ROUTERS = [status.router, market.router, tickers.router, strategies.router]
