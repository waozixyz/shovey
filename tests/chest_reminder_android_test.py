"""Verify Android reminder staging and optional built APK receiver/JNI contents."""
import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ANDROID = '{http://schemas.android.com/apk/res/android}'
RECEIVER = 'org.kryonlabs.notifications.NotificationReceiver'
PERMISSIONS = {'android.permission.POST_NOTIFICATIONS', 'android.permission.RECEIVE_BOOT_COMPLETED'}
ACTIONS = {'android.intent.action.BOOT_COMPLETED', 'android.intent.action.TIME_SET',
           'android.intent.action.TIMEZONE_CHANGED', 'android.intent.action.MY_PACKAGE_REPLACED'}


def check_receiver(manifest):
    assert PERMISSIONS <= {item.get(ANDROID + 'name') for item in manifest.findall('uses-permission')}
    application = manifest.find('application')
    receivers = [item for item in application.findall('receiver') if item.get(ANDROID + 'name') == RECEIVER]
    assert len(receivers) == 1
    assert receivers[0].get(ANDROID + 'exported') == 'false'
    assert ACTIONS == {item.get(ANDROID + 'name') for item in receivers[0].findall('intent-filter/action')}
    return application


def check_manifest(path):
    application = check_receiver(ET.parse(path).getroot())
    assert application.get(ANDROID + 'allowBackup') == 'true'
    assert application.get(ANDROID + 'fullBackupContent') == '@xml/backup_rules'
    assert application.get(ANDROID + 'dataExtractionRules') == '@xml/data_extraction_rules'
    aliases = {item.get(ANDROID + 'name'): item.get(ANDROID + 'targetActivity') for item in application.findall('activity-alias')}
    assert aliases['xyz.waozi.arcade.ArcadeActivity'] == '.ShoveyActivity'


def check_apk(apk, apkanalyzer, work):
    manifest = subprocess.check_output([str(apkanalyzer), 'manifest', 'print', str(apk)], text=True)
    check_receiver(ET.fromstring(manifest))
    # Defined-only distinguishes an actual packaged receiver from a reference.
    process = subprocess.Popen([str(apkanalyzer), 'dex', 'packages', '--defined-only', str(apk)],
                               stdout=subprocess.PIPE, text=True)
    found = False
    for line in process.stdout:
        if line.split() and line.split()[-1] == RECEIVER:
            found = True
    assert process.wait() == 0
    assert found, f'{apk}: canonical receiver class is missing'
    required = {'Java_org_kryonlabs_notifications_NotificationReceiver_receive',
                'Java_org_kryonlabs_notifications_NotificationReceiver_requestPermission',
                'JNI_OnLoad', 'ANativeActivity_onCreate'}
    private = {'ScheduleDailyNotificationHost', 'CancelDailyNotificationHost',
               'NotificationAppOpenedHost', 'NotificationAllowedHost', 'NotificationRequestHost'}
    by_abi = {}
    with tempfile.TemporaryDirectory(dir=work) as directory, zipfile.ZipFile(apk) as archive:
        target = Path(directory) / 'library.so'
        for entry in archive.infolist():
            parts = entry.filename.split('/')
            if len(parts) != 3 or parts[0] != 'lib' or not parts[2].endswith('.so'):
                continue
            with archive.open(entry) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)
            process = subprocess.Popen(['readelf', '--dyn-syms', '--wide', str(target)],
                                       stdout=subprocess.PIPE, text=True)
            symbols = by_abi.setdefault(parts[1], set())
            for line in process.stdout:
                fields = line.split()
                if len(fields) >= 8 and fields[6] != 'UND':
                    symbol = fields[-1]
                    assert not any(symbol.endswith(name) for name in private), f'{apk}: private host export {symbol}'
                    if symbol in required:
                        symbols.add(symbol)
            assert process.wait() == 0
    assert {'arm64-v8a', 'armeabi-v7a'} <= by_abi.keys(), f'{apk}: missing production ABI'
    for abi, symbols in by_abi.items():
        assert required <= symbols, f'{apk} {abi}: missing notification exports {required - symbols}'
    print(f'{apk}: merged manifest, defined receiver, JNI registration and private host symbols in both ABIs passed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kryon', type=Path)
    parser.add_argument('--apk', type=Path, action='append', default=[])
    parser.add_argument('--apkanalyzer', type=Path)
    args = parser.parse_args()
    if args.apk and not args.apkanalyzer:
        parser.error('--apkanalyzer is required with --apk')
    kryon = args.kryon.resolve()
    for name in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER'):
        os.environ.pop(name, None)
    os.environ['YUE_DESKTOP_RECOVERY'] = '0'
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('shovey_player_notification_test', ROOT / 'scripts/player.py')
    player = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(player)
    work = ROOT / 'work/chest-reminder-android-test'
    subprocess.run(['git', 'check-ignore', '-q', str(work)], cwd=ROOT, check=True)
    work.mkdir(parents=True, exist_ok=True)
    canonical_receiver = kryon / 'templates/droid/droid/app/src/main/java/org/kryonlabs/notifications/NotificationReceiver.java'
    with tempfile.TemporaryDirectory(dir=work) as directory:
        fixture = Path(directory)
        shutil.copytree(ROOT / 'packaging/android', fixture / 'packaging/android')
        player.ROOT = fixture
        droid = player.prepare_android_project(kryon)
        manifest = droid / 'app/src/main/AndroidManifest.xml'
        receiver = droid / 'app/src/main/java/org/kryonlabs/notifications/NotificationReceiver.java'
        check_manifest(manifest)
        assert receiver.read_bytes() == canonical_receiver.read_bytes()
        # Repeated release preparation must refresh a stale generated bridge.
        receiver.write_text('// stale generated receiver\n')
        player.prepare_android_project(kryon)
        check_manifest(manifest)
        assert receiver.read_bytes() == canonical_receiver.read_bytes()
        assert not (droid / 'app/src/gplay').exists()
    print('Android reminder release staging: permissions, private receiver/actions, canonical bridge refresh and backup/launcher preservation passed')
    for apk in args.apk:
        check_apk(apk.resolve(), args.apkanalyzer.resolve(), work)


if __name__ == '__main__':
    main()
