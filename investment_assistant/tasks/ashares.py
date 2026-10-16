"""Manually verified A-share task; notifications are always disabled."""
from __future__ import annotations

import argparse
import json
from datetime import date

from investment_assistant.ashare import service
from investment_assistant.ashare.domain import today_cn, trading_day
from investment_assistant.config import load_config
from investment_assistant.db import close_pools
from investment_assistant.tasks._harness import run_task


def run(config, *, start_date=None, end_date=None, trigger_source='scheduled', symbols=None,
        datasets=None, retry_failed=False):
    def core():
        if trigger_source == 'scheduled' and not trading_day(today_cn()):
            return {'skipped': 'A股休市日；Asia/Shanghai', 'notifications': 'disabled'}
        return service.sync(symbols, start=start_date, end=end_date, datasets=datasets, retry_failed=retry_failed)
    return run_task('ashares', core, config=config, trigger_source=trigger_source, notify=False,
        target_start_date=date.fromisoformat(str(start_date)) if start_date else None,
        target_end_date=date.fromisoformat(str(end_date)) if end_date else None)


def main():
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(description='少量关注A股更新；不发送通知')
    parser.add_argument('--symbols', help='例如688008.SH，多个用逗号分隔；默认现有A股关注列表')
    parser.add_argument('--from', dest='start')
    parser.add_argument('--to', dest='end')
    parser.add_argument('--datasets', help='逗号分隔，仅更新指定数据集')
    parser.add_argument('--retry-failed', action='store_true')
    args = parser.parse_args()
    try:
        result = run(load_config(), symbols=args.symbols.split(',') if args.symbols else None,
            start_date=args.start, end_date=args.end, datasets=args.datasets.split(',') if args.datasets else None,
            retry_failed=args.retry_failed, trigger_source='manual')
        print(json.dumps(result, ensure_ascii=False, default=str, indent=2))
    finally:
        close_pools()


if __name__ == '__main__':
    main()
