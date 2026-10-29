"""后端任务说明注册表：定时任务在页面上的 `?` 文案统一从这里下发。"""

from __future__ import annotations

from typing import Any

JOB_INFO: dict[str, dict[str, Any]] = {
    "workbench": {
        "title": "每日批处理",
        "goal": "每个交易日收盘后生成当日交易计划并推送。",
        "details": [
            "采集：日线、资讯、财报日、SEC 列表、行业 ETF、FRED。",
            "纳指 100 筛选（screen-1）：范围文件加载、日线与财报日采集、过滤排序，成员自动进扩展池。",
            "计算市场环境（广度样本 = 纳指 100 范围 ∪ 手动观察池）。",
            "跑规则 v1，生成观察候选。",
            "生成规则计划（plan-1）。",
            "Agent 轨道：对候选做提议与反方。",
            "每日复查：对有效 Agent 计划复查，维持、修订或作废。",
            "复盘卡（retro）：检测已结束的计划与平仓，冻结复盘事实并起草复盘卡，等你审定。",
            "推送 Discord（每日计划）。",
            "纽约休市日跳过，只推一行「纽约休市，未运行」。",
        ],
        "manual_note": "手动运行针对最近一个已收盘交易日（纽约 17:00 后算当天收盘），不推送。",
    },
    "workbench_review": {
        "title": "复盘",
        "goal": "跟踪计划结果，生成周 / 月复盘并推送。",
        "details": [
            "影子跟踪：规则计划与 Agent 计划各按自己的价位跟踪。",
            "三方对比：规则、Agent、实际成交。",
            "纪律指标。",
            "周度复盘。",
            "月度收益。",
            "周 / 月复盘完成后推送。",
        ],
        "manual_note": "手动运行不推送。",
    },
    "filings": {
        "title": "SEC 监控",
        "goal": "扫描观察名单内公司的 SEC 申报，归档原文、提取正文事实，经 Discord Bot 直发通知并做历史去重。",
        "details": [
            "两种模式：默认下载器按配置下载申报；开启 sec_monitor 后用监控模式（扫描、归档、提取、直发）。",
            "收集范围：10-Q、10-K，以及主文含 Item 2.02 或索引含 EX-99.1 的 8-K。",
            "正文提取：营收、毛利、营业利润、利润率和摊薄 EPS，带期间、单位与原文位置。",
            "通知以 Bot 身份直发 sec_monitor.discord_channel_id 指定的频道。",
            "去重读旧日志与来源库文件名里的 accession，已通知过的不重发。",
        ],
        "manual_note": "手动「按日期运行」可回补指定日期或日期范围（上限 92 天）的申报。",
    },
}


def describe(name: str) -> dict[str, Any] | None:
    return JOB_INFO.get(name)
