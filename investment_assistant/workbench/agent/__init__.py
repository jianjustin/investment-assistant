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
    # agent-2 / daily review (v2.5 spec §4.4)
    'thesis_count': '论点数量不符',
    'invalid_condition': '失效或复查条件无效',
    'changes_mismatch': '变化说明与实际差异不符',
    'no_change': '修订与上版没有差异',
    'review_malformed': '复查输出格式无效',
    'migration_026_missing': '迁移 026 未执行',
    'review_in_progress': '正在复查',
}
