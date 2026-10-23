"""Brief client backed by the local Codex CLI, i.e. the user's ChatGPT plan login.

Runs `codex exec` non-interactively in an empty temp directory with a read-only
sandbox, no persisted session and no user config/rules, and constrains the final
message with a JSON schema. Any failure returns (None, status) so the caller
falls back to a rule-only brief.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

TIMEOUT_SECONDS = 240
MODEL_LABEL = 'codex-cli (ChatGPT plan)'

_ITEM = {'type': 'object', 'additionalProperties': False, 'required': ['text', 'refs'],
         'properties': {'text': {'type': 'string'}, 'refs': {'type': 'array', 'items': {'type': 'string'}}}}
SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['summary', 'support', 'contra', 'conflicts'],
          'properties': {'summary': {'type': 'string'}, 'support': {'type': 'array', 'items': _ITEM},
                         'contra': {'type': 'array', 'items': _ITEM}, 'conflicts': {'type': 'array', 'items': _ITEM}}}

_GUARD = '只根据下面给出的输入作答；不要运行任何命令、不要读写文件、不要联网检索。输入 JSON：'


def request(*, system_prompt: str, user_payload: dict[str, Any], model: str | None,
            runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> tuple[dict | None, dict]:
    with tempfile.TemporaryDirectory(prefix='workbench-brief-') as tmp:
        schema_path, out_path = Path(tmp, 'schema.json'), Path(tmp, 'out.json')
        schema_path.write_text(json.dumps(SCHEMA))
        workdir = Path(tmp, 'work')
        workdir.mkdir()
        cmd = [os.environ.get('WORKBENCH_CODEX_BIN', 'codex'), 'exec', '--sandbox', 'read-only', '--ephemeral',
               '--skip-git-repo-check', '--ignore-user-config', '--ignore-rules', '--color', 'never',
               '-C', str(workdir), '--output-schema', str(schema_path), '-o', str(out_path)]
        model = model or os.environ.get('WORKBENCH_CODEX_MODEL')
        if model:
            cmd += ['-m', model]
        cmd.append('-')
        prompt = f'{system_prompt}\n\n{_GUARD}\n{json.dumps(user_payload, ensure_ascii=False, default=str)}'
        try:
            proc = runner(cmd, input=prompt, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
        except FileNotFoundError:
            return None, {'ok': False, 'error': 'codex CLI not found'}
        except subprocess.TimeoutExpired:
            return None, {'ok': False, 'error': f'codex timed out after {TIMEOUT_SECONDS}s'}
        if proc.returncode != 0:
            tail = (proc.stderr or '').strip().splitlines()[-3:]
            return None, {'ok': False, 'error': f"codex exit {proc.returncode}: {' | '.join(tail)[:300]}"}
        try:
            result = json.loads(out_path.read_text())
        except (OSError, ValueError):
            return None, {'ok': False, 'error': 'codex returned no valid JSON'}
    if not isinstance(result, dict):
        return None, {'ok': False, 'error': 'codex returned no JSON object'}
    return result, {'ok': True, 'error': None}
