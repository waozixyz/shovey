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


def start_map_destination(driver, level=1):
    assert_fullscreen_map(driver)
    driver.press(key=33000 + level, role='button')
    driver.press(key=20122, role='button')
