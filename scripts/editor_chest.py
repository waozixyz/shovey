#!/usr/bin/env python3
"""Save the private editor's proven 29a board, without publishing anything."""
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def save(root):
    drafts = root / 'backup/editor-drafts'
    request = (drafts / '178.chest-request').read_text().splitlines()
    if (len(request) != 3 or not re.fullmatch('[0-9a-f]{1440}', request[0]) or
            not re.fullmatch('[0-9a-f]{1440}', request[1]) or not re.fullmatch('[0123ft]+', request[2])):
        raise ValueError('Incomplete chest board or winning route')
    expected, board, route = request
    # Share the existing level-write mutex with the approval writer, without
    # altering approvals or invoking its publication queue.
    with (drafts / 'approval.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root / 'levels/approved.json'
        document = json.loads(path.read_text())
        entries = document.get('hidden_levels', [])
        matches = [entry for entry in entries if entry.get('name') == '29a']
        if len(matches) != 1:
            raise ValueError('Expected one hidden 29a entry')
        level = matches[0]
        current = ''.join(level['cells'] + level['tiles'] + level['decorations'])
        if current != expected:
            raise ValueError('29a changed after this editor loaded it; reopen before saving')
        for layer, name in enumerate(('cells', 'tiles', 'decorations')):
            start = layer * 480
            level[name] = [board[at:at + 24] for at in range(start, start + 480, 24)]
        level['solution'] = route
        text = json.dumps(document, indent=1, ensure_ascii=False) + '\n'
        with tempfile.NamedTemporaryFile('w', dir=path.parent, prefix='.chest-', delete=False) as file:
            temporary = Path(file.name)
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        try:
            temporary.chmod(path.stat().st_mode & 0o777)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    generator = root / 'tools/levels/levels.py'
    if generator.exists():
        # The saved document is already durable. Unrelated private campaign
        # work may delay generation; it must not turn this successful save
        # into a false failure. The normal build regenerates from this file.
        subprocess.run(['python3', str(generator), 'generate'], cwd=root, check=False)


if __name__ == '__main__':
    save(Path.cwd())
