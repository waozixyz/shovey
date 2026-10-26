"""Rules for authored starting boards, before they are played or published."""


def validate_star_spacing(board, label='Level'):
    """Star blocks must meet through a push, never share an edge at the start."""
    for at, kind in enumerate(board[:240]):
        if kind != 19:
            continue
        neighbors = ([at + 1] if at % 12 < 11 else []) + ([at + 12] if at < 228 else [])
        if any(board[other] == 19 for other in neighbors):
            raise ValueError(f'{label}: separate touching star blocks before starting the level')
