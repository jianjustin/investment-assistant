"""Agent track: shared status and reason constants (P3 design §6.4).

REASON_TEXT is the single backend copy of the Chinese reason labels; the
frontend keeps its own in web/src/lib/workbench.ts and the two must match.
"""
STATUSES = ('ok', 'pass', 'rejected', 'error', 'skipped')

REASON_TEXT = {
    'disabled': '已关闭',
    'not_configured': '未配置',
    'quota_exhausted': '额度用尽',
    'token_budget': '超出 token 上限',
    'stage_budget': '超出时限',
    'max_attempts': '已达重试上限',
    'malformed': '输出格式无效',
    'invalid_citation': '引用无效已作废',
    'level_check': '价位校验未通过',
    'tool_rounds_exceeded': '工具调用超限',
    'model_error': '模型调用失败',
    'checkpoint_unavailable': '状态库未就绪',
}
