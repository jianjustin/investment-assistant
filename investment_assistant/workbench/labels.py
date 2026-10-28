"""Chinese names for the ten signal rules and the three candidate actions (v2.6 spec D27).

Backend single source for the run overview, "what to watch today" and the K-line
annotations; the frontend `RULE_LABELS` mirrors RULE_TEXT (a cross-language test pins it).
Imports nothing from the other workbench modules."""

RULE_TEXT: dict[str, str] = {
    'trend_reclaim': '趋势回踩修复',
    'volume_breakout': '放量突破',
    'earnings_gap_up': '财报跳空向上',
    'trend_break': '跌破 MA50',
    'earnings_gap_down': '财报跳空向下',
    'position_drawdown': '持仓回撤',
    'new_filing': '新财报',
    'abnormal_move': '异常波动',
    'plan_stop': '计划止损',
    'plan_target': '计划目标',
}

# Short form for chart markers: at most four characters each.
RULE_SHORT: dict[str, str] = {
    'trend_reclaim': '回踩',
    'volume_breakout': '突破',
    'earnings_gap_up': '跳空涨',
    'trend_break': '破位',
    'earnings_gap_down': '跳空跌',
    'position_drawdown': '回撤',
    'new_filing': '财报',
    'abnormal_move': '异动',
    'plan_stop': '止损',
    'plan_target': '目标',
}

ACTION_TEXT: dict[str, str] = {'buy': '买入', 'sell': '卖出', 'watch': '观察'}
