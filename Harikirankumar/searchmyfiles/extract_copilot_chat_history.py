from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class ChatTurn:
    session_id: str
    source_file: str
    scope: str
    created_at: str | None
    timestamp: str | None
    responder: str | None
    model_id: str | None
    agent_id: str | None
    workspace_hint: str | None
    prompt: str
    response: str


def iso_from_epoch_ms(value: Any) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return None


def vscode_user_dir() -> Path:
    appdata = os.environ.get('APPDATA')
    if not appdata:
        raise RuntimeError('APPDATA is not set.')
    path = Path(appdata) / 'Code' / 'User'
    if not path.exists():
        raise RuntimeError(f'VS Code user directory not found: {path}')
    return path


def ensure_list_size(items: list[Any], index: int) -> None:
    while len(items) <= index:
        items.append(None)


def set_at_path(root: Any, path: list[Any], value: Any) -> Any:
    if not path:
        return value

    current = root
    for i, part in enumerate(path[:-1]):
        nxt = path[i + 1]
        if isinstance(part, int):
            if not isinstance(current, list):
                raise TypeError(f'Expected list at {path[:i]}, got {type(current).__name__}')
            ensure_list_size(current, part)
            if current[part] is None:
                current[part] = [] if isinstance(nxt, int) else {}
            current = current[part]
        else:
            if not isinstance(current, dict):
                raise TypeError(f'Expected dict at {path[:i]}, got {type(current).__name__}')
            if part not in current or current[part] is None:
                current[part] = [] if isinstance(nxt, int) else {}
            current = current[part]

    last = path[-1]
    if isinstance(last, int):
        if not isinstance(current, list):
            raise TypeError(f'Expected list at parent of {path}, got {type(current).__name__}')
        ensure_list_size(current, last)
        current[last] = value
    else:
        if not isinstance(current, dict):
            raise TypeError(f'Expected dict at parent of {path}, got {type(current).__name__}')
        current[last] = value
    return root


def get_at_path(root: Any, path: list[Any], create: bool = False) -> Any:
    current = root
    for i, part in enumerate(path):
        nxt = path[i + 1] if i + 1 < len(path) else None
        if isinstance(part, int):
            if not isinstance(current, list):
                if not create:
                    return None
                raise TypeError(f'Expected list at {path[:i]}, got {type(current).__name__}')
            ensure_list_size(current, part)
            if current[part] is None and create:
                current[part] = [] if isinstance(nxt, int) else {}
            current = current[part]
        else:
            if not isinstance(current, dict):
                if not create:
                    return None
                raise TypeError(f'Expected dict at {path[:i]}, got {type(current).__name__}')
            if part not in current or current[part] is None:
                if not create:
                    return None
                current[part] = [] if isinstance(nxt, int) else {}
            current = current[part]
    return current


def insert_many(root: Any, path: list[Any], values: list[Any], index: int | None) -> Any:
    arr = get_at_path(root, path, create=True)
    if arr is None:
        arr = []
        root = set_at_path(root, path, arr)
    if not isinstance(arr, list):
        arr = []
        root = set_at_path(root, path, arr)
    insert_index = len(arr) if index is None else index
    if insert_index < 0:
        insert_index = 0
    if insert_index > len(arr):
        insert_index = len(arr)
    arr[insert_index:insert_index] = values
    return root


def replay_session_file(path: Path) -> dict[str, Any] | None:
    root: dict[str, Any] | None = None
    with path.open('r', encoding='utf-8') as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            kind = entry.get('kind')
            if kind == 0:
                root = deepcopy(entry.get('v'))
                continue

            if root is None:
                continue

            key_path = entry.get('k', [])
            if kind == 1:
                root = set_at_path(root, key_path, deepcopy(entry.get('v')))
            elif kind == 2:
                values = entry.get('v')
                if isinstance(values, list):
                    root = insert_many(root, key_path, deepcopy(values), entry.get('i'))
                else:
                    root = set_at_path(root, key_path, deepcopy(values))

    return root


def extract_prompt(request: dict[str, Any]) -> str:
    message = request.get('message')
    if isinstance(message, dict):
        text = message.get('text')
        if isinstance(text, str) and text.strip():
            return text.strip()
        parts = message.get('parts')
        if isinstance(parts, list):
            chunks = [part.get('text', '') for part in parts if isinstance(part, dict)]
            joined = ''.join(chunks).strip()
            if joined:
                return joined
    return ''


VISIBLE_RESPONSE_KINDS = {
    None,
    'markdownContent',
    'warning',
    'progressMessage',
}

SKIP_RESPONSE_KINDS = {
    'thinking',
    'toolInvocationSerialized',
    'workspaceEdit',
    'mcpServersStarting',
    'confirmation',
    'inlineReference',
}


def extract_response(request: dict[str, Any]) -> str:
    response = request.get('response')
    if not isinstance(response, list):
        return ''

    chunks: list[str] = []
    for item in response:
        if not isinstance(item, dict):
            continue

        kind = item.get('kind')
        if kind in SKIP_RESPONSE_KINDS:
            continue

        value = item.get('value')
        if isinstance(value, str):
            text = value.strip()
            if text:
                chunks.append(text)
            continue

        if kind in VISIBLE_RESPONSE_KINDS:
            nested_value = item.get('value')
            if isinstance(nested_value, dict):
                nested_text = nested_value.get('value')
                if isinstance(nested_text, str) and nested_text.strip():
                    chunks.append(nested_text.strip())

    return '\n\n'.join(chunks).strip()


def guess_workspace_hint(request: dict[str, Any], source_file: Path) -> str | None:
    refs = request.get('contentReferences')
    if isinstance(refs, list):
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            reference = ref.get('reference')
            if isinstance(reference, dict):
                fs_path = reference.get('fsPath')
                if isinstance(fs_path, str) and fs_path:
                    return str(Path(fs_path).parent)
    parts = source_file.parts
    if 'workspaceStorage' in parts:
        idx = parts.index('workspaceStorage')
        if idx + 1 < len(parts):
            return f'workspaceStorage/{parts[idx + 1]}'
    return 'empty-window'


def collect_chat_turns() -> list[ChatTurn]:
    user_dir = vscode_user_dir()
    patterns = [
        user_dir / 'globalStorage' / 'emptyWindowChatSessions',
        user_dir / 'workspaceStorage',
    ]

    files: list[Path] = []
    empty_dir = patterns[0]
    if empty_dir.exists():
        files.extend(sorted(empty_dir.glob('*.jsonl')))

    workspace_root = patterns[1]
    if workspace_root.exists():
        files.extend(sorted(workspace_root.glob('*/chatSessions/*.jsonl')))

    turns: list[ChatTurn] = []
    for path in files:
        session = replay_session_file(path)
        if not isinstance(session, dict):
            continue

        requests = session.get('requests')
        if not isinstance(requests, list):
            continue

        source_scope = 'emptyWindow' if 'emptyWindowChatSessions' in path.parts else 'workspace'
        created_at = iso_from_epoch_ms(session.get('creationDate'))
        responder = session.get('responderUsername')
        session_id = session.get('sessionId') or path.stem

        for request in requests:
            if not isinstance(request, dict):
                continue
            prompt = extract_prompt(request)
            response = extract_response(request)
            if not prompt and not response:
                continue
            turns.append(
                ChatTurn(
                    session_id=str(session_id),
                    source_file=str(path),
                    scope=source_scope,
                    created_at=created_at,
                    timestamp=iso_from_epoch_ms(request.get('timestamp')),
                    responder=responder,
                    model_id=request.get('modelId'),
                    agent_id=(request.get('agent') or {}).get('id') if isinstance(request.get('agent'), dict) else None,
                    workspace_hint=guess_workspace_hint(request, path),
                    prompt=prompt,
                    response=response,
                )
            )

    turns.sort(key=lambda turn: (turn.timestamp or '', turn.session_id))
    return turns


def write_outputs(turns: list[ChatTurn], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / 'copilot_chat_export.json'
    md_path = output_dir / 'copilot_chat_export.md'

    json_path.write_text(json.dumps([asdict(turn) for turn in turns], indent=2, ensure_ascii=False), encoding='utf-8')

    md_lines = ['# Copilot Chat Export', '']
    for index, turn in enumerate(turns, start=1):
        md_lines.extend([
            f'## Chat {index}',
            '',
            f'- Timestamp: {turn.timestamp or "(unknown)"}',
            f'- Session: {turn.session_id}',
            f'- Scope: {turn.scope}',
            f'- Workspace hint: {turn.workspace_hint or "(unknown)"}',
            f'- Model: {turn.model_id or "(unknown)"}',
            f'- Agent: {turn.agent_id or "(unknown)"}',
            '',
            '### Prompt',
            '',
            turn.prompt or '(empty)',
            '',
            '### Response',
            '',
            turn.response or '(empty)',
            '',
            '---',
            '',
        ])

    md_path.write_text('\n'.join(md_lines), encoding='utf-8')
    return json_path, md_path


def main() -> int:
    output_dir = Path.cwd() / 'copilot_chat_export'
    turns = collect_chat_turns()
    json_path, md_path = write_outputs(turns, output_dir)
    print(f'Exported {len(turns)} chat turns')
    print(f'JSON: {json_path}')
    print(f'Markdown: {md_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
