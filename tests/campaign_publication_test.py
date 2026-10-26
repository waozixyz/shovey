"""A publication must match its approved source, publisher and winning routes."""
import copy
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('campaign_publisher', ROOT / 'scripts/publish-campaign.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


def main():
    config = json.loads((ROOT / 'levels/publication.json').read_text())
    approved = json.loads((ROOT / 'levels/approved.json').read_text())
    answer = dict(publication=dict(id=config['id'], format=config['format'], visibility='public',
                                   author=dict(public_id=config['author']), levels=len(approved['levels'])),
                  document=copy.deepcopy(approved))
    seen = []
    def winning(number, board, route):
        seen.append(number)
        return bool(board and route)
    publisher.verify_campaign(config, approved, answer, winning)
    assert seen == list(range(1, len(approved['levels']) + 1))
    for change in ('author', 'id', 'visibility', 'board', 'route'):
        wrong = copy.deepcopy(answer)
        if change == 'author': wrong['publication']['author']['public_id'] = '0' * 64
        elif change == 'id': wrong['publication']['id'] = '0' * 32
        elif change == 'visibility': wrong['publication']['visibility'] = 'private'
        elif change == 'board':
            board = wrong['document']['levels'][72]['cells']
            row = next(index for index, value in enumerate(board) if value != '00' * 12)
            board[row] = '00' * 12
        else: wrong['document']['levels'][73]['solution'] += '0'
        try:
            publisher.verify_campaign(config, approved, wrong, winning)
        except ValueError:
            pass
        else:
            raise AssertionError(f'Accepted changed {change}')
    try:
        publisher.verify_campaign(config, approved, answer, lambda *args: False)
    except ValueError:
        pass
    else:
        raise AssertionError('Accepted a losing route')
    print('Campaign publication: exact source, public publisher identity and every winning route required')


if __name__ == '__main__':
    main()
