from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body

from investment_assistant.ashare import cards, service
from investment_assistant.config import load_config
from investment_assistant.tasks import runner

router = APIRouter()


@router.get('/api/ashares/security/{symbol}')
def resolve(symbol: str):
    return service.resolve(symbol)


@router.get('/api/ashares/{symbol}/research')
def research(symbol: str, start: str | None = None, end: str | None = None,
             basis: str = 'qfq', as_of: str | None = None):
    result = service.view(symbol, start=start, end=end, basis=basis, as_of=as_of)
    if result['card']:
        result['card']['scenario_values'] = cards.scenario_values(result['card']['body'])
    return result


@router.post('/api/ashares/sync')
def sync(payload: dict[str, Any] = Body(default_factory=dict)):
    from investment_assistant.tasks.ashares import run
    service.window(payload.get('start'), payload.get('end'))
    symbols = payload.get('symbols')
    if symbols is not None and (not isinstance(symbols, list) or not symbols):
        raise ValueError('symbols须为非空股票列表')
    if symbols:
        for symbol in symbols:
            service.stock_id(symbol)
    datasets = payload.get('datasets')
    if datasets is not None and (not isinstance(datasets, list) or not datasets or set(datasets) - set(service.DATASETS)):
        raise ValueError('未知数据集')
    run_id = runner.submit('ashares', lambda: run(load_config(), symbols=symbols,
        start_date=payload.get('start'), end_date=payload.get('end'), datasets=datasets,
        retry_failed=bool(payload.get('retry_failed')), trigger_source='manual'))
    return {'run_id': run_id, 'status': 'pending'}
