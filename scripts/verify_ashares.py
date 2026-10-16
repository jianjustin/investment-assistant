"""Local acceptance: read back real data, verify PDF links, optionally create the first research card.

No notification, order, deployment or schedule enabling. Only --seed-card writes
the authorized example card and watchlist item, and only if the card is absent.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    from investment_assistant.ashare import cards, service
    from investment_assistant.db import close_pools, list_scheduled_jobs, list_watchlist_items
    from investment_assistant.services.watchlist import add_watchlist_item, current_watchlist
    import requests

    parser = argparse.ArgumentParser()
    parser.add_argument('--seed-card', action='store_true')
    parser.add_argument('--expect-schedule', choices=['enabled', 'disabled'],
                        help='可选：核对调度开关，不修改调度配置')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / '.local/ashare/verification.json'
    try:
        v = service.view('688008.SH', start='2025-09-10', end='2026-10-15')
        f = v['financials'][0]
        q1 = next(r for r in v['financials'] if r['period_end'] == '2026-03-31')
        prior = next(r for r in v['financials'] if r['period_end'] == '2025-06-30')
        assert abs(f['quarter']['revenue'] - (f['revenue'] - q1['revenue'])) < .01
        assert f['shares'] and f['quarter']['gross_margin_pct'] is not None
        annual = next(a for a in v['announcements'] if '2026年半年度报告' in a['title'] and '摘要' not in a['title'])
        sale = next(a for a in v['announcements'] if '减持股份计划' in a['title'])
        documents = []
        for a in (annual, sale):
            # Range check proves the link returns a PDF, without adding a full-text ingestion capability.
            r = requests.get(a['original_url'], headers={'Range': 'bytes=0-2047'}, stream=True, timeout=20)
            first = next(r.iter_content(2048), b'')
            r.close()
            assert r.status_code in (200, 206) and first.startswith(b'%PDF'), a['original_url']
            documents.append({'title': a['title'], 'url': a['original_url'], 'http': r.status_code, 'pdf_header': True})
        references = cards.us_references()
        if args.seed_card and not cards.get('688008.SH'):
            links = []
            products = {
                'MU': ('服务器DDR5内存需求 → 澜起DDR5 RCD/DB接口芯片',
                       '需核实服务器DIMM的DDR5渗透、每条内存接口芯片用量、客户采用和澜起份额；MU的HBM增长不能直接等同DDR5接口增长。'),
                'CRDO': ('高速互连/AEC研究 → 澜起PCIe Retimer研究',
                         'AEC/SerDes与PCIe Retimer并非同一产品；需核对PCIe代际升级、通道损耗、板卡拓扑、设计导入、量产和客户份额，不能假定收入同步。'),
                'NVDA': ('AI服务器平台与互连拓扑 → DDR5接口及PCIe Retimer需求',
                         '须确认对应服务器平台使用的内存配置和PCIe链路确需澜起产品、已被客户采用且进入量产；AI资本支出只提供需求背景。'),
            }
            for ticker in ('MU', 'CRDO', 'NVDA'):
                ref = next((r for r in references if r['ticker'] == ticker and r['facts'].get('revenue')), None)
                fact = ref['facts']['revenue'] if ref else {}
                links.append({'ticker': ticker, 'filing_id': ref['id'] if ref else None,
                    'products': products[ticker][0], 'transmission_condition': products[ticker][1],
                    'fiscal_period': str(fact.get('period') or '实际报告期尚待核对'),
                    'currency': str(fact.get('unit') or 'USD，待原文核对'),
                    'accounting_basis': str(fact.get('basis') or 'GAAP/non-GAAP待核对'), 'status': 'pending'})
            body = {
                'improvement': {'hypothesis': '分析假设，待验证：若服务器DDR5升级和PCIe代际升级持续，且澜起相关产品获得客户采用并转为量产，接口芯片与Retimer可能支持未来数周至数月的经营改善。当前财务增长不能单独证明这条产品传导链。',
                    'products': 'DDR5 RCD/DB接口芯片；PCIe Retimer（产品收入、订单与客户采用未自动提取）',
                    'expected_window': '未来数周至数月，以下一季财报和公司披露逐项核验',
                    'next_event': '2026年三季报：预约日期可能变动，核对产品结构、扣非利润与现金流',
                    'next_event_date': '2026-10-30'},
                'evidence': [
                    {'claim': f'2026上半年累计收入{f["revenue"]/1e8:.4f}亿元，较2025同期{prior["revenue"]/1e8:.4f}亿元增长{(f["revenue"]/prior["revenue"]-1)*100:.2f}%；支持公司层面改善，不能直接归因DDR5或Retimer。',
                     'stance': 'supports', 'observation_id': f['id'], 'source_url': annual['original_url'],
                     'occurred_at': '2026-01-01—2026-06-30', 'disclosed_at': f['first_disclosed_date'], 'method': 'calculated'},
                    {'claim': f'2026上半年归母净利{f["parent_profit"]/1e8:.4f}亿元、扣非{f["deducted_profit"]/1e8:.4f}亿元，两者差额{(f["parent_profit"]-f["deducted_profit"])/1e8:.4f}亿元。反对将归母增幅全部解释为主营改善；扣非也不等于纯主营利润。',
                     'stance': 'opposes', 'observation_id': f['id'], 'source_url': annual['original_url'],
                     'occurred_at': '2026-01-01—2026-06-30', 'disclosed_at': f['first_disclosed_date'], 'method': 'calculated'},
                    {'claim': '已有股东减持计划公告。计划执行、规模与动因尚未全文核实，不将标题直接视为经营恶化证据。',
                     'stance': 'pending', 'observation_id': sale['id'], 'source_url': sale['original_url'],
                     'occurred_at': None, 'disclosed_at': sale['notice_date'], 'method': 'disclosed'},
                ],
                'scenarios': [{'label': '敏感性起点：半年利润机械年化（可修改）', 'method': 'mechanical_annualization',
                    'profit_cny': f['parent_profit'] * 2, 'pe': 40, 'shares': f['shares'], 'period': '2026H1×2，非2026全年预测',
                    'share_basis': '2026-06-30来源TOTAL_SHARE期末总股数，包含A/H时不拆分；并非加权平均EPS口径',
                    'source_url': annual['original_url'],
                    'note': '利润=半年归母×2，忽略季节性且含非经常项；40倍PE仅为可调整的分析假设，非公司指引。跨A/H价格及股本差异未复算，不将情景值视为目标价。'}],
                'invalidations': [{'condition': '分析设定，待用户复核：未来两个可比季度若收入改善停滞且扣非盈利/经营现金流同步转弱，或公司证据否定关键产品导入，则复核假设。',
                    'indicator': '同比收入、单季扣非、经营现金流/利润、应收与存货；产品量产/客户采用原文',
                    'review_date': '2026-10-30', 'result': 'pending', 'checked_at': None,
                    'note': '需先取得三季报并核对累计差分和来源版本；系统不自动改变投资判断。'}],
                'links': links,
            }
            cards.save('688008.SH', body, 0)
            add_watchlist_item({'ticker': '688008.SH', 'status': 'active', 'tags': ['A股', '半导体'],
                                'thesis': body['improvement']['hypothesis']})
        with service.connection() as conn:
            wl = list_watchlist_items(conn)
            jobs = list_scheduled_jobs(conn)
            counts = conn.execute('SELECT ticker,count(*) FROM filings GROUP BY ticker ORDER BY ticker').fetchall()
        historical = service.view('688008.SH', start='2025-09-10', end='2026-10-15', as_of='2026-10-15T23:59:59+08:00')
        assert not historical['financials'] and not historical['bars']
        assert '688008.SH' not in current_watchlist()
        if args.expect_schedule:
            assert next(j for j in jobs if j['name'] == 'ashares')['enabled'] is (args.expect_schedule == 'enabled')
        report = {'security': v['profile']['name'], 'window': v['window'],
            'status': [(s['dataset'], s['status'], s.get('stored_rows')) for s in v['statuses']],
            'raw_price': {'date': v['raw_bars'][-1]['date'], 'close': v['raw_bars'][-1]['close']},
            'financial_check': {key: f[key] for key in ('period_end','revenue','parent_profit','deducted_profit','shares','quarter','ttm')},
            'pdf_links': documents, 'card_version': (cards.get('688008.SH') or {}).get('version'),
            'watchlist': [r['ticker'] for r in wl], 'us_scan_watchlist': current_watchlist(),
            'sec_index_counts': counts, 'scheduled_jobs': jobs, 'strict_pit': False,
            'historical_before_first_collection': {'financials': 0, 'bars': 0},
            'scope': '真实来源链接/数据库/服务层回读；不等同浏览器或用户验收；没有发送通知'}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    finally:
        close_pools()


if __name__ == '__main__':
    main()
