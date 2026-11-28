#!/usr/bin/env python3
"""Sign and verify the standalone Shovey Android downloads: the normal APK
(also the F-Droid edition), which holds no Google library, and the Google
Play edition's APK and bundle, the only ones with Play Billing."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build_tools():
    sdk = Path(os.environ.get('ANDROID_SDK_ROOT') or os.environ.get('ANDROID_HOME') or Path.home() / 'Android/Sdk')
    folders = sorted((sdk / 'build-tools').glob('*'), key=lambda p: tuple(int(n) for n in re.findall(r'\d+', p.name)))
    return next(p for p in reversed(folders) if all((p / name).is_file() for name in ('aapt', 'apksigner', 'zipalign')))


def verify(apk, version, tools, edition='direct', device_abi=None):
    assert re.fullmatch(r'\d+\.\d+\.\d+', version), 'A numeric release version is required'
    changelog = (ROOT / 'src/CHANGELOG.md').read_text()
    assert re.search(r'^## \[' + re.escape(version) + r'\] - ', changelog, re.M), 'Release version is absent from the changelog'
    badging = subprocess.check_output([str(tools / 'aapt'), 'dump', 'badging', str(apk)], text=True)
    package = re.search(r"^package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", badging, re.M)
    assert package and package[1] == 'xyz.waozi.shovey' and package[3] == version, 'APK identity or version differs'
    assert 'application-debuggable' not in badging, 'A debug build cannot be published'
    google_play = edition == 'gplay'
    assert ("'com.android.vending.BILLING'" in badging) == google_play, \
        'Only the Google Play edition may ask for Play Billing'
    certificate = subprocess.check_output(['openssl', 'x509', '-in', str(ROOT / 'packaging/android/certificate.pem'), '-outform', 'DER'])
    expected = hashlib.sha256(certificate).hexdigest()
    signature = subprocess.check_output([str(tools / 'apksigner'), 'verify', '--verbose', '--print-certs', str(apk)], text=True)
    actual = re.findall(r'^(?:Signer #\d+|V[\d.]+ Signer:) certificate SHA-256 digest: ([0-9a-f]+)$', signature, re.M)
    assert 'Number of signers: 1' in signature and set(actual) == {expected}, 'APK signer differs from the preserved Shovey release certificate'
    subprocess.run([str(tools / 'zipalign'), '-c', '-P', '16', '4', str(apk)], check=True, capture_output=True)
    with zipfile.ZipFile(apk) as archive:
        abis = sorted(p.split('/')[1] for p in archive.namelist() if re.fullmatch(r'lib/[^/]+/libmain\.so', p))
        expected_abis = [device_abi] if device_abi else ['arm64-v8a', 'armeabi-v7a']
        assert abis == expected_abis, 'APK architectures differ from the requested build'
        metadata = json.loads(archive.read('assets/shovey.json'))
        payload = archive.read('assets/shovey.zx')
        assert metadata['id'] == 'arcade.shovey-player' and metadata['version'] == version
        assert metadata['sha256'] == hashlib.sha256(payload).hexdigest(), 'Embedded game collection differs from its receipt'
        dex = b''.join(archive.read(name) for name in archive.namelist() if re.fullmatch(r'classes\d*\.dex', name))
        for marker in (b'Lorg/kryonlabs/play/PlayBilling;', b'Lcom/android/billingclient/'):
            assert (marker in dex) == google_play, 'Only the Google Play edition may include Play Billing'
    return dict(version=version, version_code=int(package[2]), package=package[1], abis=abis, edition=edition,
                sha256=hashlib.sha256(apk.read_bytes()).hexdigest(), certificate_sha256=expected,
                payload_sha256=metadata['sha256'], bytes=apk.stat().st_size)


def verify_bundle(bundle, version, bundletool):
    subprocess.run(['java', '-jar', str(bundletool), 'validate', '--bundle=' + str(bundle)],
                   check=True, stdout=subprocess.DEVNULL)
    xml = subprocess.check_output(['java', '-jar', str(bundletool), 'dump', 'manifest',
                                   '--bundle=' + str(bundle)], text=True)
    manifest = ET.fromstring(xml)
    android = '{http://schemas.android.com/apk/res/android}'
    assert manifest.get('package') == 'xyz.waozi.shovey'
    assert manifest.get(android + 'versionName') == version
    assert int(manifest.find('uses-sdk').get(android + 'targetSdkVersion')) >= 36
    signed = subprocess.check_output(['jarsigner', '-verify', str(bundle)], text=True,
                                     env=dict(os.environ, LC_ALL='C'))
    assert 'jar verified.' in signed, 'The Play bundle must be signed'
    certificate = subprocess.check_output(['openssl', 'x509', '-in', str(ROOT / 'packaging/android/certificate.pem'), '-outform', 'DER'])
    expected = hashlib.sha256(certificate).hexdigest()
    certificates = subprocess.check_output(['keytool', '-printcert', '-jarfile', str(bundle)], text=True,
                                          env=dict(os.environ, LC_ALL='C'))
    found = re.findall(r'SHA256:\s*([A-Fa-f0-9:]+)', certificates)
    assert found and {item.replace(':', '').lower() for item in found} == {expected}, 'Play bundle signer differs from Shovey release key'
    with zipfile.ZipFile(bundle) as archive:
        metadata = json.loads(archive.read('base/assets/shovey.json'))
        assert metadata['version'] == version and metadata['id'] == 'arcade.shovey-player'
        assert metadata['sha256'] == hashlib.sha256(archive.read('base/assets/shovey.zx')).hexdigest()
        abis = {name.split('/')[2] for name in archive.namelist() if name.startswith('base/lib/') and name.endswith('.so')}
        assert abis == {'arm64-v8a', 'armeabi-v7a'}
        dex = b''.join(archive.read(name) for name in archive.namelist() if name.startswith('base/dex/'))
        assert b'Lorg/kryonlabs/play/PlayBilling;' in dex, 'The Google Play edition must include Play Billing'
        verify_root = ROOT / 'build/play-verify'
        verify_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=verify_root) as directory:
            for name in archive.namelist():
                if not name.startswith('base/lib/arm64-v8a/') or not name.endswith('.so'): continue
                library = Path(directory) / Path(name).name
                library.write_bytes(archive.read(name))
                headers = subprocess.check_output(['readelf', '-lW', str(library)], text=True)
                loads = [line.split() for line in headers.splitlines() if line.strip().startswith('LOAD ')]
                assert loads and all(int(parts[-1], 16) >= 16384 for parts in loads), 'Native library needs 16 KB page alignment'
    return dict(version=version, version_code=int(manifest.get(android + 'versionCode')),
                package='xyz.waozi.shovey', certificate_sha256=expected,
                sha256=hashlib.sha256(bundle.read_bytes()).hexdigest())


def github(path):
    return json.loads(subprocess.check_output(['gh', 'api', 'repos/waozixyz/shovey/' + path], text=True))


def reuse_release(apk, version, revision, tools):
    """Reuse the published normal APK as F-Droid's identical signed reference."""
    if not re.fullmatch(r'\d+\.\d+\.\d+', version) or not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Reuse requires a numeric release version and full source commit')
    tag = 'v' + version
    release = github('releases/tags/' + tag)
    if release['draft'] or release['tag_name'] != tag:
        raise ValueError('Reuse requires the published release')
    if github('commits/' + tag)['sha'] != revision:
        raise ValueError('Published release belongs to another source commit')
    name = f'shovey-v{version}.apk'
    assets = [asset for asset in release['assets'] if asset['name'] == name]
    if len(assets) != 1 or not re.fullmatch(r'sha256:[0-9a-f]{64}', assets[0].get('digest') or ''):
        raise ValueError('Published normal APK needs one recorded SHA-256 digest')
    expected = json.loads((ROOT / 'version.json').read_text())
    if expected['version'] != version:
        raise ValueError('Requested APK differs from the checked-out release version')
    apk.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=apk.parent) as directory:
        subprocess.run(['gh', 'release', 'download', tag, '--repo', 'waozixyz/shovey',
                        '--pattern', name, '--dir', directory], check=True)
        source = Path(directory) / name
        with source.open('rb') as stream:
            actual = 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != assets[0]['digest']:
            raise ValueError('Downloaded APK differs from the published digest')
        result = verify(source, version, tools)
        if result['version_code'] != expected['version_code']:
            raise ValueError('Published APK version code differs from this release')
        if github('commits/' + tag)['sha'] != revision:
            raise ValueError('Release tag changed while downloading the APK')
        source.replace(apk)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('sign', 'verify', 'reuse'))
    parser.add_argument('apk', type=Path)
    parser.add_argument('--version', required=True)
    parser.add_argument('--revision', help='Full published source commit, required for reuse')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/android/shovey.apk')
    parser.add_argument('--keystore', type=Path, default=ROOT / 'backup/android-signing/shovey-release.p12')
    parser.add_argument('--password-file', type=Path, default=ROOT / 'backup/android-signing/password')
    parser.add_argument('--alias', default='shovey')
    parser.add_argument('--device-abi', choices=('arm64-v8a', 'armeabi-v7a'),
                        help='Verify a local device repair; published releases still require both ARM architectures')
    parser.add_argument('--bundletool', type=Path, help='Google bundletool JAR, required for .aab files')
    parser.add_argument('--edition', choices=('direct', 'gplay'), default='direct',
                        help='direct: the normal and F-Droid APK; gplay: the Google Play APK')
    args = parser.parse_args()
    tools = build_tools()
    if args.action == 'reuse':
        if not args.revision or args.edition != 'direct' or args.device_abi:
            parser.error('reuse requires --revision and the normal dual-ABI release APK')
        result = reuse_release(args.apk.resolve(), args.version, args.revision, tools)
        print(f'Shovey {args.version}: reused verified signed APK {result["sha256"]}')
        return
    apk = args.apk.resolve(strict=True)
    if apk.suffix == '.aab':
        assert not args.device_abi, 'Device repairs use APKs'
        assert args.bundletool, '--bundletool is required to verify a Play bundle'
        output = apk
        if args.action == 'sign':
            output = args.output.resolve()
            assert output.suffix == '.aab', 'Use an .aab output filename'
            output.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(['jarsigner', '-keystore', str(args.keystore.resolve(strict=True)),
                            '-storepass:file', str(args.password_file.resolve(strict=True)),
                            '-signedjar', str(output), str(apk), args.alias], check=True)
        result = verify_bundle(output, args.version, args.bundletool.resolve(strict=True))
        records = ROOT / 'backup/android-release'
        records.mkdir(parents=True, exist_ok=True)
        (records / 'play-verification.json').write_text(json.dumps(result, indent=2) + '\n')
        print(f'Shovey {args.version}: signed Play bundle, package, native alignment and embedded games verified')
        return
    if args.action == 'sign':
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        aligned = output.with_name('aligned-unsigned.apk')
        temporary = output.with_name('shovey.new.apk')
        # Keep an aligned build's bytes, which F-Droid reproduces from source.
        if subprocess.run([str(tools / 'zipalign'), '-c', '-P', '16', '4', str(apk)], capture_output=True).returncode == 0:
            shutil.copyfile(apk, aligned)
        else:
            subprocess.run([str(tools / 'zipalign'), '-P', '16', '-f', '4', str(apk), str(aligned)], check=True)
        try:
            # apksigner re-aligns entries with its own padding unless told to
            # keep them; kept, F-Droid's rebuild takes this signature as is.
            # Downloads carry the APK's embedded signatures, not an incremental
            # install's separate v4 .idsig file.
            subprocess.run([str(tools / 'apksigner'), 'sign', '--alignment-preserved', '--v4-signing-enabled', 'false',
                            '--ks', str(args.keystore.resolve(strict=True)),
                            '--ks-key-alias', args.alias, '--ks-pass', 'file:' + str(args.password_file.resolve(strict=True)),
                            '--out', str(temporary), str(aligned)], check=True)
        finally:
            # Only the signed APK belongs beside the output.
            aligned.unlink(missing_ok=True)
            temporary.with_suffix('.apk.idsig').unlink(missing_ok=True)
        result = verify(temporary, args.version, tools, args.edition, args.device_abi)
        temporary.replace(output)
        result['apk'] = str(output)
        records = ROOT / 'backup/android-release'
        records.mkdir(parents=True, exist_ok=True)
        name = 'gplay-verification.json' if args.edition == 'gplay' else 'verification.json'
        (records / name).write_text(json.dumps(result, indent=2) + '\n')
    else:
        verify(apk, args.version, tools, args.edition, args.device_abi)
    print(f'Shovey {args.version}: release APK identity, signer, alignment and embedded games verified')


if __name__ == '__main__':
    main()
