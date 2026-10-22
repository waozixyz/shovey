#!/usr/bin/env python3
"""Sign and verify the standalone Shovey Android download."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build_tools():
    sdk = Path(os.environ.get('ANDROID_SDK_ROOT') or os.environ.get('ANDROID_HOME') or Path.home() / 'Android/Sdk')
    folders = sorted((sdk / 'build-tools').glob('*'), key=lambda p: tuple(int(n) for n in re.findall(r'\d+', p.name)))
    return next(p for p in reversed(folders) if all((p / name).is_file() for name in ('aapt', 'apksigner', 'zipalign')))


def verify(apk, version, tools):
    assert re.fullmatch(r'\d+\.\d+\.\d+', version), 'A numeric release version is required'
    changelog = (ROOT / 'src/CHANGELOG.md').read_text()
    assert re.search(r'^## \[' + re.escape(version) + r'\] - ', changelog, re.M), 'Release version is absent from the changelog'
    badging = subprocess.check_output([str(tools / 'aapt'), 'dump', 'badging', str(apk)], text=True)
    package = re.search(r"^package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", badging, re.M)
    assert package and package[1] == 'xyz.waozi.shovey' and package[3] == version, 'APK identity or version differs'
    assert 'application-debuggable' not in badging, 'A debug build cannot be published'
    certificate = subprocess.check_output(['openssl', 'x509', '-in', str(ROOT / 'packaging/android/certificate.pem'), '-outform', 'DER'])
    expected = hashlib.sha256(certificate).hexdigest()
    signature = subprocess.check_output([str(tools / 'apksigner'), 'verify', '--verbose', '--print-certs', str(apk)], text=True)
    actual = re.findall(r'^(?:Signer #\d+|V[\d.]+ Signer:) certificate SHA-256 digest: ([0-9a-f]+)$', signature, re.M)
    assert 'Number of signers: 1' in signature and set(actual) == {expected}, 'APK signer differs from the preserved Shovey release certificate'
    subprocess.run([str(tools / 'zipalign'), '-c', '-P', '16', '4', str(apk)], check=True, capture_output=True)
    with zipfile.ZipFile(apk) as archive:
        abis = sorted(p.split('/')[1] for p in archive.namelist() if re.fullmatch(r'lib/[^/]+/libmain\.so', p))
        assert abis == ['arm64-v8a', 'armeabi-v7a'], 'Both supported ARM architectures must be present'
        metadata = json.loads(archive.read('assets/arcade.json'))
        payload = archive.read('assets/arcade.zib')
        assert metadata['id'] == 'arcade.shovey-player' and metadata['version'] == version
        assert metadata['sha256'] == hashlib.sha256(payload).hexdigest(), 'Embedded game collection differs from its receipt'
    return dict(version=version, version_code=int(package[2]), package=package[1], abis=abis,
                sha256=hashlib.sha256(apk.read_bytes()).hexdigest(), certificate_sha256=expected,
                payload_sha256=metadata['sha256'], bytes=apk.stat().st_size)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('sign', 'verify'))
    parser.add_argument('apk', type=Path)
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/android/shovey.apk')
    parser.add_argument('--keystore', type=Path, default=ROOT / 'backup/android-signing/shovey-release.p12')
    parser.add_argument('--password-file', type=Path, default=ROOT / 'backup/android-signing/password')
    parser.add_argument('--alias', default='shovey')
    args = parser.parse_args()
    tools = build_tools()
    apk = args.apk.resolve(strict=True)
    if args.action == 'sign':
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        aligned = output.with_name('aligned-unsigned.apk')
        temporary = output.with_name('shovey.new.apk')
        subprocess.run([str(tools / 'zipalign'), '-P', '16', '-f', '4', str(apk), str(aligned)], check=True)
        subprocess.run([str(tools / 'apksigner'), 'sign', '--ks', str(args.keystore.resolve(strict=True)),
                        '--ks-key-alias', args.alias, '--ks-pass', 'file:' + str(args.password_file.resolve(strict=True)),
                        '--out', str(temporary), str(aligned)], check=True)
        result = verify(temporary, args.version, tools)
        temporary.replace(output)
        result['apk'] = str(output)
        records = ROOT / 'backup/android-release'
        records.mkdir(parents=True, exist_ok=True)
        (records / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
    else:
        verify(apk, args.version, tools)
    print(f'Shovey {args.version}: release APK identity, signer, alignment and embedded games verified')


if __name__ == '__main__':
    main()
