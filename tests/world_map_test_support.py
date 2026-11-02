"""Private profiles and provenance for native map UI tests."""
import hashlib
import os
from pathlib import Path


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
