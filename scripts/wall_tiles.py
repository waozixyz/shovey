"""Visual wall connections shared by the atlas builder and level previews.

Low bits join left/up/right/down. High bits mark a missing diagonal when
both adjacent sides join, giving the 47 valid outside/inside corner shapes.
These names extend the artwork only; board cell IDs stay unchanged.
"""
WALL_KINDS = (12, 14, 62, 63, 76, 95, 96, 97, 98, 127, 128, 129, 130, 164)
CORNERS = ((16, 1, 2), (32, 2, 4), (64, 4, 8), (128, 8, 1))
WALL_MASKS = tuple(mask for mask in range(256)
                   if all(not mask & corner or mask & a and mask & b
                          for corner, a, b in CORNERS))
assert len(WALL_MASKS) == 47


def wall_mask(at, walls, landscape=False):
    def neighbor(pos, direction):
        if pos < 0:
            return -1
        x, y = pos % 12, pos // 12
        dx, dy = ((-1, 0), (0, -1), (1, 0), (0, 1))[direction]
        return pos + dx + dy * 12 if 0 <= x + dx < 12 and 0 <= y + dy < 20 else -1

    directions = tuple((side + int(landscape)) % 4 for side in range(4))
    sides = [neighbor(at, direction) for direction in directions]
    joined = [pos >= 0 and walls[pos] in WALL_KINDS for pos in sides]
    mask = sum(1 << side for side in range(4) if joined[side])
    for side, (corner, _, _) in enumerate(CORNERS):
        other = (side + 1) % 4
        diagonal = neighbor(sides[side], directions[other])
        if joined[side] and joined[other] and (diagonal < 0 or walls[diagonal] not in WALL_KINDS):
            mask |= corner
    return mask


def wall_name(kind, at, walls, landscape=False):
    return f'wall-{kind}-{wall_mask(at, walls, landscape)}' if kind in WALL_KINDS else f'tile-{kind}'


def pit_floor(at, tiles):
    """Backing for old ball sockets that occupy their terrain slot."""
    for dx, dy in ((-1, 0), (0, -1), (1, 0), (0, 1)):
        x, y = at % 12 + dx, at // 12 + dy
        if 0 <= x < 12 and 0 <= y < 20:
            tile = tiles[y * 12 + x]
            if tile in {0, 60, 61, 77, 78, 99, 100, 101, 102, 103, 162, 163}:
                return tile
    return 0
