import json
import subprocess
from pathlib import Path

from investment_assistant.workbench import briefs, codex_client

OUT = {'summary': 's', 'support': [], 'contra': [], 'conflicts': []}


def fake_runner(*, returncode=0, output=OUT, stderr='', raise_exc=None):
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if raise_exc:
            raise raise_exc
        out_path = Path(cmd[cmd.index('-o') + 1])
        schema = json.loads(Path(cmd[cmd.index('--output-schema') + 1]).read_text())
        calls.append(('schema', schema))
        if output is not None:
            out_path.write_text(output if isinstance(output, str) else json.dumps(output))
        return subprocess.CompletedProcess(cmd, returncode, stdout='', stderr=stderr)
    run.calls = calls
    return run


def test_runs_codex_read_only_and_ephemeral_with_schema():
    runner = fake_runner()
    result, status = codex_client.request(system_prompt='SYS', user_payload={'ticker': 'NVDA'}, model=None, runner=runner)
    assert result == OUT and status['ok'] is True
    cmd, kwargs = runner.calls[0]
    assert cmd[:2] == ['codex', 'exec']
    assert {'--ephemeral', '--skip-git-repo-check', '--ignore-user-config', '--ignore-rules'} <= set(cmd)
    assert cmd[cmd.index('--sandbox') + 1] == 'read-only'
    assert cmd[-1] == '-' and 'SYS' in kwargs['input'] and '"ticker": "NVDA"' in kwargs['input']
    assert kwargs['timeout'] == codex_client.TIMEOUT_SECONDS
    schema = runner.calls[1][1]
    assert schema['required'] == ['summary', 'support', 'contra', 'conflicts'] and schema['additionalProperties'] is False


def test_model_override_is_passed_only_when_set():
    runner = fake_runner()
    codex_client.request(system_prompt='S', user_payload={}, model='gpt-x', runner=runner)
    assert runner.calls[0][0][runner.calls[0][0].index('-m') + 1] == 'gpt-x'


def test_failures_return_none_with_reason():
    assert codex_client.request(system_prompt='S', user_payload={}, model=None,
                                runner=fake_runner(returncode=1, stderr='not logged in'))[1]['error'].startswith('codex exit 1')
    assert 'timed out' in codex_client.request(system_prompt='S', user_payload={}, model=None, runner=fake_runner(
        raise_exc=subprocess.TimeoutExpired('codex', 1)))[1]['error']
    assert 'not found' in codex_client.request(system_prompt='S', user_payload={}, model=None, runner=fake_runner(
        raise_exc=FileNotFoundError()))[1]['error']
    assert codex_client.request(system_prompt='S', user_payload={}, model=None, runner=fake_runner(output='not json'))[0] is None
    assert codex_client.request(system_prompt='S', user_payload={}, model=None, runner=fake_runner(output=None))[0] is None


def test_provider_selection(monkeypatch):
    monkeypatch.setenv('WORKBENCH_LLM_PROVIDER', 'codex')
    client, label = briefs.provider_client()
    assert client is codex_client.request and label == 'codex-cli (ChatGPT plan)'
    monkeypatch.setenv('WORKBENCH_LLM_PROVIDER', 'deepseek')
    assert briefs.provider_client()[1] == 'deepseek-chat'
    monkeypatch.setenv('WORKBENCH_LLM_PROVIDER', 'off')
    client, label = briefs.provider_client()
    assert client(system_prompt='', user_payload={}, model=None) == (None, {'ok': False, 'error': 'LLM 已关闭（WORKBENCH_LLM_PROVIDER=off）'})


def test_tests_never_reach_a_real_model_by_default():
    # conftest pins the provider off; a default-client brief must fall back without a subprocess.
    unit = {'ticker': 'NVDA', 'signal_date': __import__('datetime').date(2026, 10, 22), 'proposed_action': 'watch',
            'labels': [], 'candidate_ids': []}
    brief = briefs.generate(unit, [], [], [], cutoff_at=__import__('datetime').datetime(2026, 10, 22, tzinfo=__import__('datetime').UTC))
    assert brief['status'] == 'fallback' and brief['model'] == 'none'


def test_transient_failure_is_retried_once():
    state = {'n': 0}
    ok = fake_runner()
    bad = fake_runner(returncode=1, stderr='prompt echo\nERROR: stream disconnected before completion\nmore echo')

    def flaky(cmd, **kwargs):
        state['n'] += 1
        return (bad if state['n'] == 1 else ok)(cmd, **kwargs)
    result, status = codex_client.request(system_prompt='S', user_payload={}, model=None, runner=flaky)
    assert result == OUT and status['attempts'] == 2


def test_error_message_prefers_real_error_lines_over_prompt_echo():
    stderr = 'user\n你是美股波段研究助手\n{"ticker": "NVDA"}\nERROR: stream disconnected before completion\ncodex\n'
    _, status = codex_client.request(system_prompt='S', user_payload={}, model=None,
                                     runner=fake_runner(returncode=1, stderr=stderr))
    assert 'stream disconnected' in status['error'] and 'NVDA' not in status['error']
    assert status['attempts'] == 2


def test_timeouts_are_not_retried():
    calls = []

    def slow(cmd, **kwargs):
        calls.append(1)
        raise subprocess.TimeoutExpired('codex', 1)
    codex_client.request(system_prompt='S', user_payload={}, model=None, runner=slow)
    assert len(calls) == 1
