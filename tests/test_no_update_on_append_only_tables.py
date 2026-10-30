"""Static guard (v2.9 Review Focus 3): the evidence tables are append-only, no `UPDATE` / `DELETE` against them.

`trade_plans`, `agent_plan_versions`, `plan_reviews`, `signal_decisions`, `chain_retriggers`, `holding_status`,
`plan_notes` and `trades` get rows added and never changed; `trades` has one status write (`voided_at` /
`void_reason`, via `repository.mark_trade_voided`). Scans every SQL string literal of the production code (an
`ON CONFLICT … DO UPDATE` upsert counts). Offline: parses the source files, no database."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ('investment_assistant', 'scripts')
TABLES = ('trade_plans', 'agent_plan_versions', 'plan_reviews', 'signal_decisions', 'chain_retriggers',
          'holding_status', 'plan_notes', 'trades')
NAMES = '|'.join(TABLES)
UPDATE = re.compile(rf'\bUPDATE\s+(?:ONLY\s+)?({NAMES})\b(.*)', re.I | re.S)
DELETE = re.compile(rf'\b(?:DELETE\s+FROM|TRUNCATE(?:\s+TABLE)?)\s+(?:ONLY\s+)?({NAMES})\b', re.I)
INSERT = re.compile(rf'\bINSERT\s+INTO\s+({NAMES})\b', re.I)
UPSERT = re.compile(r'\bON\s+CONFLICT\b.*\bDO\s+UPDATE\b', re.I | re.S)
# `trades` may change `voided_at` / `void_reason` and nothing else.
VOID_ONLY = re.compile(r'\bSET\s+voided_at\s*=\s*%s\s*,\s*void_reason\s*=\s*%s\b(?!\s*,)', re.I)


def _sql_strings():
    for directory in SOURCE_DIRS:
        for path in sorted((ROOT / directory).rglob('*.py')):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    yield f'{path.relative_to(ROOT)}:{node.lineno}', node.value


def test_no_update_or_delete_on_append_only_tables():
    offences = []
    for where, text in _sql_strings():
        if DELETE.search(text):
            offences.append(f'{where}: DELETE/TRUNCATE')
        for match in UPDATE.finditer(text):
            table, rest = match.group(1).lower(), match.group(2)
            if table == 'trades' and VOID_ONLY.search(rest[:200]):
                continue                              # the one status write: mark_trade_voided
            offences.append(f'{where}: UPDATE {table}')
        if UPSERT.search(text) and INSERT.search(text):
            offences.append(f'{where}: INSERT ... DO UPDATE')
    assert not offences, f'append-only tables must not be changed: {offences}'


def test_scanner_recognises_the_patterns():
    """The scan is not vacuous: each pattern fires on a sample, and the void write is the lone exception."""
    assert UPDATE.search('UPDATE trade_plans SET stop = 1')
    assert UPDATE.search('update plan_notes set body = %s')
    assert DELETE.search('DELETE FROM holding_status WHERE 1=1')
    assert DELETE.search('TRUNCATE chain_retriggers')
    assert INSERT.search('INSERT INTO plan_reviews (a) VALUES (1)') and UPSERT.search('ON CONFLICT (id) DO UPDATE SET a = 1')
    void = UPDATE.search('UPDATE trades SET voided_at = %s, void_reason = %s WHERE id = %s')
    assert void and VOID_ONLY.search(void.group(2))
    sneaky = UPDATE.search('UPDATE trades SET voided_at = %s, void_reason = %s, quantity = 5 WHERE id = %s')
    assert sneaky and not VOID_ONLY.search(sneaky.group(2))
    # the sources really contain SQL strings to scan
    assert any(re.search(r'\bINSERT\s+INTO\s+trades\b', text, re.I) for _, text in _sql_strings())
