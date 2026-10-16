"""Small, explicit-symbol source adapters. Never initiate a market-wide crawl.

Field contracts and the Sina factor parser are adapted from CNEquity v0.16.0,
c118038ea82b5bb78783c0c17a1d9251b36de71d (Apache-2.0); see vendor/NOTICE.
HTTP, bounds, snapshot provenance and PostgreSQL integration are workbench code.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from .domain import BENCHMARKS, SHANGHAI, stock_id, today_cn
from .vendor.numeric import finite_int64

DATACENTER = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
BARS_URL = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
ANN_URL = 'https://np-anotice-stock.eastmoney.com/api/security/ann'
DEFAULT_ARCHIVE = Path(__file__).resolve().parents[2] / '.local/ashare/raw'
UPSTREAM_COMMIT = 'c118038ea82b5bb78783c0c17a1d9251b36de71d'


def number(value):
    """Adapted from CNEquity eastmoney/common._to_float; unknown remains null."""
    if value is None or value in ('', '-'):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def day(value):
    return date.fromisoformat(str(value)[:10]).isoformat() if value else None


def disclosed_after_day(value):
    """Date-only disclosure becomes available no earlier than next local day.

    This is NOT a strict PIT assertion: the version was first observed now.
    """
    if not value:
        return None
    d = date.fromisoformat(str(value)[:10]) + timedelta(days=1)
    return datetime(d.year, d.month, d.day, tzinfo=SHANGHAI).isoformat()


class SourceError(RuntimeError):
    pass


class PublicSources:
    def __init__(self, *, session=None, archive=DEFAULT_ARCHIVE):
        self.session = session or requests.Session()
        self.archive = Path(archive)
        self.last_request = 0.0

    def get(self, url, params=None, *, text=False):
        # Bounded retries, no proxy rotation, credentials, cookies or bypasses.
        for attempt in range(2):
            time.sleep(max(0, .35 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                r = self.session.get(url, params=params, timeout=(5, 15),
                                     headers={'User-Agent': 'investment-assistant-local-research/1.0'},
                                     allow_redirects=False)
            except requests.RequestException as exc:
                if attempt == 0:
                    continue
                raise SourceError(f'{type(exc).__name__}: 来源连接失败') from None
            if r.status_code == 429:
                raise SourceError('HTTP 429: 来源限流；稍后手动续跑')
            if r.status_code >= 500 and attempt == 0:
                continue
            if r.status_code != 200:
                raise SourceError(f'HTTP {r.status_code}: 来源拒绝或不可用')
            digest = hashlib.sha256(r.content).hexdigest()
            self.archive.mkdir(parents=True, exist_ok=True)
            path = self.archive / (digest + '.response')
            if not path.exists():
                path.write_bytes(r.content)
            provenance = {'source_url': r.url, 'response_sha256': digest}
            if text:
                return r.text, provenance
            try:
                return r.json(), provenance
            except ValueError:
                raise SourceError('来源返回非JSON内容，不能视为零记录') from None
        raise SourceError('来源重试耗尽')

    def report(self, name, symbol, *, sort=None, lower=None, upper=None, date_field=None, extra_filter=''):
        stock_id(symbol)
        filters = f'(SECUCODE="{symbol}")'
        if date_field and lower:
            filters += f'({date_field}>=\'{lower}\')'
        if date_field and upper:
            filters += f'({date_field}<=\'{upper}\')'
        filters += extra_filter
        rows, provenance = [], []
        for page in range(1, 11):
            params = {'reportName': name, 'columns': 'ALL', 'filter': filters,
                      'pageSize': 100, 'pageNumber': page}
            if sort:
                params.update(sortColumns=sort, sortTypes=-1)
            payload, origin = self.get(DATACENTER, params)
            provenance.append(origin)
            if not isinstance(payload, dict):
                raise SourceError(f'{name}: 非法响应结构')
            if not payload.get('success'):
                if payload.get('message') == '返回数据为空' and page == 1:
                    return [], provenance
                raise SourceError(f'{name}: 来源业务失败 code={payload.get("code")}')
            result = payload.get('result')
            if not isinstance(result, dict) or not isinstance(result.get('data'), list):
                raise SourceError(f'{name}: 缺少数据或分页元信息')
            batch = result['data']
            pages = finite_int64(result.get('pages'), minimum=0)
            if pages > 10:
                raise SourceError(f'{name}: 超出单证券1000条上限；拒绝扩大采集')
            if page <= pages and not batch:
                raise SourceError(f'{name}: 分页中途缺失')
            for row in batch:
                if row.get('SECUCODE') != symbol:
                    raise SourceError(f'{name}: 来源未遵守证券过滤')
                if date_field:
                    d = day(row.get(date_field))
                    if not d or (lower and d < lower) or (upper and d > upper):
                        raise SourceError(f'{name}: 来源未遵守日期过滤')
            rows.extend(batch)
            if page >= pages:
                if result.get('count') is not None and len(rows) != int(result['count']):
                    raise SourceError(f'{name}: 分页数量不一致')
                return rows, provenance
        raise SourceError('分页未结束')

    def profile(self, sid, start, end):
        symbol = sid.split(':')[-1]
        rows, origin = self.report('RPT_F10_ORG_BASICINFO', symbol)
        if not rows:
            return []
        r = rows[0]
        if r.get('SECURITY_TYPE') != 'A股' or not r.get('SECURITY_NAME_ABBR'):
            raise SourceError('主数据未确认A股名称/类型')
        return [self.record('current', today_cn().isoformat(), {
            'symbol': symbol, 'name': r['SECURITY_NAME_ABBR'], 'exchange': symbol.split('.')[1],
            'asset_type': 'stock', 'market': 'CN', 'board': r.get('TRADE_MARKET'),
            'listing_date': day(r.get('LISTING_DATE')), 'listing_status': 'unknown',
            'provider_listing_state': r.get('LISTING_STATE'),
            'listing_status_note': f'来源状态码{r.get("LISTING_STATE")}的枚举尚未独立核实；上市日期已取得，当前退市/暂停上市状态保留未知',
            'currency': 'CNY', 'timezone': 'Asia/Shanghai', 'industry': r.get('EM2016'),
            'raw': r, 'coverage_kind': 'current_snapshot', 'origins': origin,
        }, origin[0])]

    @staticmethod
    def record(key, data_date, payload, origin, disclosed_at=None):
        return {'natural_key': key, 'data_date': data_date, 'payload': payload,
                'disclosed_at': disclosed_at, 'source': 'public_source', **origin}

    def bars(self, sid, start, end):
        symbol = sid.split(':')[-1]
        if sid in BENCHMARKS:
            secid = BENCHMARKS[sid]['secid']
        else:
            stock_id(symbol)
            code, exchange = symbol.split('.')
            if exchange == 'BJ':
                raise SourceError('首批日线暂未验证北交所代码迁移/市场路由')
            secid = f'{1 if exchange == "SH" else 0}.{code}'
        data, origin = self.get(BARS_URL, {'secid': secid, 'klt': 101, 'fqt': 0,
            'beg': start.strftime('%Y%m%d'), 'end': end.strftime('%Y%m%d'),
            'fields1': 'f1,f2,f3,f4,f5,f6', 'fields2': 'f51,f52,f53,f54,f55,f56,f57'})
        if data.get('rc') != 0 or not isinstance(data.get('data'), dict):
            raise SourceError('日线来源未返回有效证券；不是“没有行情”')
        data = data['data']
        if data.get('code') != symbol.split('.')[0]:
            raise SourceError('日线证券代码不匹配')
        rows = []
        for raw in data.get('klines', []):
            vals = raw.split(',')
            if len(vals) != 7:
                raise SourceError('日线字段数量改变')
            d = date.fromisoformat(vals[0])
            if not start <= d <= end:
                raise SourceError('日线超出请求窗口')
            o, c, h, l, volume, amount = [number(v) for v in vals[1:]]
            if any(v is None or v <= 0 for v in (o, c, h, l)) or h < max(o, c) or l > min(o, c):
                raise SourceError('日线价格无效')
            if volume is not None and volume < 0 or amount is not None and amount < 0:
                raise SourceError('成交量/额无效')
            # Stock volumes are lots (100 shares); index volumes retain vendor lots.
            payload = {'date': vals[0], 'open': o, 'close': c, 'high': h, 'low': l,
                       'volume': finite_int64(volume * 100, minimum=0) if volume is not None and sid not in BENCHMARKS else volume,
                       'volume_unit': '股' if sid not in BENCHMARKS else '来源手数（指数）',
                       'amount': amount, 'amount_unit': 'CNY元', 'price_basis': 'raw',
                       'name': data.get('name'), 'currency': 'CNY', 'timezone': 'Asia/Shanghai',
                       'coverage_kind': 'historical_backfill_current_version'}
            rows.append(self.record(vals[0], vals[0], payload, origin))
        return rows

    def factors(self, sid, start, end):
        code, exchange = sid.split(':')[-1].split('.')
        url = f'https://finance.sina.com.cn/realstock/company/{exchange.lower()}{code}/hfq.js'
        text, origin = self.get(url, text=True)
        # Adapted from CNEquity sina/adj_factors._parse_sina_factor_payload.
        match = re.search(r'=\s*(\{.*\})', text, re.DOTALL)
        if not match:
            raise SourceError('新浪复权因子没有JSON内容')
        data = json.loads(match.group(1)).get('data')
        if not isinstance(data, list) or not data:
            raise SourceError('复权因子缺失；不以1补齐')
        values = {}
        for r in data:
            d, f = day(r.get('d') or r.get('date')), number(r.get('f'))
            if not d or f is None or f <= 0:
                raise SourceError('复权因子日期/乘数无效')
            values[d] = f
        payload = {'factors': [{'date': d, 'factor': f} for d, f in sorted(values.items())],
                   'basis': 'hfq_multiplier', 'coverage_kind': 'current_factor_snapshot',
                   'limitation': '当前新浪后复权乘数快照；历史版本自首次采集积累，不支持启用前严格PIT'}
        return [self.record('current', today_cn().isoformat(), payload, origin)]

    def financials(self, sid, start, end):
        symbol = sid.split(':')[-1]
        # Eight recent quarters suffice for two comparable YTD years + TTM.
        lower = date(end.year - 2, 1, 1).isoformat()
        specs = [('RPT_LICO_FN_CPD', 'REPORTDATE'), ('RPT_DMSK_FN_BALANCE', 'REPORT_DATE'),
                 ('RPT_DMSK_FN_INCOME', 'REPORT_DATE'), ('RPT_DMSK_FN_CASHFLOW', 'REPORT_DATE')]
        reports, origins, component_errors = {}, {}, {}
        for name, field in specs:
            try:
                rows, origin = self.report(name, symbol, sort=field, date_field=field,
                                           lower=lower, upper=end.isoformat())
            except SourceError as exc:
                if name == specs[0][0]:
                    raise  # Headline report anchors report periods and disclosure dates.
                rows, origin = [], []
                component_errors[name] = str(exc)
            reports[name] = {day(r[field]): r for r in rows}
            origins[name] = origin
        # The four CNEquity statements do not expose capital in this response.
        # This additional report is a workbench adapter, not copied CNEquity functionality.
        try:
            share_rows, share_origin = self.report('RPT_F10_FINANCE_MAINFINADATA', symbol, sort='REPORT_DATE',
                date_field='REPORT_DATE', lower=lower, upper=end.isoformat())
        except SourceError as exc:
            share_rows, share_origin = [], []
            component_errors['RPT_F10_FINANCE_MAINFINADATA'] = str(exc)
        share_map = {day(r['REPORT_DATE']): r for r in share_rows}
        origins['RPT_F10_FINANCE_MAINFINADATA'] = share_origin
        out = []
        for period, headline in sorted(reports[specs[0][0]].items(), reverse=True)[:8]:
            balance = reports[specs[1][0]].get(period, {})
            income = reports[specs[2][0]].get(period, {})
            cash = reports[specs[3][0]].get(period, {})
            revenue = number(headline.get('TOTAL_OPERATE_INCOME'))
            cost = number(income.get('OPERATE_COST'))
            # Same scope: financial statement operating revenue minus operating cost.
            operating_revenue = number(income.get('OPERATE_INCOME'))
            margin = number(headline.get('XSMLL'))
            if operating_revenue is None:
                total = number(income.get('TOTAL_OPERATE_INCOME'))
                if total and cost is not None and margin is not None and abs((total - cost) / total * 100 - margin) < .01:
                    operating_revenue = total
            payload = {'period_end': period, 'period_start': period[:4] + '-01-01',
                'flow_basis': 'YTD', 'balance_basis': 'period_end', 'unit': 'CNY元',
                'currency': 'CNY', 'accounting_basis': '中国企业会计准则/合并报表（来源口径）',
                'revenue': revenue, 'parent_profit': number(headline.get('PARENT_NETPROFIT')),
                'deducted_profit': number(income.get('DEDUCT_PARENT_NETPROFIT')),
                'gross_margin_pct': number(headline.get('XSMLL')),
                'gross_profit': operating_revenue - cost if operating_revenue is not None and cost is not None else None,
                'operating_cashflow': number(cash.get('NETCASH_OPERATE')),
                'receivables': number(balance.get('ACCOUNTS_RECE')), 'inventory': number(balance.get('INVENTORY')),
                'shares': number(share_map.get(period, {}).get('TOTAL_SHARE')),
                'shares_basis': '主指标报告TOTAL_SHARE期末总股数，含A/H时不拆分，非加权平均股数；不可据此计算GAAP EPS',
                'eps': number(headline.get('BASIC_EPS')), 'eps_basis': '来源累计基本EPS，不差分、不机械年化',
                'first_disclosed_date': day(headline.get('NOTICE_DATE')),
                'first_disclosed_date_basis': 'LICO提供的首次公告日期，未独立核实历史数值版本',
                'provider_updated_date': day(headline.get('UPDATE_DATE')),
                'provider_republished_dates': {name: day(reports[name].get(period, {}).get('NOTICE_DATE')) for name, _ in specs[1:]},
                'raw_reports': {**{name: reports[name].get(period, {}) for name, _ in specs},
                                'RPT_F10_FINANCE_MAINFINADATA': share_map.get(period, {})},
                'origins': origins, 'coverage_kind': 'historical_backfill_current_version',
                'limitations': ['扣非利润不等于纯主营利润', '历史重述值可能混合，季度差分须核对原文一致性',
                                '报告期过滤不是严格PIT；回填值不早于本机首次采集可用']}
            if component_errors:
                payload['component_errors'] = component_errors
                payload['limitations'] += [f'{name}: {error}' for name, error in component_errors.items()]
            out.append(self.record(period, period, payload, origins[specs[0][0]][0],
                                   disclosed_after_day(headline.get('NOTICE_DATE'))))
        return out

    def valuation(self, sid, start, end):
        rows, origins = self.report('RPT_VALUEANALYSIS_DET', sid.split(':')[-1], sort='TRADE_DATE',
            date_field='TRADE_DATE', lower=start.isoformat(), upper=end.isoformat())
        out = []
        for r in rows:
            d, pe = day(r['TRADE_DATE']), number(r.get('PE_TTM'))
            payload = {'date': d, 'pe_ttm': pe if pe and pe > 0 else None,
                'pe_status': 'available' if pe and pe > 0 else '亏损/零利润或缺失，不适用常规PE',
                'pb_mrq': number(r.get('PB_MRQ')), 'ps_ttm': number(r.get('PS_TTM')),
                'total_market_cap': number(r.get('TOTAL_MARKET_CAP')), 'market_cap_unit': 'CNY元',
                'total_shares': number(r.get('TOTAL_SHARES')),
                'basis': '东方财富PE_TTM/PB_MRQ/PS_TTM；总市值按来源股本口径，A/H未独立复算',
                'coverage_kind': 'historical_backfill_current_version', 'raw': r}
            out.append(self.record(d, d, payload, origins[0]))
        return out

    def announcements(self, sid, start, end):
        code = sid.split(':')[-1].split('.')[0]
        out = []
        for page in range(1, 21):
            data, origin = self.get(ANN_URL, {'sr': -1, 'page_size': 100, 'page_index': page,
                'ann_type': 'A', 'client_source': 'web', 'stock_list': code,
                'begin_time': start.isoformat(), 'end_time': end.isoformat()})
            if data.get('success') != 1 or not isinstance(data.get('data'), dict):
                raise SourceError('公告索引来源失败；不能判断无公告/无风险')
            batch = data['data'].get('list')
            if not isinstance(batch, list) or 'total_hits' not in data['data']:
                raise SourceError('公告索引格式或分页信息缺失')
            for r in batch:
                if not any(c.get('stock_code') == code for c in r.get('codes', [])):
                    raise SourceError('公告证券不匹配')
                d = day(r.get('notice_date'))
                if not d:
                    raise SourceError('公告日期缺失')
                if not start.isoformat() <= d <= end.isoformat():
                    continue
                aid = r.get('art_code', '')
                if not re.fullmatch(r'AN\d+', aid):
                    raise SourceError('公告ID格式变化')
                title = r.get('title', '')
                tags = [label for label, terms in [('减持', ('减持',)), ('解禁', ('解禁', '解除限售')),
                        ('监管候选', ('监管函', '警示函', '处罚', '立案', '调查', '处分'))]
                        if any(term in title for term in terms)]
                payload = {'announcement_id': aid, 'title': title, 'notice_date': d,
                    'display_time': r.get('display_time'), 'provider_ingest_time': r.get('eiTime'),
                    'original_url': f'https://pdf.dfcfw.com/pdf/H2_{aid}_1.pdf',
                    'index_url': f'https://data.eastmoney.com/notices/detail/{code}/{aid}.html',
                    'event_tags': tags, 'event_date': None, 'full_text_parsed': False,
                    'coverage_kind': 'announcement_index', 'raw': r,
                    'limitation': '标题匹配仅作事件线索；非全面监管扫描，不代表无风险；公告日期非可信盘中可用时间'}
                out.append(self.record(aid, d, payload, origin, disclosed_after_day(d)))
            total = int(data['data']['total_hits'])
            if page * 100 >= total:
                return out
            if not batch:
                raise SourceError('公告分页中途缺失')
        raise SourceError('公告超过单证券2000条上限，请缩小窗口')

    def disclosure(self, sid, start, end):
        rows, origins = self.report('RPT_PUBLIC_BS_APPOIN', sid.split(':')[-1], sort='REPORT_DATE',
            date_field='REPORT_DATE', lower=date(end.year, 1, 1).isoformat(),
            upper=(end + timedelta(days=100)).isoformat())
        return [self.record(day(r['REPORT_DATE']), today_cn().isoformat(), {
            'period_end': day(r['REPORT_DATE']), 'scheduled_date': day(r.get('APPOINT_PUBLISH_DATE')),
            'first_scheduled_date': day(r.get('FIRST_APPOINT_DATE')), 'actual_date': day(r.get('ACTUAL_PUBLISH_DATE')),
            'coverage_kind': 'current_snapshot', 'limitation': '预约是当前快照，历史修订仅自启用后积累', 'raw': r}, origins[0]) for r in rows]

    def unlocks(self, sid, start, end):
        # This report has SECURITY_CODE, not SECUCODE; narrow explicitly and check identity.
        code = sid.split(':')[-1].split('.')[0]
        params = {'reportName': 'RPT_LIFT_STAGE', 'columns': 'ALL', 'pageSize': 100, 'pageNumber': 1,
            'filter': f'(SECURITY_CODE="{code}")(FREE_DATE>=\'{start}\')(FREE_DATE<=\'{end + timedelta(days=180)}\')',
            'sortColumns': 'FREE_DATE', 'sortTypes': 1}
        data, origin = self.get(DATACENTER, params)
        if data.get('message') == '返回数据为空':
            return []
        result = data.get('result')
        if not data.get('success') or not isinstance(result, dict) or not isinstance(result.get('data'), list):
            raise SourceError('解禁来源失败；不能判断没有解禁')
        if int(result.get('pages', 0)) > 1:
            raise SourceError('解禁单证券结果超过首批100条上限')
        out = []
        for r in result['data']:
            if r.get('SECURITY_CODE') != code:
                raise SourceError('解禁证券不匹配')
            shares = number(r.get('ABLE_FREE_SHARES'))
            d = day(r.get('FREE_DATE'))
            payload = {'event_date': d, 'shares': shares * 10000 if shares is not None else None,
                'unit': '股（来源万股×10000）', 'share_type': r.get('FREE_SHARES_TYPE'),
                'ratio_pct': number(r.get('FREE_RATIO')), 'coverage_kind': 'current_snapshot', 'raw': r}
            out.append(self.record(f'{d}:{r.get("FREE_SHARES_TYPE")}', today_cn().isoformat(), payload, origin))
        return out
