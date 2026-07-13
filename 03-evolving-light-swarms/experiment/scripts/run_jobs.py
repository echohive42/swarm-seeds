#!/usr/bin/env python3
"""Run up to 50 dependency-aware Experiment 03 jobs via fresh, tool-disabled Codex CLI processes with durable retries and telemetry."""
from __future__ import annotations
import argparse, concurrent.futures, datetime as dt, fcntl, hashlib, json, math, os, re, signal, subprocess, sys, tempfile, threading, time
from pathlib import Path; from typing import Any, Iterable
MODEL, REASONING_EFFORT, PUBLIC_LABEL = 'gpt-5.6-luna', 'low', 'Light reasoning'
DEFAULT_TIMEOUT, MAX_CONCURRENCY, MAX_INFRA_ATTEMPTS, MAX_SCHEMA_INVALID_ATTEMPTS = 300, 50, 3, 2
LEDGER_VERSION = 'experiment-03-attempts-v1'; JOB_ID_RE = re.compile('^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$')
DISABLED_FEATURES = ('apps', 'browser_use', 'browser_use_external', 'browser_use_full_cdp_access', 'computer_use', 'enable_mcp_apps', 'goals', 'hooks', 'image_generation', 'in_app_browser', 'multi_agent', 'multi_agent_v2', 'plugin_sharing', 'plugins', 'remote_plugin', 'shell_tool', 'skill_mcp_dependency_install', 'standalone_web_search', 'tool_suggest', 'unified_exec', 'workspace_dependencies'); TOOL_MARKERS = ('tool_call', 'function_call', 'mcp_tool_call', 'command_execution', 'computer_action', 'browser_action')
class RunnerError(RuntimeError): pass
def utc_now() -> str: return dt.datetime.now(dt.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
def canonical_bytes(value: Any) -> bytes: return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
def sha256_bytes(value: bytes) -> str: return hashlib.sha256(value).hexdigest()
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()
def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); descriptor, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
def atomic_json(path: Path, value: Any) -> None: atomic_write(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8') + b'\n')
class RunLock:
    def __init__(self, run_dir: Path) -> None:
        self.path = run_dir / '.run.lock'; self.handle: Any = None
    def __enter__(self) -> 'RunLock':
        self.path.parent.mkdir(parents=True, exist_ok=True); self.handle = self.path.open('a+', encoding='utf-8')
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.handle.close()
            raise RunnerError(f'another runner owns {self.path.parent}') from exc
        self.handle.seek(0); self.handle.truncate(); self.handle.write(json.dumps({'pid': os.getpid(), 'acquired_at': utc_now()}) + '\n')
        self.handle.flush(); os.fsync(self.handle.fileno()); return self
    def __exit__(self, *_: Any) -> None:
        if self.handle:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN); self.handle.close()
class ActiveCounter:
    def __init__(self) -> None:
        self.lock = threading.Lock(); self.active = 0; self.maximum = 0
    def enter(self) -> None:
        with self.lock:
            self.active += 1; self.maximum = max(self.maximum, self.active)
    def leave(self) -> None:
        with self.lock:
            self.active -= 1
def _safe_relative(base: Path, relative: str, label: str) -> Path:
    path = (base / relative).resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError as exc:
        raise RunnerError(f'{label} escapes the manifest directory: {relative}') from exc
    return path
def _strict_json(text: str) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            if key in output:
                raise ValueError(f'duplicate JSON key {key!r}')
            output[key] = value
        return output
    def nonfinite(token: str) -> None: raise ValueError(f'non-finite JSON number {token}')
    return json.loads(text, object_pairs_hook=unique, parse_constant=nonfinite)
def load_manifest(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    manifest = _strict_json(path.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or not isinstance(manifest.get('jobs'), list):
        raise RunnerError('job manifest must be an object containing a jobs array')
    if manifest.get('model', MODEL) != MODEL or manifest.get('reasoning_effort', REASONING_EFFORT) != REASONING_EFFORT:
        raise RunnerError('Experiment 03 jobs must use gpt-5.6-luna with provider effort low')
    if manifest.get('public_condition_label', PUBLIC_LABEL) != PUBLIC_LABEL:
        raise RunnerError("public condition label must be 'Light reasoning'")
    base = path.resolve().parent
    jobs: dict[str, dict[str, Any]] = {}
    for raw in manifest['jobs']:
        if not isinstance(raw, dict) or not isinstance(raw.get('job_id'), str) or (not JOB_ID_RE.fullmatch(raw['job_id'])):
            raise RunnerError('every job requires a stable job_id using letters, digits, dot, dash, or underscore')
        job_id = raw['job_id']
        if job_id in jobs:
            raise RunnerError(f'duplicate job_id {job_id}')
        if ('prompt' in raw) == ('prompt_path' in raw):
            raise RunnerError(f'{job_id} must define exactly one of prompt or prompt_path')
        schema_path_key = 'schema_path' if 'schema_path' in raw else 'output_schema_path'
        if ('output_schema' in raw) == (schema_path_key in raw):
            raise RunnerError(f'{job_id} must define exactly one output_schema or schema_path')
        prompt = raw.get('prompt')
        if 'prompt_path' in raw:
            prompt = _safe_relative(base, raw['prompt_path'], 'prompt_path').read_text(encoding='utf-8')
        schema = raw.get('output_schema')
        if schema_path_key in raw:
            schema = _strict_json(_safe_relative(base, raw[schema_path_key], 'schema_path').read_text(encoding='utf-8'))
        dependencies = raw.get('dependency_ids', [])
        expected = raw.get('expected_case_ids', [])
        if not isinstance(prompt, str) or not prompt.strip() or (not isinstance(schema, dict)):
            raise RunnerError(f'{job_id} has an invalid prompt or output schema')
        if not isinstance(dependencies, list) or any((not isinstance(item, str) for item in dependencies)):
            raise RunnerError(f'{job_id}.dependency_ids must be a string array')
        if not isinstance(expected, list) or any((not isinstance(item, str) for item in expected)) or len(set(expected)) != len(expected):
            raise RunnerError(f'{job_id}.expected_case_ids must contain unique strings')
        expected_block_id = raw.get('expected_block_id')
        if expected_block_id is not None and (not isinstance(expected_block_id, str)):
            raise RunnerError(f'{job_id}.expected_block_id must be a string')
        jobs[job_id] = {'job_id': job_id, 'prompt': prompt, 'output_schema': schema, 'dependency_ids': dependencies, 'expected_case_ids': expected, 'expected_block_id': expected_block_id}
    for job in jobs.values():
        unknown = set(job['dependency_ids']) - set(jobs)
        if unknown or job['job_id'] in job['dependency_ids']:
            raise RunnerError(f"invalid dependencies for {job['job_id']}: {sorted(unknown)}")
    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(job_id: str) -> None:
        if job_id in visiting:
            raise RunnerError(f'dependency cycle includes {job_id}')
        if job_id in visited:
            return
        visiting.add(job_id)
        for dependency in jobs[job_id]['dependency_ids']:
            visit(dependency)
        visiting.remove(job_id)
        visited.add(job_id)
    for job_id in jobs:
        visit(job_id)
    return (manifest, jobs)
def _resolve_ref(root: dict[str, Any], reference: str) -> Any:
    if not reference.startswith('#/'):
        raise ValueError(f'only local JSON Schema references are supported: {reference}')
    value: Any = root
    for part in reference[2:].split('/'):
        value = value[part.replace('~1', '/').replace('~0', '~')]
    return value
def validate_schema(value: Any, schema: dict[str, Any], root: dict[str, Any] | None=None, path: str='$', errors: list[str] | None=None) -> list[str]:
    """Validate the JSON Schema subset used by structured experiment outputs."""
    root, errors = (root or schema, errors if errors is not None else [])
    if '$ref' in schema:
        try:
            return validate_schema(value, _resolve_ref(root, schema['$ref']), root, path, errors)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f'{path}: invalid $ref: {exc}')
            return errors
    if 'const' in schema and value != schema['const']:
        errors.append(f"{path}: must equal {schema['const']!r}")
    if 'enum' in schema and value not in schema['enum']:
        errors.append(f'{path}: is not an allowed value')
    if 'oneOf' in schema:
        matches = sum((not validate_schema(value, option, root, path, []) for option in schema['oneOf']))
        if matches != 1:
            errors.append(f'{path}: must match exactly one oneOf branch')
        return errors
    if 'anyOf' in schema and (not any((not validate_schema(value, option, root, path, []) for option in schema['anyOf']))):
        errors.append(f'{path}: must match an anyOf branch')
        return errors
    expected = schema.get('type')
    checks = {'object': lambda x: isinstance(x, dict), 'array': lambda x: isinstance(x, list), 'string': lambda x: isinstance(x, str), 'integer': lambda x: isinstance(x, int) and (not isinstance(x, bool)), 'number': lambda x: isinstance(x, (int, float)) and (not isinstance(x, bool)) and math.isfinite(x), 'boolean': lambda x: isinstance(x, bool), 'null': lambda x: x is None}
    types = expected if isinstance(expected, list) else [expected] if expected else []
    if types and (not any((kind in checks and checks[kind](value) for kind in types))):
        errors.append(f'{path}: expected type {expected!r}')
        return errors
    if isinstance(value, dict):
        required = schema.get('required', [])
        if isinstance(required, list):
            for key in required:
                if key not in value:
                    errors.append(f'{path}: missing required key {key!r}')
        properties = schema.get('properties', {})
        for key, child in value.items():
            if key in properties:
                validate_schema(child, properties[key], root, f'{path}.{key}', errors)
            elif schema.get('additionalProperties') is False:
                errors.append(f'{path}: unexpected key {key!r}')
            elif isinstance(schema.get('additionalProperties'), dict):
                validate_schema(child, schema['additionalProperties'], root, f'{path}.{key}', errors)
    elif isinstance(value, list):
        if len(value) < schema.get('minItems', 0) or ('maxItems' in schema and len(value) > schema['maxItems']):
            errors.append(f'{path}: array length is outside allowed range')
        if schema.get('uniqueItems') and len({canonical_bytes(item) for item in value}) != len(value):
            errors.append(f'{path}: array items must be unique')
        prefix = schema.get('prefixItems', [])
        for index, child_schema in enumerate(prefix[:len(value)]):
            validate_schema(value[index], child_schema, root, f'{path}[{index}]', errors)
        items = schema.get('items')
        if isinstance(items, dict):
            for index, child in enumerate(value[len(prefix):], len(prefix)):
                validate_schema(child, items, root, f'{path}[{index}]', errors)
        elif items is False and len(value) > len(prefix):
            errors.append(f'{path}: additional array items are forbidden')
    elif isinstance(value, str):
        if len(value) < schema.get('minLength', 0) or ('maxLength' in schema and len(value) > schema['maxLength']):
            errors.append(f'{path}: string length is outside allowed range')
        if 'pattern' in schema and re.search(schema['pattern'], value) is None:
            errors.append(f'{path}: string does not match required pattern')
    elif isinstance(value, (int, float)) and (not isinstance(value, bool)):
        if 'minimum' in schema and value < schema['minimum']:
            errors.append(f'{path}: number is below minimum')
        if 'maximum' in schema and value > schema['maximum']:
            errors.append(f'{path}: number is above maximum')
    return errors
def validate_output(text: str, schema: dict[str, Any], expected_case_ids: list[str], expected_block_id: str | None=None) -> list[str]:
    try:
        document = _strict_json(text)
    except (json.JSONDecodeError, ValueError) as exc:
        return [f'$: invalid JSON: {exc}']
    errors = validate_schema(document, schema)
    if expected_block_id is not None and (not isinstance(document, dict) or document.get('block_id') != expected_block_id):
        errors.append('$: block_id does not match expected_block_id')
    if expected_case_ids:
        records: Any = document.get('results') if isinstance(document, dict) else None
        if records is None and isinstance(document, dict) and ('case_id' in document):
            records = [document]
        if not isinstance(records, list) or any((not isinstance(item, dict) for item in records)):
            errors.append('$: expected case IDs require an object result or results array')
        else:
            observed = [item.get('case_id') for item in records]
            if len(observed) != len(expected_case_ids) or set(observed) != set(expected_case_ids):
                errors.append('$: returned case IDs do not exactly match expected_case_ids')
    return errors
def build_command(binary: Path, schema: Path, workspace: Path, last_message: Path) -> list[str]:
    command = [str(binary), 'exec', '--model', MODEL, '-c', 'model_reasoning_effort="low"', '--ephemeral', '--ignore-user-config', '--ignore-rules', '--strict-config', '--skip-git-repo-check', '--sandbox', 'read-only']
    for feature in DISABLED_FEATURES:
        command.extend(('--disable', feature))
    command.extend(('--json', '--color', 'never', '--output-schema', str(schema), '--output-last-message', str(last_message), '-C', str(workspace), '-'))
    return command
def public_command(command: list[str]) -> list[str]:
    result: list[str] = []
    replacement: str | None = None
    for index, token in enumerate(command):
        if replacement is not None:
            result.append(replacement)
            replacement = None
        elif index == 0:
            result.append('<FROZEN_CODEX_BINARY>')
        elif token in {'--output-schema', '--output-last-message', '-C'}:
            result.append(token)
            replacement = {'--output-schema': '<OUTPUT_SCHEMA>', '--output-last-message': '<LAST_MESSAGE>', '-C': '<FRESH_EMPTY_WORKSPACE>'}[token]
        else:
            result.append(token)
    return result
def parse_events(raw: str) -> tuple[list[dict[str, Any]], int, bool]:
    events, failures, tool_event = ([], 0, False)
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            failures += 1
            continue
        if not isinstance(event, dict):
            failures += 1
            continue
        event_type = str(event.get('type', '')).lower()
        item = event.get('item') if isinstance(event.get('item'), dict) else {}
        item_type = str(item.get('type', '')).lower()
        tool_event |= any((marker in event_type or marker in item_type for marker in TOOL_MARKERS))
        events.append(event)
    return (events, failures, tool_event)
def final_message(events: list[dict[str, Any]], path: Path) -> str | None:
    if path.is_file():
        text = path.read_text(encoding='utf-8', errors='replace')
        if text.strip():
            return text.strip()
    messages = []
    for event in events:
        item = event.get('item') if isinstance(event.get('item'), dict) else {}
        if str(event.get('type', '')).lower() == 'item.completed' and item.get('type') == 'agent_message':
            text = item.get('text', item.get('content'))
            if isinstance(text, str) and text.strip():
                messages.append(text.strip())
    return messages[-1] if messages else None
def telemetry(events: list[dict[str, Any]]) -> tuple[dict[str, int] | None, str | None]:
    usage, model = (None, None)
    for event in events:
        candidate_usage = event.get('usage')
        if isinstance(candidate_usage, dict):
            normalized = {key: value for key, value in candidate_usage.items() if key in {'input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_tokens', 'total_tokens'} and isinstance(value, int) and (not isinstance(value, bool)) and (value >= 0)}
            if normalized:
                if 'total_tokens' not in normalized:
                    normalized['total_tokens'] = normalized.get('input_tokens', 0) + normalized.get('output_tokens', 0)
                usage = normalized
        for candidate in (event.get('model'), event.get('model_id'), event.get('model_name')):
            if isinstance(candidate, str) and candidate:
                model = candidate
    return (usage, model)
def request_hash(job: dict[str, Any], binary_hash: str, timeout: int) -> str:
    identity = {'prompt_sha256': sha256_bytes(job['prompt'].encode('utf-8')), 'schema_sha256': sha256_bytes(canonical_bytes(job['output_schema'])), 'model': MODEL, 'reasoning_effort': REASONING_EFFORT, 'binary_sha256': binary_hash, 'timeout': timeout, 'disabled_features': list(DISABLED_FEATURES)}
    return sha256_bytes(canonical_bytes(identity))
def load_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events = []
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if line.strip():
            event = json.loads(line)
            if not isinstance(event, dict):
                raise RunnerError(f'ledger line {number} is not an object')
            events.append(event)
    return events
def job_state(events: list[dict[str, Any]], job_id: str) -> dict[str, Any]:
    attempts = [event for event in events if event.get('event_type') == 'attempt' and event.get('job_id') == job_id]
    valid = next((event for event in attempts if event.get('status') == 'valid_output'), None)
    protocol = next((event for event in attempts if event.get('status') == 'protocol_violation'), None)
    invalid_count = sum((event.get('status') == 'schema_invalid' for event in attempts))
    infra_count = sum((event.get('status') == 'infrastructure_failure' for event in attempts))
    if valid:
        return {'state': 'closed', 'outcome': 'valid_output', 'attempt_count': len(attempts)}
    if protocol:
        return {'state': 'closed', 'outcome': 'protocol_violation', 'attempt_count': len(attempts)}
    if invalid_count >= MAX_SCHEMA_INVALID_ATTEMPTS:
        return {'state': 'closed', 'outcome': 'schema_invalid_exhausted', 'attempt_count': len(attempts)}
    if infra_count >= MAX_INFRA_ATTEMPTS:
        return {'state': 'closed', 'outcome': 'infrastructure_exhausted', 'attempt_count': len(attempts)}
    return {'state': 'open', 'outcome': None, 'attempt_count': len(attempts), 'next_attempt': len(attempts) + 1}
def validate_ledger(events: list[dict[str, Any]], jobs: dict[str, dict[str, Any]]) -> None:
    request_hashes: dict[str, set[str]] = {}
    numbers: dict[str, int] = {}
    closed: set[str] = set()
    for event in events:
        job_id = event.get('job_id')
        if event.get('ledger_version') != LEDGER_VERSION or job_id not in jobs:
            raise RunnerError('ledger has an invalid version or unknown job_id')
        if event.get('event_type') == 'attempt':
            if job_id in closed:
                raise RunnerError(f'attempt recorded after {job_id} closed')
            numbers[job_id] = numbers.get(job_id, 0) + 1
            if event.get('attempt_number') != numbers[job_id]:
                raise RunnerError(f'non-contiguous attempt numbers for {job_id}')
            request_hashes.setdefault(job_id, set()).add(str(event.get('request_sha256')))
        elif event.get('event_type') == 'job_closed':
            closed.add(job_id)
        else:
            raise RunnerError('unknown ledger event_type')
    if any((len(values) != 1 for values in request_hashes.values())):
        raise RunnerError('a retry changed its frozen request identity')
def append_attempt(ledger: Path, event: dict[str, Any], jobs: dict[str, dict[str, Any]]) -> None:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open('a+', encoding='utf-8') as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        events = [json.loads(line) for line in handle if line.strip()]
        validate_ledger(events, jobs)
        state = job_state(events, event['job_id'])
        if state['state'] != 'open' or event['attempt_number'] != state['next_attempt']:
            raise RunnerError(f"stale or closed attempt for {event['job_id']}")
        prior_hashes = {item['request_sha256'] for item in events if item.get('event_type') == 'attempt' and item.get('job_id') == event['job_id']}
        if prior_hashes and prior_hashes != {event['request_sha256']}:
            raise RunnerError(f"retry request changed for {event['job_id']}")
        additions = [event]
        projected = events + [event]
        projected_state = job_state(projected, event['job_id'])
        if projected_state['state'] == 'closed':
            additions.append({'ledger_version': LEDGER_VERSION, 'event_type': 'job_closed', 'job_id': event['job_id'], 'closed_at': event['finished_at'], 'outcome': projected_state['outcome']})
        handle.seek(0, os.SEEK_END)
        handle.write(''.join((json.dumps(item, sort_keys=True, separators=(',', ':')) + '\n' for item in additions)))
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
def invoke(binary: Path, job: dict[str, Any], attempt_dir: Path, timeout: int, active: ActiveCounter) -> dict[str, Any]:
    attempt_dir.mkdir(parents=True, exist_ok=False)
    schema_path = attempt_dir / 'output_schema.json'
    last_path = attempt_dir / 'last_message.txt'
    atomic_json(schema_path, job['output_schema'])
    workspace = attempt_dir / 'empty_workspace'
    workspace.mkdir()
    command = build_command(binary, schema_path, workspace, last_path)
    atomic_json(attempt_dir / 'command.json', {'argv': public_command(command), 'prompt_transport': 'stdin'})
    started_at = utc_now()
    started = time.monotonic()
    timed_out, start_failure, process_started = (False, False, False)
    stdout = stderr = b''
    exit_code: int | None = None
    active.enter()
    try:
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            process_started = True
            atomic_json(attempt_dir / 'process.json', {'pid': process.pid, 'started_at': started_at})
        except OSError as exc:
            process, start_failure, stderr = (None, True, str(exc).encode('utf-8', errors='replace'))
        if process:
            try:
                stdout, stderr = process.communicate(job['prompt'].encode('utf-8'), timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    stdout, stderr = process.communicate(timeout=5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    stdout, stderr = process.communicate()
            exit_code = process.returncode
    finally:
        active.leave()
    duration_ms = int(round((time.monotonic() - started) * 1000))
    atomic_write(attempt_dir / 'events.jsonl', stdout)
    atomic_write(attempt_dir / 'stderr.txt', stderr)
    parsed, failures, tool_event = parse_events(stdout.decode('utf-8', errors='replace'))
    response = final_message(parsed, last_path)
    if isinstance(response, str) and not last_path.is_file():
        atomic_write(last_path, response.encode('utf-8'))
    usage, reported_model = telemetry(parsed)
    result = {'started_at': started_at, 'finished_at': utc_now(), 'duration_ms': duration_ms, 'exit_code': exit_code, 'timed_out': timed_out, 'process_started': process_started, 'start_failure': start_failure, 'jsonl_event_count': len(parsed), 'jsonl_parse_failures': failures, 'tool_event': tool_event, 'response_text': response, 'usage': usage, 'reported_model': reported_model, 'stdout_sha256': sha256_file(attempt_dir / 'events.jsonl'), 'stderr_sha256': sha256_file(attempt_dir / 'stderr.txt'), 'stderr_excerpt': stderr.decode('utf-8', errors='replace')[:800]}
    atomic_json(attempt_dir / 'transport_result.json', result)
    return result
def classify(result: dict[str, Any], job: dict[str, Any]) -> tuple[str, list[str]]:
    if result.get('tool_event'):
        return ('protocol_violation', ['Codex emitted a forbidden tool event'])
    response = result.get('response_text')
    if isinstance(response, str) and response.strip():
        errors = validate_output(response, job['output_schema'], job['expected_case_ids'], job.get('expected_block_id'))
        return ('schema_invalid', errors) if errors else ('valid_output', [])
    details = []
    if result.get('timed_out'):
        details.append('hard timeout')
    if result.get('start_failure'):
        details.append('process start failure')
    if result.get('exit_code') not in {0, None}:
        details.append(f"exit code {result['exit_code']}")
    if result.get('stderr_excerpt'):
        details.append(result['stderr_excerpt'])
    return ('infrastructure_failure', details or ['no substantive final agent_message'])
def execute_attempt(binary: Path, job: dict[str, Any], run_dir: Path, ledger: Path, binary_hash: str, timeout: int, active: ActiveCounter, jobs: dict[str, dict[str, Any]]) -> str:
    events = load_ledger(ledger)
    state = job_state(events, job['job_id'])
    attempt_number = state['next_attempt']
    attempt_dir = run_dir / 'jobs' / job['job_id'] / f'attempt-{attempt_number:02d}'
    if attempt_dir.exists():
        result_path = attempt_dir / 'transport_result.json'
        process_path = attempt_dir / 'process.json'
        if not result_path.is_file():
            if process_path.is_file():
                pid = json.loads(process_path.read_text(encoding='utf-8')).get('pid')
                try:
                    if isinstance(pid, int):
                        os.kill(pid, 0)
                        raise RunnerError(f"orphan process {pid} is still active for {job['job_id']}")
                except ProcessLookupError:
                    pass
            result = {'started_at': utc_now(), 'finished_at': utc_now(), 'duration_ms': 0, 'exit_code': None, 'timed_out': False, 'process_started': process_path.is_file(), 'start_failure': not process_path.is_file(), 'jsonl_event_count': 0, 'jsonl_parse_failures': 0, 'tool_event': False, 'response_text': None, 'usage': None, 'reported_model': None, 'stderr_excerpt': 'runner crashed before durable result'}
            for name in ('events.jsonl', 'stderr.txt'):
                if not (attempt_dir / name).exists(): atomic_write(attempt_dir / name, b'')
            atomic_json(result_path, result)
        else:
            result = json.loads(result_path.read_text(encoding='utf-8'))
    else:
        result = invoke(binary, job, attempt_dir, timeout, active)
    status, errors = classify(result, job)
    response = result.get('response_text')
    event = {'ledger_version': LEDGER_VERSION, 'event_type': 'attempt', 'job_id': job['job_id'], 'attempt_number': attempt_number, 'started_at': result['started_at'], 'finished_at': result['finished_at'], 'status': status, 'request_sha256': request_hash(job, binary_hash, timeout), 'duration_ms': result['duration_ms'], 'exit_code': result.get('exit_code'), 'timed_out': result.get('timed_out', False), 'jsonl_event_count': result.get('jsonl_event_count', 0), 'jsonl_parse_failures': result.get('jsonl_parse_failures', 0), 'usage': result.get('usage'), 'reported_model': result.get('reported_model'), 'response_sha256': sha256_bytes(response.encode('utf-8')) if isinstance(response, str) else None, 'validation_errors': errors[:12], 'artifact_relpath': attempt_dir.relative_to(run_dir).as_posix()}
    append_attempt(ledger, event, jobs)
    closed_state = job_state(load_ledger(ledger), job['job_id'])
    if closed_state['state'] == 'closed':
        document = None
        if status == 'valid_output' and isinstance(response, str):
            document = _strict_json(response)
        atomic_json(run_dir / 'jobs' / job['job_id'] / 'result.json', {'job_id': job['job_id'], 'outcome': closed_state['outcome'], 'attempt_count': closed_state['attempt_count'], 'terminal_artifact_relpath': event['artifact_relpath'], 'response_sha256': event['response_sha256'], 'document': document})
    return status
def cli_identity(binary_arg: Path) -> tuple[Path, dict[str, str]]:
    absolute = Path(os.path.abspath(binary_arg))
    resolved = absolute.resolve()
    if absolute.is_symlink():
        raise RunnerError('--codex-binary must name the versioned release binary, not a mutable symlink')
    if not resolved.is_file():
        raise RunnerError(f'Codex binary does not exist: {resolved}')
    completed = subprocess.run([str(resolved), '--version'], capture_output=True, text=True, timeout=30, check=False)
    if completed.returncode != 0 or not completed.stdout.strip():
        raise RunnerError('Codex CLI version check failed')
    parts = resolved.parts
    locator = '/'.join(parts[parts.index('releases') + 1:]) if 'releases' in parts else resolved.name
    return (resolved, {'version': completed.stdout.strip(), 'binary_sha256': sha256_file(resolved), 'release_locator': locator})
def _selected_with_dependencies(jobs: dict[str, dict[str, Any]], requested: list[str] | None) -> set[str]:
    if not requested:
        return set(jobs)
    unknown = set(requested) - set(jobs)
    if unknown:
        raise RunnerError(f'unknown requested job IDs: {sorted(unknown)}')
    selected: set[str] = set()
    def add(job_id: str) -> None:
        if job_id not in selected:
            selected.add(job_id)
            for dependency in jobs[job_id]['dependency_ids']:
                add(dependency)
    for job_id in requested:
        add(job_id)
    return selected
def run(args: argparse.Namespace) -> int:
    _, jobs = load_manifest(args.manifest)
    selected = _selected_with_dependencies(jobs, args.job_id)
    if not 1 <= args.concurrency <= MAX_CONCURRENCY:
        raise RunnerError(f'concurrency must be from 1 through {MAX_CONCURRENCY}')
    if args.timeout <= 0:
        raise RunnerError('timeout must be positive')
    if args.dry_run:
        print(json.dumps({'jobs': len(selected), 'model': MODEL, 'reasoning_effort': REASONING_EFFORT, 'public_label': PUBLIC_LABEL, 'concurrency': args.concurrency}, sort_keys=True))
        return 0
    binary, identity = cli_identity(args.codex_binary)
    run_dir = args.run_dir.resolve()
    with RunLock(run_dir):
        preflight = run_dir / 'preflight.json'
        if preflight.exists() and json.loads(preflight.read_text(encoding='utf-8')) != identity:
            raise RunnerError('Codex CLI identity drifted since this run began')
        if not preflight.exists():
            atomic_json(preflight, identity)
        ledger = run_dir / 'attempts.jsonl'
        active = ActiveCounter()
        attempts_started = 0
        while True:
            events = load_ledger(ledger)
            validate_ledger(events, jobs)
            states = {job_id: job_state(events, job_id) for job_id in selected}
            infrastructure_failed = {job_id: state['outcome'] for job_id, state in states.items() if state.get('outcome') == 'infrastructure_exhausted'}
            if infrastructure_failed:
                raise RunnerError(f'exhausted infrastructure retries block collection: {infrastructure_failed}')
            remaining = [jobs[job_id] for job_id in selected if states[job_id]['state'] == 'open']
            if not remaining:
                break
            ready = [job for job in remaining if all((job_state(events, dependency).get('state') == 'closed' for dependency in job['dependency_ids']))]
            ready.sort(key=lambda job: job['job_id'])
            if not ready:
                raise RunnerError('dependency deadlock or failed prerequisite')
            if args.max_attempts_this_run is not None:
                available = args.max_attempts_this_run - attempts_started
                if available <= 0:
                    break
                ready = ready[:available]
            batch = ready[:args.concurrency]
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
                futures = [executor.submit(execute_attempt, binary, job, run_dir, ledger, identity['binary_sha256'], args.timeout, active, jobs) for job in batch]
                for future in concurrent.futures.as_completed(futures):
                    future.result()
            attempts_started += len(batch)
        final_events = load_ledger(ledger)
        final_states = {job_id: job_state(final_events, job_id) for job_id in selected}
        valid_jobs = sum(state.get('outcome') == 'valid_output' for state in final_states.values())
        failed_jobs = sum(state['state'] == 'closed' and state.get('outcome') != 'valid_output' for state in final_states.values())
        summary = {'generated_at': utc_now(), 'selected_jobs': len(selected), 'valid_jobs': valid_jobs, 'failed_jobs': failed_jobs, 'open_jobs': len(selected) - valid_jobs - failed_jobs, 'attempts': sum((event.get('event_type') == 'attempt' for event in final_events)), 'max_active_processes': active.maximum}
        atomic_json(run_dir / 'operational_summary.json', summary)
        print(json.dumps(summary, sort_keys=True))
    return 0
def status(run_dir: Path) -> int:
    ledger = run_dir.resolve() / 'attempts.jsonl'; events = load_ledger(ledger)
    attempts = [event for event in events if event.get('event_type') == 'attempt']; results = []
    jobs_dir = run_dir.resolve() / 'jobs'
    if jobs_dir.is_dir():
        for path in sorted(jobs_dir.glob('*/result.json')):
            result = json.loads(path.read_text(encoding='utf-8')); results.append({key: result.get(key) for key in ('job_id', 'outcome', 'attempt_count', 'response_sha256')})
    valid_jobs = sum(item['outcome'] == 'valid_output' for item in results)
    summary = {'attempts': len(attempts), 'terminal_jobs': len(results), 'valid_jobs': valid_jobs, 'failed_jobs': len(results) - valid_jobs, 'jobs': results}
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True)); return 0
def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); fake = root / 'fake-codex'
        fake_source = "#!/usr/bin/env python3\nimport json,pathlib,sys\nif sys.argv[1:] == ['--version']:\n print('codex-cli 0.test'); raise SystemExit\na=sys.argv[1:]; prompt=sys.stdin.read(); last=pathlib.Path(a[a.index('--output-last-message')+1])\nkind='alwaysbad' if 'ALWAYS_BAD' in prompt else 'bad' if 'MALFORMED_ONCE' in prompt else 'infra' if 'INFRA_ONCE' in prompt else 'ok'\ncounter=pathlib.Path(__file__).with_name(kind+'.count'); n=int(counter.read_text()) if counter.exists() else 0; counter.write_text(str(n+1))\nif kind=='infra' and n==0:\n print('temporary',file=sys.stderr); raise SystemExit(1)\ntext='not-json' if kind=='alwaysbad' or kind=='bad' and n==0 else json.dumps({'block_id':'B01','case_id':kind.upper(),'value':1},separators=(',',':'))\nlast.write_text(text); print(json.dumps({'type':'thread.started','thread_id':'00000000-0000-4000-8000-000000000000'})); print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':text}})); print(json.dumps({'type':'turn.completed','model':'gpt-5.6-luna','usage':{'input_tokens':3,'output_tokens':4,'reasoning_tokens':2}}))\n"
        fake.write_text(fake_source, encoding='utf-8'); fake.chmod(493)
        schema = {'type': 'object', 'additionalProperties': False, 'required': ['block_id', 'case_id', 'value'], 'properties': {'block_id': {'type': 'string'}, 'case_id': {'type': 'string'}, 'value': {'type': 'integer'}}}
        atomic_json(root / 'schema.json', schema)
        for name, prompt in {'bad': 'MALFORMED_ONCE', 'alwaysbad': 'ALWAYS_BAD', 'infra': 'INFRA_ONCE', 'dependent': 'OK'}.items(): atomic_write(root / f'{name}.txt', prompt.encode())
        manifest = {'model': MODEL, 'reasoning_effort': REASONING_EFFORT, 'public_condition_label': PUBLIC_LABEL, 'jobs': [{'job_id': name, 'prompt_path': f'{name}.txt', 'schema_path': 'schema.json', 'expected_block_id': 'B01', 'expected_case_ids': ['OK' if name == 'dependent' else name.upper()], 'dependency_ids': ['bad', 'infra'] if name == 'dependent' else []} for name in ('bad', 'alwaysbad', 'infra', 'dependent')]}
        manifest_path = root / 'jobs.json'; atomic_json(manifest_path, manifest)
        args = argparse.Namespace(manifest=manifest_path, run_dir=root / 'run', codex_binary=fake, concurrency=2, timeout=10, job_id=None, dry_run=False, max_attempts_this_run=None)
        assert run(args) == 0; events = load_ledger(root / 'run' / 'attempts.jsonl')
        assert job_state(events, 'bad')['outcome'] == 'valid_output'; assert job_state(events, 'bad')['attempt_count'] == 2
        assert job_state(events, 'infra')['attempt_count'] == 2; assert job_state(events, 'dependent')['attempt_count'] == 1
        assert job_state(events, 'alwaysbad')['outcome'] == 'schema_invalid_exhausted'; assert json.loads((root / 'run' / 'jobs' / 'alwaysbad' / 'result.json').read_text())['document'] is None
        assert job_state([{'event_type': 'attempt', 'job_id': 'x', 'status': 'infrastructure_failure'}] * 3, 'x')['outcome'] == 'infrastructure_exhausted'
        before = len(events)
        assert run(args) == 0 and len(load_ledger(root / 'run' / 'attempts.jsonl')) == before
        assert (root / 'run' / 'jobs' / 'dependent' / 'result.json').is_file(); command = build_command(fake, root / 's', root / 'w', root / 'l')
        assert command[-1] == '-' and '--ephemeral' in command and ('--ignore-user-config' in command)
        assert all((command[command.index(feature) - 1] == '--disable' for feature in DISABLED_FEATURES))
        assert MAX_CONCURRENCY == 50
    print('run_jobs.py self-test: PASS')
def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__); result.add_argument('--self-test', action='store_true', help='exercise retry/resume with a fake Codex CLI')
    sub = result.add_subparsers(dest='command'); run_parser = sub.add_parser('run', help='execute or resume selected jobs')
    run_parser.add_argument('--manifest', type=Path, required=True); run_parser.add_argument('--run-dir', type=Path, required=True)
    run_parser.add_argument('--codex-binary', type=Path, required=True, help='exact versioned release binary; mutable symlinks are rejected'); run_parser.add_argument('--concurrency', type=int, default=MAX_CONCURRENCY)
    run_parser.add_argument('--timeout-seconds', dest='timeout', type=int, default=DEFAULT_TIMEOUT); run_parser.add_argument('--job-id', action='append', help='select a job and its transitive dependencies')
    run_parser.add_argument('--max-attempts-this-run', type=int, help='stop cleanly after this many new attempts')
    run_parser.add_argument('--dry-run', action='store_true', help='validate and summarize without invoking Codex')
    status_parser = sub.add_parser('status', help='show terminal operational state without reading correctness'); status_parser.add_argument('--run-dir', type=Path, required=True)
    return result
def main(argv: Iterable[str] | None=None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.self_test:
            self_test(); return 0
        if args.command == 'run': return run(args)
        if args.command == 'status': return status(args.run_dir)
        parser().print_help(); return 2
    except (RunnerError, OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(f'run_jobs error: {exc}', file=sys.stderr); return 1
if __name__ == '__main__':
    raise SystemExit(main())
