#!/usr/bin/env python3
"""v2.8 开工前核查：Sign in with ChatGPT 登录 → GET /v1/models → Responses 调用 → 打印脱敏摘要。

只由你本人在运行服务的这台 Mac 上执行一次（spec docs/specs/2026-10-29-v2.8-daily-workflow-design.md §17）。
只用 .venv 里已装的 openai、langchain-openai（及其依赖 langchain-core、httpx）与标准库；不 import 项目代码、
不连数据库、不改任何配置。

- 令牌只写到 .local/siwc-precheck/tokens.json（权限 0600），结束时默认撤销并删除；任何输出都不含令牌。
- 每一步失败都打印可读原因并继续下一步；最后打印一段「核查摘要」，整段贴进 spec §17 末尾。
- 运行方式见 scripts/README.md。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import http.server
import json
import os
import platform
import re
import secrets
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

SCRIPT_VERSION = 'siwc-precheck-1'
ISSUER = 'https://auth.openai.com'
RESOURCE = 'https://api.openai.com/v1'
SCOPES = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'
SHARING_SCOPE = 'chatgpt.tokens.use.direct'
CALLBACK_PATH = '/auth/callback'
DYNAMIC_CLIENT = 'dynamic_agent_client'
APP_NAME = 'investment-assistant'
LOGIN_WAIT_S = 300
HTTP_TIMEOUT_S = 30
MODEL_TIMEOUT_S = 180

REPO = Path(__file__).resolve().parents[1]
STATE_DIR = REPO / '.local' / 'siwc-precheck'
TOKENS_FILE = STATE_DIR / 'tokens.json'
CLIENT_FILE = STATE_DIR / 'client.json'      # 动态注册得到的 client_id 与 host_id（不是令牌，但同样只放本机）
SUMMARY_FILE = STATE_DIR / 'summary.md'

# 官方限制页列出的被禁字段（spec §8.5 FORBIDDEN_FIELDS）之外，还要看 langchain-openai 会不会夹带的几个。
PROBES: list[tuple[str, dict[str, Any]]] = [
    ('temperature', {'temperature': 0.2}),
    ('max_output_tokens', {'max_output_tokens': 256}),
    ('user', {'user': 'precheck'}),
    ('top_p', {'top_p': 1}),
    ('metadata', {'metadata': {'k': 'v'}}),
    ('truncation', {'truncation': 'auto'}),
    ('parallel_tool_calls', {'parallel_tool_calls': False}),
    ('include', {'include': ['reasoning.encrypted_content']}),
    ('previous_response_id', {'previous_response_id': 'resp_precheck_nonexistent'}),
    ('store_true', {'__store__': True}),
    ('stream_false', {'__stream__': False}),
    ('system_role_input', {'__system_input__': True}),
]

TOOL_FUNCTION = {
    'type': 'function',
    'name': 'get_price',
    'description': '返回一只股票的最新收盘价（核查用的假数据）。',
    'parameters': {
        'type': 'object',
        'properties': {'ticker': {'type': 'string', 'description': '股票代码，例如 NVDA'}},
        'required': ['ticker'],
        'additionalProperties': False,
    },
}
TOOL_PROMPT = '请调用 get_price 工具查询 NVDA 的最新收盘价，然后用一句中文回答价格是多少。'
FAKE_PRICE = {'ticker': 'NVDA', 'close': 123.45, 'note': 'precheck fake data'}
INSTRUCTIONS = '你是核查脚本的测试助手。回答要短。'

# ---------------------------------------------------------------------------------------------- 脱敏输出

_SECRETS: set[str] = set()
_JWT = re.compile(r'eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}')
_BEARER = re.compile(r'(?i)bearer\s+[A-Za-z0-9._~+/=-]+')
_SAFE_CODE = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.:\[\]-]{0,99}$')


def remember_secret(value: Any) -> None:
    if isinstance(value, str) and len(value) >= 8:
        _SECRETS.add(value)


def redact(text: Any) -> str:
    out = str(text)
    for secret in sorted(_SECRETS, key=len, reverse=True):
        out = out.replace(secret, '<redacted>')
    out = _JWT.sub('<redacted-jwt>', out)
    return _BEARER.sub('Bearer <redacted>', out)


def say(*parts: Any) -> None:
    print(redact(' '.join(str(p) for p in parts)), flush=True)


def safe_code(value: Any) -> str | None:
    return value if isinstance(value, str) and _SAFE_CODE.match(value) else None


def mask_email(email: Any) -> str:
    if not isinstance(email, str) or '@' not in email:
        return '（无）'
    name, domain = email.split('@', 1)
    return f'{name[:1]}***@{domain}'


def mask_id(value: Any) -> str:
    return f'{str(value)[:4]}…（{len(str(value))} 字符）' if value else '（无）'


def short_error(exc: BaseException) -> str:
    """异常的一行可读原因；不带请求体、不带令牌。"""
    status = getattr(exc, 'status_code', None)
    body = getattr(exc, 'body', None)
    code = param = None
    if isinstance(body, dict):
        detail = body.get('error') if isinstance(body.get('error'), dict) else body
        if isinstance(detail, dict):
            code = safe_code(detail.get('code')) or safe_code(detail.get('type'))
            param = safe_code(detail.get('param'))
    parts = [type(exc).__name__]
    if status is not None:
        parts.append(f'HTTP {status}')
    if code:
        parts.append(f'code={code}')
    if param:
        parts.append(f'param={param}')
    if len(parts) == 1:
        parts.append(redact(exc)[:200])
    return ' · '.join(parts)


# ---------------------------------------------------------------------------------------------- 结果记录

class Report:
    """每个核查项（C1–C8，对应 spec §17 的表）收集若干行结论。"""

    TITLES = {
        'C1': '发现文档与登录',
        'C2': '可见模型清单',
        'C3': '原生 openai SDK 最小调用',
        'C4': '被拒字段',
        'C5': '工具形状',
        'C6': 'langchain-openai 路径 A',
        'C7': '额度用尽的错误文本',
        'C8': '选定路径（建议）',
    }

    def __init__(self) -> None:
        self.items: dict[str, list[str]] = {key: [] for key in self.TITLES}
        self.facts: dict[str, Any] = {}

    def add(self, key: str, line: str) -> None:
        self.items[key].append(redact(line))
        say(f'  [{key}] {line}')

    def markdown(self) -> str:
        lines = [f'#### 核查摘要（{datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")}，`{SCRIPT_VERSION}`）', '',
                 f'- 环境：Python {platform.python_version()} · openai {self.facts.get("openai_version", "?")} · '
                 f'langchain-openai {self.facts.get("langchain_openai_version", "?")} · '
                 f'代理变量 {"有" if self.facts.get("proxy_env") else "无"}', '']
        for key, title in self.TITLES.items():
            lines.append(f'- **{key} {title}**')
            for item in self.items[key] or ['（没有结果）']:
                lines.append(f'  - {item}')
        return redact('\n'.join(lines))


def step(title: str) -> None:
    say('')
    say(f'== {title} ==')


def guarded(report: Report, key: str, title: str, fn: Callable[[], Any]) -> Any:
    """跑一步；任何异常都转成一行可读原因记进报告，返回 None，脚本继续。"""
    step(title)
    try:
        return fn()
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001 - 核查脚本：每步失败都记录后继续
        report.add(key, f'失败：{short_error(exc)}')
        if os.environ.get('SIWC_PRECHECK_DEBUG'):
            say(redact(traceback.format_exc()))
        return None


# ---------------------------------------------------------------------------------------------- HTTP（标准库）

def http_json(method: str, url: str, *, form: dict[str, str] | None = None,
              headers: dict[str, str] | None = None) -> tuple[int, Any]:
    """一次 HTTP 请求（读环境里的代理变量）；返回 (状态码, JSON 或 None)。网络错误抛出。"""
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header('Accept', 'application/json')
    if form is not None:
        request.add_header('Content-Type', 'application/x-www-form-urlencoded')
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    try:
        return status, json.loads(raw.decode('utf-8')) if raw else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return status, None


def oauth_error(body: Any) -> str:
    if isinstance(body, dict):
        for key in ('error', 'code'):
            value = body.get(key)
            if isinstance(value, dict):
                value = value.get('code') or value.get('type')
            if safe_code(value):
                return value
    return 'unknown_error'


# ---------------------------------------------------------------------------------------------- 本机文件

def write_private(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        os.fchmod(handle.fileno(), 0o600)
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def jwt_claims(token: str) -> dict[str, Any]:
    """只解码 ID token 的声明（不验签名，同 spec D28；这里只用来读 iss / aud / exp / nonce / email）。"""
    payload = token.split('.')[1]
    payload += '=' * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload.encode()).decode('utf-8'))


# ---------------------------------------------------------------------------------------------- C1 发现与登录

def discover(report: Report) -> dict[str, Any]:
    status, body = http_json('GET', f'{ISSUER}/.well-known/openid-configuration')
    if status != 200 or not isinstance(body, dict):
        raise RuntimeError(f'发现文档返回 HTTP {status}')
    if body.get('issuer') != ISSUER:
        raise RuntimeError('发现文档的 issuer 不是 https://auth.openai.com')
    endpoints = {key: body.get(key) for key in ('authorization_endpoint', 'token_endpoint',
                                                 'revocation_endpoint', 'jwks_uri')}
    for key, value in endpoints.items():
        if value is not None and urllib.parse.urlsplit(value).netloc != urllib.parse.urlsplit(ISSUER).netloc:
            raise RuntimeError(f'{key} 不在 {ISSUER} 下')
    report.add('C1', '发现文档：issuer 正确；端点 ' + ', '.join(
        f'{k}={"有" if v else "无"}' for k, v in endpoints.items()))
    return body


class _Callback:
    def __init__(self, state: str) -> None:
        self.state = state
        self.result: dict[str, Any] | None = None
        self.event = threading.Event()
        self.port = 0


def _handler_for(box: _Callback):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:   # 不打印访问日志（URL 里有一次性 code）
            return

        def _reply(self, code: int, text: str) -> None:
            body = (f'<!doctype html><meta charset="utf-8"><title>{APP_NAME}</title>'
                    f'<p style="font:16px system-ui;margin:20vh auto;max-width:30rem">{text}</p>').encode()
            self.send_response(code)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - http.server 的方法名
            parsed = urllib.parse.urlsplit(self.path)
            if self.headers.get('Host') != f'127.0.0.1:{box.port}' or parsed.path != CALLBACK_PATH or box.event.is_set():
                self._reply(404, 'Not found')
                return
            query = urllib.parse.parse_qs(parsed.query)
            states = query.get('state', [])
            if len(states) != 1 or not hmac.compare_digest(states[0].encode(), box.state.encode()):
                self._reply(400, '登录状态不匹配：请回到发起登录的那个浏览器标签页。')
                return
            box.result = {key: values for key, values in query.items()}
            box.event.set()
            self._reply(200, '核查脚本已收到登录结果，可以关闭这个标签页，回到终端。')
    return Handler


def login(report: Report, disc: dict[str, Any], *, port: int, open_browser: bool) -> dict[str, Any]:
    saved = read_json(CLIENT_FILE) or {}
    host_id = saved.get('host_id') or f'urn:uuid:{uuid.uuid4()}'
    client_id = saved.get('client_id')
    state, nonce, verifier = b64url(secrets.token_bytes(32)), b64url(secrets.token_bytes(32)), b64url(secrets.token_bytes(32))
    challenge = b64url(hashlib.sha256(verifier.encode()).digest())

    box = _Callback(state)
    server = http.server.HTTPServer(('127.0.0.1', port), _handler_for(box))
    box.port = server.server_address[1]
    redirect_uri = f'http://127.0.0.1:{box.port}{CALLBACK_PATH}'
    thread = threading.Thread(target=server.serve_forever, name='siwc-callback', daemon=True)
    thread.start()
    try:
        params = {
            'client_id': client_id or DYNAMIC_CLIENT, 'response_type': 'code', 'redirect_uri': redirect_uri,
            'scope': SCOPES, 'resource': RESOURCE, 'state': state, 'nonce': nonce,
            'code_challenge_method': 'S256', 'code_challenge': challenge, 'ext_agent_host_id': host_id,
        }
        if not client_id:
            params['agent_name_hint'] = APP_NAME
        url = f"{disc['authorization_endpoint']}?{urllib.parse.urlencode(params)}"
        say(f'  回环监听：127.0.0.1:{box.port}{CALLBACK_PATH}（{LOGIN_WAIT_S // 60} 分钟内有效）')
        say(f'  {"首次登录：动态注册（dynamic_agent_client）" if not client_id else "复用已保存的 client_id"}')
        opened = open_browser and webbrowser.open(url)
        if not opened:
            say('  请在这台 Mac 的浏览器里打开下面的地址完成登录（地址里没有任何令牌）：')
            say(f'  {url}')
        else:
            say('  已在默认浏览器里打开授权页，请在浏览器里完成登录。')
        if not box.event.wait(LOGIN_WAIT_S):
            raise RuntimeError(f'{LOGIN_WAIT_S} 秒内没有收到浏览器回调')
    finally:
        server.shutdown()
        server.server_close()

    query = box.result or {}
    if 'error' in query:
        raise RuntimeError(f"授权页返回错误：{safe_code(query['error'][0]) or 'unknown'}")
    codes = query.get('code', [])
    if len(codes) != 1:
        raise RuntimeError('回调里没有唯一的 code')
    code = codes[0]
    remember_secret(code)
    returned = query.get('client_id', [])
    issued = returned[0] if len(returned) == 1 else client_id
    if not issued or issued == DYNAMIC_CLIENT or not re.match(r'^[A-Za-z0-9_-]{1,200}$', issued):
        raise RuntimeError('回调里没有有效的 client_id（registration_incomplete）')
    if client_id and returned and returned[0] != client_id:
        raise RuntimeError('回调里的 client_id 与已保存的不同（registration_incomplete）')
    report.add('C1', f'回调：带回 client_id={"是" if returned else "否（沿用已保存的）"}，client_id {mask_id(issued)}')
    write_private(CLIENT_FILE, {'client_id': issued, 'host_id': host_id, 'saved_at': datetime.now(UTC).isoformat()})

    status, body = http_json('POST', disc['token_endpoint'], form={
        'grant_type': 'authorization_code', 'client_id': issued, 'code': code,
        'code_verifier': verifier, 'redirect_uri': redirect_uri, 'resource': RESOURCE,
    })
    if status != 200 or not isinstance(body, dict):
        raise RuntimeError(f'换令牌失败：HTTP {status} · {oauth_error(body)}')
    tokens = _check_token_response(report, body, issued, nonce=nonce)
    tokens.update(client_id=issued, host_id=host_id)
    write_private(TOKENS_FILE, tokens)
    say(f'  令牌已写入 {TOKENS_FILE.relative_to(REPO)}（权限 0600）')
    return tokens


def _check_token_response(report: Report, body: dict[str, Any], client_id: str, *,
                          nonce: str | None = None, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    for key in ('access_token', 'refresh_token', 'id_token'):
        remember_secret(body.get(key))
    scopes = (body.get('scope') or (previous or {}).get('scope') or '').split()
    missing = [key for key in ('access_token', 'refresh_token') if not body.get(key)]
    report.add('C1', f"令牌响应键：{', '.join(sorted(body))}；token_type={body.get('token_type')}；"
                     f"expires_in={body.get('expires_in')}；earliest_refresh_at={'有' if 'earliest_refresh_at' in body else '无'}；"
                     f"缺少：{', '.join(missing) or '无'}")
    report.add('C1', f"scope：{' '.join(scopes) or '（响应里没有）'}；含 {SHARING_SCOPE}：{'是' if SHARING_SCOPE in scopes else '否'}")
    email = (previous or {}).get('email')
    subject = (previous or {}).get('subject')
    if isinstance(body.get('id_token'), str):
        claims = jwt_claims(body['id_token'])
        checks = {
            'iss': claims.get('iss') == ISSUER,
            'aud': client_id in (claims.get('aud') if isinstance(claims.get('aud'), list) else [claims.get('aud')]),
            'exp': isinstance(claims.get('exp'), (int, float)) and claims['exp'] > time.time(),
            'nonce': nonce is None or claims.get('nonce') == nonce,
            'sub': bool(claims.get('sub')) and (subject is None or claims.get('sub') == subject),
        }
        email = claims.get('email', email)
        subject = claims.get('sub', subject)
        report.add('C1', 'ID token 声明：' + ', '.join(f'{k}={"通过" if v else "不通过"}' for k, v in checks.items())
                   + f'；账号 {mask_email(email)}')
    else:
        report.add('C1', 'ID token：响应里没有')
    now = time.time()
    return {
        'access_token': body.get('access_token'), 'refresh_token': body.get('refresh_token'),
        'access_expires_at': now + float(body.get('expires_in') or 0),
        'earliest_refresh_at': body.get('earliest_refresh_at'),
        'scope': ' '.join(scopes), 'email': email, 'subject': subject,
        'saved_at': datetime.now(UTC).isoformat(),
    }


def reuse_tokens(report: Report) -> dict[str, Any] | None:
    tokens = read_json(TOKENS_FILE)
    if not tokens or not tokens.get('access_token'):
        return None
    for key in ('access_token', 'refresh_token'):
        remember_secret(tokens.get(key))
    report.add('C1', f'复用上次保存的令牌（{TOKENS_FILE.relative_to(REPO)}），账号 {mask_email(tokens.get("email"))}')
    return tokens


def refresh(report: Report, disc: dict[str, Any], tokens: dict[str, Any]) -> dict[str, Any]:
    status, body = http_json('POST', disc['token_endpoint'], form={
        'grant_type': 'refresh_token', 'client_id': tokens['client_id'],
        'refresh_token': tokens['refresh_token'], 'resource': RESOURCE,
    })
    if status != 200 or not isinstance(body, dict):
        raise RuntimeError(f'刷新失败：HTTP {status} · {oauth_error(body)}')
    rotated = body.get('refresh_token') not in (None, tokens['refresh_token'])
    fresh = _check_token_response(report, body, tokens['client_id'], previous=tokens)
    fresh.update(client_id=tokens['client_id'], host_id=tokens['host_id'])
    if not fresh.get('refresh_token'):
        fresh['refresh_token'] = tokens['refresh_token']
    write_private(TOKENS_FILE, fresh)
    report.add('C1', f'刷新一次：成功；refresh token {"已轮换" if rotated else "未轮换（沿用旧值）"}')
    return fresh


def revoke(report: Report, disc: dict[str, Any] | None, tokens: dict[str, Any]) -> None:
    endpoint = (disc or {}).get('revocation_endpoint')
    if not endpoint or not tokens.get('refresh_token'):
        report.add('C1', '撤销：没有撤销端点或 refresh token，未撤销（可到 ChatGPT 设置里断开这个应用）')
        return
    status, body = http_json('POST', endpoint, form={
        'token': tokens['refresh_token'], 'token_type_hint': 'refresh_token', 'client_id': tokens['client_id'],
    })
    report.add('C1', f'撤销 refresh token：HTTP {status}' + ('' if status == 200 else f' · {oauth_error(body)}'))


# ---------------------------------------------------------------------------------------------- C2 模型清单

def list_models(report: Report, tokens: dict[str, Any]) -> list[dict[str, Any]]:
    status, body = http_json('GET', f'{RESOURCE}/models', headers={'Authorization': f"Bearer {tokens['access_token']}"})
    if status != 200 or not isinstance(body, dict):
        raise RuntimeError(f'GET /v1/models 返回 HTTP {status} · {oauth_error(body)}')
    report.add('C2', f"顶层键：{', '.join(sorted(body))}")
    rows = body.get('models') if isinstance(body.get('models'), list) else body.get('data')
    if not isinstance(rows, list):
        raise RuntimeError('响应里没有 models 或 data 数组')
    keys = sorted({k for row in rows if isinstance(row, dict) for k in row})
    report.add('C2', f'条目数 {len(rows)}；条目键：{", ".join(keys)}')
    visible = [row for row in rows if isinstance(row, dict) and row.get('visibility') == 'list']
    others = sorted({str(row.get('visibility')) for row in rows if isinstance(row, dict)} - {'list'})
    report.add('C2', f'visibility=list 的 {len(visible)} 个（服务器顺序）：' + '；'.join(
        f"{row.get('slug') or row.get('id')}（{row.get('display_name') or '—'}）" for row in visible))
    if others:
        report.add('C2', f"其它 visibility 取值：{', '.join(others)}")
    return visible


# ---------------------------------------------------------------------------------------------- openai SDK

def sdk_client(tokens: dict[str, Any]):
    import openai

    return openai.OpenAI(api_key=tokens['access_token'], base_url=RESOURCE, max_retries=0,
                         timeout=MODEL_TIMEOUT_S, organization=None, project=None)


def consume(stream) -> dict[str, Any]:
    """读完一次流式 Responses：事件类型序列、文本、函数调用、usage、失败码。"""
    out: dict[str, Any] = {'events': [], 'text': '', 'calls': [], 'usage': None, 'completed': False,
                           'failed': None, 'incomplete': False}
    for event in stream:
        kind = getattr(event, 'type', '?')
        if not out['events'] or out['events'][-1] != kind:
            out['events'].append(kind)
        if kind == 'response.output_text.delta':
            out['text'] += getattr(event, 'delta', '') or ''
        elif kind == 'response.output_item.done':
            item = getattr(event, 'item', None)
            if getattr(item, 'type', None) == 'function_call':
                out['calls'].append({'name': getattr(item, 'name', None), 'call_id': getattr(item, 'call_id', None),
                                     'arguments': getattr(item, 'arguments', None),
                                     'namespace': getattr(item, 'namespace', None)})
        elif kind == 'response.completed':
            out['completed'] = True
            usage = getattr(getattr(event, 'response', None), 'usage', None)
            out['usage'] = usage.model_dump() if hasattr(usage, 'model_dump') else usage
            break
        elif kind in ('response.failed', 'error'):
            error = getattr(getattr(event, 'response', None), 'error', None) if kind == 'response.failed' else event
            out['failed'] = safe_code(getattr(error, 'code', None)) or 'unknown'
            break
        elif kind == 'response.incomplete':
            out['incomplete'] = True
            break
    return out


def usage_shape(usage: Any) -> str:
    if not isinstance(usage, dict):
        return '（没有 usage）'

    def walk(value: Any, prefix: str = '') -> list[str]:
        if isinstance(value, dict):
            return [x for k, v in value.items() for x in walk(v, f'{prefix}{k}.')]
        return [f'{prefix[:-1]}={value}']
    return '；'.join(walk(usage))


def sdk_minimal(report: Report, tokens: dict[str, Any], model: str) -> None:
    client = sdk_client(tokens)
    stream = client.responses.create(model=model, instructions=INSTRUCTIONS,
                                     input=[{'role': 'user', 'content': '只回答两个字母：ok'}],
                                     store=False, stream=True)
    out = consume(stream)
    report.add('C3', f"事件序列：{' → '.join(out['events'])}")
    report.add('C3', f"completed={out['completed']}；failed={out['failed']}；文本长度 {len(out['text'])}")
    report.add('C3', f"usage：{usage_shape(out['usage'])}")


def probe_fields(report: Report, tokens: dict[str, Any], model: str) -> None:
    client = sdk_client(tokens)
    for name, extra in PROBES:
        kwargs: dict[str, Any] = {'model': model, 'instructions': INSTRUCTIONS,
                                  'input': [{'role': 'user', 'content': '只回答 ok'}],
                                  'store': extra.get('__store__', False), 'stream': extra.get('__stream__', True)}
        if extra.get('__system_input__'):
            kwargs.pop('instructions')
            kwargs['input'] = [{'role': 'system', 'content': INSTRUCTIONS}, {'role': 'user', 'content': '只回答 ok'}]
        body = {k: v for k, v in extra.items() if not k.startswith('__')}
        if body:
            kwargs['extra_body'] = body
        try:
            result = client.responses.create(**kwargs)
            if kwargs['stream']:
                out = consume(result)
                verdict = ('接受' if out['completed'] else
                           f"流内失败 code={out['failed']}" if out['failed'] else '未完成')
            else:
                verdict = '接受（非流式）'
        except Exception as exc:  # noqa: BLE001 - 逐个探测，记录后继续
            verdict = f'拒绝：{short_error(exc)}'
        report.add('C4', f'{name}：{verdict}')


def _tool_request(shape: str, model: str, extra_input: list | None = None) -> dict[str, Any]:
    user = {'role': 'user', 'content': TOOL_PROMPT}
    kwargs: dict[str, Any] = {'model': model, 'instructions': INSTRUCTIONS, 'store': False, 'stream': True}
    if shape == 'top_level':
        kwargs.update(input=[user, *(extra_input or [])], tools=[TOOL_FUNCTION])
    elif shape == 'namespace':
        kwargs.update(input=[user, *(extra_input or [])], tools=[{
            'type': 'namespace', 'name': 'workbench', 'description': '投研工作台的只读数据工具',
            'tools': [TOOL_FUNCTION]}])
    else:   # additional_tools
        kwargs.update(input=[{'type': 'additional_tools', 'role': 'developer', 'tools': [TOOL_FUNCTION]},
                             user, *(extra_input or [])])
    return kwargs


def tool_shapes(report: Report, tokens: dict[str, Any], model: str) -> str | None:
    client = sdk_client(tokens)
    working: list[str] = []
    for shape in ('top_level', 'namespace', 'additional_tools'):
        try:
            first = consume(client.responses.create(**_tool_request(shape, model)))
            if first['failed'] or not first['completed']:
                report.add('C5', f"{shape}：第一轮未完成（code={first['failed']}）")
                continue
            if not first['calls']:
                report.add('C5', f'{shape}：请求被接受，但模型没有调用工具（文本长度 {len(first["text"])}）')
                continue
            call = first['calls'][0]
            replay: dict[str, Any] = {'type': 'function_call', 'call_id': call['call_id'], 'name': call['name'],
                                      'arguments': call['arguments'] or '{}'}
            if call.get('namespace'):
                replay['namespace'] = call['namespace']
            outputs = [replay, {'type': 'function_call_output', 'call_id': call['call_id'],
                                'output': json.dumps(FAKE_PRICE)}]
            second = consume(client.responses.create(**_tool_request(shape, model, outputs)))
            ok = second['completed'] and not second['failed'] and bool(second['text'])
            report.add('C5', f"{shape}：调用了 {call['name']}（namespace={call.get('namespace') or '无'}）；"
                             f"回传结果后 {'得到最终回答' if ok else '失败 code=' + str(second['failed'])}")
            if ok:
                working.append(shape)
        except Exception as exc:  # noqa: BLE001
            report.add('C5', f'{shape}：拒绝：{short_error(exc)}')
    report.facts['tool_shapes_ok'] = working
    return working[0] if working else None


# ---------------------------------------------------------------------------------------------- C6 langchain-openai

def _capture_client(captured: list[dict[str, Any]]):
    import httpx

    def hook(request) -> None:
        try:
            body = json.loads(request.content.decode('utf-8')) if request.content else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {}
        roles = [item.get('role') or item.get('type') for item in body.get('input', []) if isinstance(item, dict)]
        tools = [tool.get('type') for tool in body.get('tools', []) if isinstance(tool, dict)]
        captured.append({'keys': sorted(body), 'roles': roles, 'tools': tools,
                         'store': body.get('store'), 'stream': body.get('stream')})

    return httpx.Client(timeout=httpx.Timeout(MODEL_TIMEOUT_S, connect=10), event_hooks={'request': [hook]})


def _lc_tool():
    from langchain_core.tools import tool

    @tool
    def get_price(ticker: str) -> str:
        """返回一只股票的最新收盘价（核查用的假数据）。"""
        return json.dumps({**FAKE_PRICE, 'ticker': ticker})
    return get_price


FORBIDDEN_FIELDS = ('background', 'conversation', 'max_output_tokens', 'max_tool_calls', 'metadata', 'moderation',
                    'multi_agent', 'prompt', 'prompt_cache_retention', 'safety_identifier', 'temperature',
                    'top_logprobs', 'top_p', 'truncation', 'user', 'previous_response_id')


def _rewriting_class(tool_shape: str):
    """spec §8.5 的路径 A 改写（与将来的 SiwcChatOpenAI 同一规则的最小版本）。"""
    from langchain_openai import ChatOpenAI

    class RewritingChatOpenAI(ChatOpenAI):
        def _get_request_payload(self, input_, *, stop=None, **kwargs):
            payload = super()._get_request_payload(input_, stop=stop, **kwargs)
            items = list(payload.get('input') or [])
            head: list[str] = []
            while items and isinstance(items[0], dict) and items[0].get('role') in ('system', 'developer') \
                    and isinstance(items[0].get('content'), str):
                head.append(items.pop(0)['content'])
            for item in items:
                if isinstance(item, dict) and item.get('role') == 'system':
                    item['role'] = 'developer'
            if head:
                payload['instructions'] = '\n\n'.join(filter(None, [payload.get('instructions'), *head]))
            tools = payload.get('tools')
            if tools and tool_shape == 'namespace':
                payload['tools'] = [{'type': 'namespace', 'name': 'workbench',
                                     'description': '投研工作台的只读数据工具', 'tools': tools}]
            elif tools and tool_shape == 'additional_tools':
                payload.pop('tools')
                items.insert(0, {'type': 'additional_tools', 'role': 'developer', 'tools': tools})
            payload['input'] = items
            for field in FORBIDDEN_FIELDS:
                payload.pop(field, None)
            return payload

    return RewritingChatOpenAI


def _lc_round_trip(model_obj, messages: list) -> dict[str, Any]:
    from langchain_core.messages import ToolMessage

    tool_obj = _lc_tool()
    bound = model_obj.bind_tools([tool_obj])
    first = bound.invoke(messages)
    result: dict[str, Any] = {'content_type': type(first.content).__name__, 'tool_calls': len(first.tool_calls),
                              'usage': getattr(first, 'usage_metadata', None), 'final': None}
    if first.tool_calls:
        call = first.tool_calls[0]
        follow = [*messages, first, ToolMessage(content=tool_obj.invoke(call['args']), tool_call_id=call['id'])]
        final = bound.invoke(follow)
        text = getattr(final, 'text', None)
        text = text() if callable(text) else text
        result['final'] = {'content_type': type(final.content).__name__, 'text_len': len(str(text or final.content))}
    return result


def langchain_checks(report: Report, tokens: dict[str, Any], model: str, tool_shape: str | None) -> None:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    common = dict(model=model, api_key=tokens['access_token'], base_url=RESOURCE, use_responses_api=True,
                  store=False, streaming=True, temperature=None, max_retries=0)
    variants = [
        ('原样 ChatOpenAI + SystemMessage', ChatOpenAI, {}, [SystemMessage(content=INSTRUCTIONS)]),
        ('原样 ChatOpenAI + developer 角色', ChatOpenAI, {},
         [SystemMessage(content=INSTRUCTIONS, additional_kwargs={'__openai_role__': 'developer'})]),
        (f'改写（system→instructions、删被禁字段、工具形状 {tool_shape or "top_level"}）+ output_version=v0',
         _rewriting_class(tool_shape or 'top_level'), {'output_version': 'v0'}, [SystemMessage(content=INSTRUCTIONS)]),
    ]
    success: list[str] = []
    for label, cls, extra, head in variants:
        captured: list[dict[str, Any]] = []
        try:
            model_obj = cls(**common, **extra, http_client=_capture_client(captured))
            out = _lc_round_trip(model_obj, [*head, HumanMessage(content=TOOL_PROMPT)])
            ok = out['final'] is not None
            report.add('C6', f"{label}：{'两轮工具循环成功' if ok else '模型没有调用工具'}；content 类型 "
                             f"{out['content_type']}；usage_metadata {out['usage']}")
            if ok:
                success.append(label)
        except Exception as exc:  # noqa: BLE001
            report.add('C6', f'{label}：失败：{short_error(exc)}')
        if captured:
            first = captured[0]
            report.add('C6', f"  请求体键：{', '.join(first['keys'])}；input 角色 / 类型：{first['roles']}；"
                             f"tools 类型：{first['tools']}；store={first['store']}；stream={first['stream']}")
    report.facts['langchain_ok'] = success


# ---------------------------------------------------------------------------------------------- 主流程

def recommend(report: Report) -> None:
    lc_ok = report.facts.get('langchain_ok') or []
    shapes = report.facts.get('tool_shapes_ok') or []
    if any(label.startswith('改写') for label in lc_ok) or any(label.startswith('原样') for label in lc_ok):
        report.add('C8', f'路径 A（ChatOpenAI 子类改写请求体）；TOOL_SHAPE={shapes[0] if shapes else "top_level"}')
    elif shapes:
        report.add('C8', f'路径 B（openai SDK 薄客户端，保留 ToolNode）；TOOL_SHAPE={shapes[0]}')
    else:
        report.add('C8', '两条路径都没有跑通带工具的调用：按 spec §8.7 第 3 条，模型层推迟、先向编排者汇报')
    report.add('C7', '核查时未触发额度用尽（正常）；实施后第一次出现时按 agent_runs.detail 追加原文')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='v2.8 Sign in with ChatGPT 开工前核查（只由你本人执行）')
    parser.add_argument('--port', type=int, default=0, help='回环回调端口，默认 0 = 系统分配')
    parser.add_argument('--model', default=None, help='指定模型 slug；默认取 visibility=list 的第一个')
    parser.add_argument('--no-browser', action='store_true', help='不自动打开浏览器，只打印授权地址')
    parser.add_argument('--reuse', action='store_true', help='复用上次保存在 .local/siwc-precheck/ 的令牌，不重新登录')
    parser.add_argument('--skip-probes', action='store_true', help='跳过被拒字段的逐个探测（C4）')
    parser.add_argument('--keep-token', action='store_true', help='结束时保留本地令牌文件、不撤销')
    parser.add_argument('--delete-token', action='store_true', help='结束时不询问，直接撤销并删除本地令牌文件')
    args = parser.parse_args(argv)

    report = Report()
    say(f'{SCRIPT_VERSION} · 输出已脱敏，不含任何令牌')
    # openai SDK 会从环境读组织 / 项目 / base_url；这些不属于 ChatGPT 连接，先拿掉，只记录是否存在。
    dropped = [name for name in ('OPENAI_ORG_ID', 'OPENAI_PROJECT_ID', 'OPENAI_BASE_URL', 'OPENAI_API_KEY')
               if os.environ.pop(name, None) is not None]
    report.facts['proxy_env'] = any(os.environ.get(k) for k in ('https_proxy', 'HTTPS_PROXY', 'http_proxy', 'HTTP_PROXY'))
    from importlib import metadata
    for package, key in (('openai', 'openai_version'), ('langchain-openai', 'langchain_openai_version')):
        try:
            report.facts[key] = metadata.version(package)
        except metadata.PackageNotFoundError:
            say(f'  缺少依赖 {package}；请用 .venv/bin/python 运行')
    if dropped:
        say(f"  已在本进程里忽略环境变量：{', '.join(dropped)}")

    disc = guarded(report, 'C1', '第 1 步：发现文档', lambda: discover(report))
    tokens = reuse_tokens(report) if args.reuse else None
    if tokens is None and disc is not None:
        tokens = guarded(report, 'C1', '第 2 步：登录（动态注册 + PKCE + 回环回调）',
                         lambda: login(report, disc, port=args.port, open_browser=not args.no_browser))
    if tokens is not None and disc is not None and tokens.get('refresh_token'):
        refreshed = guarded(report, 'C1', '第 3 步：刷新一次（确认 refresh token 可用与是否轮换）',
                            lambda: refresh(report, disc, tokens))
        tokens = refreshed or tokens

    model = args.model
    if tokens is not None:
        visible = guarded(report, 'C2', '第 4 步：GET /v1/models', lambda: list_models(report, tokens)) or []
        if model is None and visible:
            model = visible[0].get('slug') or visible[0].get('id')
    if tokens is None:
        for key in ('C2', 'C3', 'C4', 'C5', 'C6'):
            report.add(key, '跳过：没有可用的 access token')
    elif not model:
        for key in ('C3', 'C4', 'C5', 'C6'):
            report.add(key, '跳过：没有可用的模型（用 --model 指定）')
    else:
        say(f'  使用模型：{model}')
        guarded(report, 'C3', '第 5 步：原生 openai SDK 最小调用', lambda: sdk_minimal(report, tokens, model))
        if args.skip_probes:
            report.add('C4', '跳过（--skip-probes）')
        else:
            guarded(report, 'C4', '第 6 步：被拒字段逐个探测', lambda: probe_fields(report, tokens, model))
        shape = guarded(report, 'C5', '第 7 步：工具形状（顶层函数 / namespace / additional_tools）',
                        lambda: tool_shapes(report, tokens, model))
        guarded(report, 'C6', '第 8 步：langchain-openai ChatOpenAI（Responses 模式）',
                lambda: langchain_checks(report, tokens, model, shape))
    recommend(report)

    if tokens is not None:
        if args.keep_token:
            keep = True
        elif args.delete_token or not sys.stdin.isatty():
            keep = False
        else:
            answer = input('\n撤销 refresh token 并删除本地令牌文件？[Y/n] ').strip().lower()
            keep = answer in ('n', 'no')
        if keep:
            say(f'  已保留 {TOKENS_FILE.relative_to(REPO)}（0600）；用完请再运行一次并选择删除，或手动删除。')
        else:
            guarded(report, 'C1', '收尾：撤销并删除本地令牌', lambda: revoke(report, disc, tokens))
            try:
                TOKENS_FILE.unlink(missing_ok=True)
                say(f'  已删除 {TOKENS_FILE.relative_to(REPO)}')
            except OSError as exc:
                say(f'  删除令牌文件失败：{short_error(exc)}；请手动删除 {TOKENS_FILE}')

    summary = report.markdown()
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        SUMMARY_FILE.write_text(summary + '\n', encoding='utf-8')
        saved = f'（同时写入 {SUMMARY_FILE.relative_to(REPO)}）'
    except OSError:
        saved = ''
    say('')
    say(f'========== 核查摘要：整段贴到 spec §17 末尾{saved} ==========')
    print(summary)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
