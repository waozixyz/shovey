#!/usr/bin/env python3
"""Durable, per-board publication requests; one worker builds the campaign."""
import argparse
import contextlib
import fcntl
import hashlib
import json
from pathlib import Path
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BUSY = {'building', 'checking', 'publishing', 'verifying'}
WAITING = {'queued', 'waiting'}


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix=path.name + '.', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(value)
    temporary.replace(path)


class Queue:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.state = self.root / 'backup/editor-drafts'
        self.state.mkdir(parents=True, exist_ok=True)
        self.path = self.state / 'publication-queue.json'

    @contextlib.contextmanager
    def transaction(self):
        with (self.state / 'publication-queue.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = json.loads(self.path.read_text()) if self.path.exists() else dict(schema=1, jobs=[], events=[])
            yield data
            atomic(self.path, json.dumps(data, indent=2) + '\n')
            latest = {}
            for job in data['jobs']:
                latest[job['level']] = job
            for level, job in latest.items():
                atomic(self.state / f'{level:03}.publication', json.dumps(job, separators=(',', ':')) + '\n')
            active = [j for j in latest.values() if j['state'] in BUSY]
            queued = [j for j in latest.values() if j['state'] in WAITING]
            failed = [j for j in latest.values() if j['state'] == 'failed']
            if active:
                message = (f"Level {active[0]['level']}: {active[0]['state']}" if len(active) == 1 else
                           f"{active[0]['state'].capitalize()} {len(active)} levels")
                if queued:
                    message += f' · {len(queued)} queued'
            elif queued:
                message = f'{len(queued)} queued'
            elif failed:
                message = f"Level {failed[-1]['level']}: update failed. Retry."
            else:
                message = 'Published' if latest else ''
                summary = self.state / 'update-all-summary.json'
                if latest and summary.exists():
                    retained = json.loads(summary.read_text()).get('unproven_boards', {})
                    unchanged = 0
                    for number, digest in retained.items():
                        draft = self.state / f'{int(number):03}.hex'
                        published = self.state / f'{int(number):03}.published'
                        if draft.exists() and hashlib.sha256(draft.read_text().strip().encode()).hexdigest() == digest and (
                                not published.exists() or published.read_text().strip() != draft.read_text().strip()):
                            unchanged += 1
                    if unchanged:
                        message += f' · {unchanged} drafts not updated'
            atomic(self.state / 'publish-status', message)

    @staticmethod
    def event(data, job, state, message=''):
        now = round(time.time(), 3)
        job.update(state=state, updated_at=now)
        data['events'].append(dict(at=now, id=job['id'], level=job['level'], state=state, message=message))
        data['events'] = data['events'][-400:]

    def enqueue(self, levels, available=None):
        """Coalesce repeated clicks; preserve requests for other levels."""
        with self.transaction() as data:
            for level in levels:
                board = level.get('board', '')
                if not board:
                    board = ''.join(''.join(level[name]) for name in ('cells', 'tiles', 'decorations'))
                number = level['number']
                digest = hashlib.sha256(board.encode()).hexdigest()
                identity = f'{number}:{digest}'
                current = next((j for j in reversed(data['jobs']) if j['level'] == number), None)
                if current and current['id'] == identity and current['state'] in BUSY | WAITING:
                    continue
                for old in data['jobs']:
                    if old['level'] == number and old['state'] in WAITING:
                        self.event(data, old, 'superseded')
                job = dict(id=identity, level=number, board=board, board_sha256=digest,
                           requested_at=round(time.time(), 3), attempt=(current or {}).get('attempt', 0),
                           step='', error='')
                data['jobs'].append(job)
                self.event(data, job, 'waiting' if available is not None and number > available else 'queued')

    def claim(self, boards):
        ids = []
        with self.transaction() as data:
            for job in data['jobs']:
                if job['state'] not in WAITING | BUSY or job['level'] > len(boards):
                    continue
                if boards[job['level'] - 1] != job['board']:
                    self.event(data, job, 'superseded')
                    continue
                job.update(attempt=job['attempt'] + (job['state'] in WAITING), error='', step='Preparing campaign')
                self.event(data, job, 'building')
                ids.append(job['id'])
        return ids

    def advance(self, ids, state, step):
        with self.transaction() as data:
            for job in data['jobs']:
                if job['id'] in ids and job['state'] in BUSY:
                    if job['state'] != state or job['step'] != step:
                        job['step'] = step
                        self.event(data, job, state, step)

    def fail(self, ids, error):
        with self.transaction() as data:
            for job in data['jobs']:
                if job['id'] in ids and job['state'] in BUSY:
                    job['error'] = str(error)[:1200]
                    self.event(data, job, 'failed', job['error'])

    def published(self, boards):
        with self.transaction() as data:
            for job in data['jobs']:
                if job['state'] in BUSY | WAITING | {'failed'} and job['level'] <= len(boards) and boards[job['level'] - 1] == job['board']:
                    job.update(step='Verified on server', error='')
                    self.event(data, job, 'published')

    def reconcile(self):
        """An idle OS lock proves that a former worker cannot still be running."""
        with (self.state / 'publish.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            with self.transaction() as data:
                for job in data['jobs']:
                    if job['state'] in BUSY:
                        job['error'] = 'Worker stopped. Retry this level.'
                        self.event(data, job, 'failed', job['error'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    queue = Queue()
    queue.reconcile()
    data = json.loads(queue.path.read_text())
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        latest = {j['level']: j for j in data['jobs']}
        for number, job in sorted(latest.items()):
            print(f"Level {number}: {job['state']} · attempt {job['attempt']} · {job['step']}")
            if job['error']:
                print('  ' + job['error'])
