import type { ResearchMetric } from './api'
export const metricNames:Record<string,string> = {
 investments:'短期投资',repurchases:'股份回购现金支出',revenue:'营业收入',cost_of_revenue:'营业成本',gross_profit:'毛利',operating_income:'营业利润',net_income:'归母净利润',consolidated_net_income:'合并净利润',common_net_income:'归属普通股股东净利润',eps_diluted:'摊薄每股收益',weighted_shares:'摊薄加权平均股数',shares:'期末普通股在外股数',cfo:'经营现金流',cash_capex:'现金购建固定资产',broad_capex:'广义生产性资产投资',fcf:'标准自由现金流',cash:'现金及等价物',debt:'有息债务合计',receivables:'应收账款',inventory:'存货',sbc:'股权激励费用',gross_margin:'毛利率',operating_margin:'营业利润率',fcf_margin:'自由现金流率',receivable_days:'应收周转天数',inventory_days:'存货周转天数',revenue_yoy:'收入同比',revenue_qoq:'收入环比',long_term_debt_total:'长期债务（含当期到期）',long_term_debt:'非流动长期债务',short_term_debt:'当期到期长期债务',short_term_borrowings:'短期借款',debt_with_leases_current:'流动债务（含租赁）',debt_with_leases_noncurrent:'非流动债务（含租赁）',long_term_debt_with_leases_total:'长期债务及融资租赁合计',pe_ttm:'市盈率 TTM',ps_ttm:'市销率 TTM',fcf_yield:'自由现金流收益率',return:'区间收益',max_drawdown:'最大回撤',SPY:'相对标普500',QQQ:'相对纳斯达克100'
}
export const metricName=(key:string)=>metricNames[key]??key
export const number=(value:any,digits=2)=>value == null || !Number.isFinite(Number(value))?'—':Number(value).toLocaleString('zh-CN',{maximumFractionDigits:digits})
export function metricValue(m?:ResearchMetric){
 if(m?.value==null)return '—'
 if(m.unit==='ratio')return number(m.value*100)+'%'
 if(m.unit==='multiple')return number(m.value)+' 倍'
 if(m.unit==='days')return number(m.value)+' 天'
 if(m.unit==='shares')return number(m.value,0)+' 股'
 return number(m.value)+' '+(m.unit??'单位待确认')
}
const methods:Record<string,string>={reported:'直接披露',unavailable:'尚无可比来源',cumulative_unavailable:'累计数据无法可靠差分',ytd_difference:'本期累计 − 上期累计',annual_minus_nine_months:'全年 − 前九个月',sum_four_contiguous_quarters:'四个连续财季之和',revenue_minus_cost:'收入 − 营业成本',cfo_minus_cash_ppe:'经营现金流 − 现金购建固定资产',aggregate_amount_ratio:'同口径期间总额相除',average_balance_over_quarter_flow_times_days:'期初期末平均余额 ÷ 单季流量 × 实际天数',average_opening_closing_balance:'（期初余额 + 期末余额）÷ 2',comparable_quarter_growth:'本期收入 ÷ 可比前期收入 − 1',end_over_start_minus_one:'期末调整价 ÷ 期初调整价 − 1',minimum_close_over_running_peak_minus_one:'调整收盘价 ÷ 此前最高调整价 − 1 的最小值',stock_return_minus_benchmark_return:'共同日期个股收益 − 基准收益',market_cap_over_ttm:'已核验可比市值 ÷ TTM 金额',fcf_over_market_cap:'TTM 标准自由现金流 ÷ 已核验可比市值',noncurrent_plus_current_debt_including_finance_leases:'流动债务 + 非流动债务（含融资租赁）',noncurrent_plus_current_long_term_debt:'非流动长期债务 + 当期到期长期债务',long_term_total_plus_short_borrowings:'长期债务总额 + 短期借款'}
export const methodName=(method?:string)=>methods[method??'']??'计算方法待核对'
export const basisName=(basis?:string|null)=>({'us-gaap:consolidated':'美国会计准则 · 合并口径','us-gaap:parent':'美国会计准则 · 归母口径','us-gaap:common':'美国会计准则 · 普通股股东口径','us-gaap:debt_including_finance_leases':'债务含融资租赁','us-gaap:debt_excluding_finance_leases':'债务不含融资租赁','reported_share_basis_unverified':'来源股本口径尚未核验','adjusted_close':'来源调整收盘价','adjusted_close_common_dates':'共同日期调整收盘价'}[basis??'']??(basis?'公司特定口径（详见溯源）':'口径待确认'))
const reasons:Record<string,string>={
 'Historical backfill of currently available filing versions; not strict point-in-time':'当前披露版本的历史回补，不代表严格历史可用',
 'Multiple reported quarter starts; most-supported actual interval selected':'存在多个单季开始日期，按来源支持最多的实际期间展示',
 'Insufficient adjusted-price calendar coverage':'调整收盘价的日历窗口覆盖不足',
 'Financial period or filing version is later than the market quote':'财务期间或披露版本晚于行情日期，不能组合估值',
 'Nonpositive TTM denominator; conventional valuation multiple unavailable':'TTM 分母为零或负数，不适用常规估值倍数',
 'Compatible TTM metric unavailable':'缺少可比的 TTM 财务指标',
 'No compatible source observation':'暂无可比来源记录','No source observation':'尚无来源记录','Missing compatible calculation input':'缺少可比计算输入','Incompatible input units or accounting basis':'输入单位或会计口径不一致','Nonpositive denominator':'分母为零或负数，不作比率比较','Four contiguous fiscal quarters required':'需要四个连续财季','Missing quarter input':'部分财季输入缺失','Non-additive metric; TTM summation unavailable without verified share basis':'该指标不可相加；股本口径未核验，暂不计算 TTM','Incomplete mutually exclusive debt components; missing borrowing/lease coverage is unknown':'债务构成不完整，缺失借款或租赁金额未知','Comparable prior fiscal quarter unavailable':'缺少可比前期财季','Prior quarter is not contiguous':'前一财季不连续','Prior-year fiscal period is not comparable':'去年同期财季不可比','EPS, weighted shares and instant balances cannot be differenced':'每股收益、加权股数及期末余额不可累计差分','Missing preceding cumulative boundary observation':'缺少上期累计边界记录','Incompatible preceding cumulative unit/basis':'上期累计单位或口径不一致','Unresolved restatement across cumulative filings':'累计申报之间的重述尚未对齐','Missing compatible preceding cumulative quarter':'缺少可比上期累计财季','Conflicting facts within the same latest filing date':'最新同日申报存在冲突值','Conflicting overlapping taxonomy aliases or units':'重叠标签或单位存在冲突','Incompatible quarter currency or basis':'财季币种或口径不一致','Conflicting restatement inputs across TTM quarters':'TTM 财季之间存在重述冲突','Insufficient calendar-window price coverage':'价格日历窗口覆盖不足','Interior daily price coverage is incomplete':'区间内部日线覆盖不完整，无法计算回撤','Insufficient common-date calendar coverage':'与基准共同日期覆盖不足','Exact target period actual unavailable':'目标期间没有可比实际值'
}
export function missingReason(reason?:string|null){
 if(!reason)return '尚未提供'
 if(reasons[reason])return reasons[reason]
 if(/market cap|market capitalization|share.class|compatible quote/i.test(reason))return '市值、币种或股权类别口径尚未核验，暂不计算估值'
 if(/common.*earnings|common.shareholder|TTM.*positive|positive.*TTM/i.test(reason))return '缺少正且可比的普通股股东 TTM 利润'
 if(/Direct quarter.*cumulative|direct quarter conflicts/i.test(reason))return '直接单季与累计披露存在冲突，相关 TTM 不可用'
 if(/Insufficient|coverage/i.test(reason))return '来源覆盖不足，请核对实际期间与来源'
 if(/basis|unit|comparable/i.test(reason))return '期间、单位或会计口径不可比，请核对原始记录'
 if(/[\u3400-\u9fff]/.test(reason))return reason
 return '该数据暂不可用，具体原因见溯源原文'
}
export const statusName=(s:string)=>({ready:'已更新',partial:'覆盖不全',failed:'来源失败',empty:'本次无记录',never_collected:'尚未采集',unavailable_at_cutoff:'截止时尚不可用',skipped:'本次跳过'}[s]??'状态待核对')
export const datasetName=(s:string)=>({financials:'标准财务',market:'行情与基准',filings:'本地财报原文',profile:'证券资料',bars:'日线',factors:'复权因子',valuation:'估值',announcements:'公告索引',disclosure:'财报预约',unlocks:'解禁'}[s]??s)
