"""Private profiles and provenance for native map UI tests."""
import hashlib
import os
from pathlib import Path
import time


def private_environment(profile, extra=None):
    assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
    assert os.environ.get('YUE_DESKTOP_RECOVERY') == '0'
    environment = os.environ.copy()
    for key in ('WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER',
                'GDK_DISPLAY', 'LISTEN_PID', 'LISTEN_FDS', 'LISTEN_FDNAMES', 'NOTIFY_SOCKET'):
        environment.pop(key, None)
    if extra:
        environment.update(extra)
    profile = Path(profile).resolve()
    for key, directory in {'HOME': 'home', 'XDG_CONFIG_HOME': 'config',
                           'XDG_CACHE_HOME': 'cache', 'XDG_DATA_HOME': 'data',
                           'XDG_STATE_HOME': 'state', 'XDG_RUNTIME_DIR': 'runtime',
                           'ENTITY_DATA': 'entity'}.items():
        path = profile / directory
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)
        environment[key] = str(path)
    environment.update(ARCADE_DATA=str(profile), LANG='en_US.UTF-8', YUE_DESKTOP_RECOVERY='0')
    return environment


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def assert_fullscreen_map(driver):
    """Map occupies the whole app viewport; Back is an accessible icon only."""
    driver.wait(key=20105, visible=True)
    driver.wait(key=20022, role='button', visible=True)
    nodes = driver.tree()
    screen = nodes[0]
    viewport = next(node for node in nodes if node.get('key') == 20105)
    assert viewport['x'] == 0 and viewport['y'] == 0, viewport
    assert (viewport['width'], viewport['height']) == (screen['width'], screen['height']), (viewport, screen)
    assert not any(node.get('key') in (20103, 20104) for node in nodes), 'Map chrome returned'
    assert not any(node.get('kind') == 'text' and node.get('label') in ('Levels', 'Continue', 'Back') for node in nodes)
    back = next(node for node in nodes if node.get('key') == 20022)
    assert back['label'] == 'Back' and back['width'] == 48 and back['height'] == 48, back
    return viewport


def enter_classic_map(driver):
    """Enter Classic through its own portable title when the host opens it."""
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        nodes = driver.tree()
        if any(n.get('key') == 20105 and n.get('visible') for n in nodes):
            return assert_fullscreen_map(driver)
        if any(n.get('key') == 20510 and n.get('visible') for n in nodes):
            driver.press(key=20510, role='button')
            return assert_fullscreen_map(driver)
        driver.wait_idle(frames=2, timeout=1)
    shown = [{k: n.get(k) for k in ('key', 'kind', 'label', 'detail')}
             for n in nodes if n.get('visible')][-16:]
    raise AssertionError(('Classic did not show its title or map', shown))


GAMEPLAY_CONTROLS = (20022, 20820, 20016, 20017, 20023)


def wait_gameplay(driver, timeout=30):
    """A level is open and takes input: its five controls and its board show.
    The game screen no longer names the level; the map names it before it
    starts."""
    for key in GAMEPLAY_CONTROLS:
        driver.wait(key=key, role='button', timeout=timeout)
    driver.wait(label='Wall', role='image', timeout=timeout)


def board_layout(driver):
    """Every picture of the open board but the player and the controls, to
    tell one board from another now that the game screen names none."""
    apart = {'Back', 'Collectibles', 'Restart', 'Hint', 'Mute', 'Shovey'}
    return sorted((node['label'], round(node['x']), round(node['y']))
                  for node in driver.find(role='image', visible=True) if node['label'] not in apart)


def wait_board_change(driver, before, timeout=20):
    """Another board replaced the one board_layout saw."""
    deadline = time.monotonic() + timeout
    while board_layout(driver) == before:
        assert time.monotonic() < deadline, 'The board did not change'
        time.sleep(.05)


def start_map_destination(driver, level=1):
    assert_fullscreen_map(driver)
    driver.press(key=33000 + level, role='button')
    driver.press(key=20122, role='button')
