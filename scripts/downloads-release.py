#!/usr/bin/env python3
"""Publish verified Downloads from Gitea; keep the existing isolated signing backend."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
GITEA = 'https://git.waozi.xyz'
REPO = 'waozi/shovey'
GITHUB = 'https://api.github.com/repos/waozixyz/shovey'
SIGNER = '3f687dd9aa7edd8c81b9d3ade255f0b620be7b9fd62783e5f8d7e7f7df658820'


def request(base, path, token, method='GET', data=None, missing=False):
    headers = {'Authorization': 'Bearer ' + token, 'User-Agent': 'Shovey-Downloads/1.0'}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers['Content-Type'] = 'application/json'
    try:
        with urllib.request.urlopen(urllib.request.Request(base + path, body, headers, method=method), timeout=60) as response:
            payload = response.read(4 * 1024 * 1024)
            return json.loads(payload) if payload else None
    except urllib.error.HTTPError as error:
        if missing and error.code == 404:
            return None
        raise RuntimeError(f'{method} {base}{path}: HTTP {error.code}; mutations are never retried automatically') from None


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def names(version):
    return {f'shovey-v{version}.apk', f'shovey-{version}-fdroid.apk',
            f'shovey-v{version}-gplay.apk', f'shovey-v{version}-linux-x86_64.tar.gz',
            f'shovey-v{version}-windows-x86_64.zip'}


def download(url, destination, token=None):
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
            # Signed object-storage redirects must never receive an API token.
            redirected.remove_header('Authorization')
            return redirected
    headers = {'User-Agent': 'Shovey-Downloads/1.0'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    with urllib.request.build_opener(Redirect()).open(urllib.request.Request(url, headers=headers), timeout=120) as source, destination.open('wb') as output:
        while block := source.read(1024 * 1024):
            output.write(block)


def extract(archive, destination, expected=None):
    with zipfile.ZipFile(archive) as zipped:
        for member in zipped.infolist():
            if member.is_dir():
                continue
            path = Path(member.filename)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('Unsafe artifact path')
            if expected is not None and path.name not in expected:
                raise ValueError(f'Unexpected download: {path.name}')
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise ValueError(f'Duplicate artifact: {path.name}')
            with zipped.open(member) as source, target.open('wb') as output:
                while block := source.read(1024 * 1024):
                    output.write(block)


def collect(run, token, output, version):
    artifacts = request(GITHUB, f'/actions/runs/{run}/artifacts?per_page=100', token)['artifacts']
    required = {'shovey-android', 'shovey-android-gplay', 'shovey-linux', 'shovey-windows', 'fdroid-unsigned'}
    selected = {a['name']: a for a in artifacts if a['name'] in required and not a['expired']}
    if selected.keys() != required:
        raise ValueError('Missing verified release artifacts')
    downloads = output / 'downloads'
    downloads.mkdir(parents=True, exist_ok=True)
    for name, artifact in selected.items():
        archive = output / (name + '.zip')
        download(artifact['archive_download_url'], archive, token)
        expected_digest = artifact.get('digest')
        if expected_digest and expected_digest != 'sha256:' + digest(archive):
            raise ValueError(f'Artifact digest mismatch: {name}')
        extract(archive, output / 'fdroid' if name == 'fdroid-unsigned' else downloads,
                None if name == 'fdroid-unsigned' else names(version))
    if {p.name for p in downloads.iterdir()} != names(version):
        raise ValueError('Release must contain exactly the five expected downloads')
    return downloads


def verify(downloads, output, version, code):
    for edition, filename in [('direct', f'shovey-v{version}.apk'),
                              ('fdroid', f'shovey-{version}-fdroid.apk'),
                              ('gplay', f'shovey-v{version}-gplay.apk')]:
        apk = downloads / filename
        signer = subprocess.check_output(['apksigner', 'verify', '--print-certs', str(apk)], text=True)
        if SIGNER not in signer:
            raise ValueError(f'Wrong signing key: {edition}')
        badging = subprocess.check_output(['aapt', 'dump', 'badging', str(apk)], text=True)
        if not re.search(r"^package: name='xyz\.waozi\.shovey' versionCode='" + str(code) + r"' versionName='" + re.escape(version) + "'", badging):
            raise ValueError(f'Wrong APK version: {edition}')
    if digest(downloads / f'shovey-v{version}.apk') != digest(downloads / f'shovey-{version}-fdroid.apk'):
        raise ValueError('Normal and F-Droid editions differ')
    rebuilt = list((output / 'fdroid' / 'tmp').glob('*.apk'))
    if len(rebuilt) != 1:
        raise ValueError('Expected one F-Droid source rebuild')
    subprocess.run(['apksigcopier', 'compare', '--unsigned', str(downloads / f'shovey-{version}-fdroid.apk'), str(rebuilt[0])], check=True)


def upload(release, path, token):
    boundary = 'shovey-release-upload'
    prefix = (f'--{boundary}\r\nContent-Disposition: form-data; name="attachment"; filename="{path.name}"\r\n'
              'Content-Type: application/octet-stream\r\n\r\n').encode()
    suffix = f'\r\n--{boundary}--\r\n'.encode()
    connection = http.client.HTTPSConnection('git.waozi.xyz', timeout=180)
    try:
        connection.putrequest('POST', f'/api/v1/repos/{REPO}/releases/{release}/assets?name={path.name}')
        connection.putheader('Authorization', 'Bearer ' + token)
        connection.putheader('User-Agent', 'Shovey-Downloads/1.0')
        connection.putheader('Content-Type', f'multipart/form-data; boundary={boundary}')
        connection.putheader('Content-Length', str(len(prefix) + path.stat().st_size + len(suffix)))
        connection.endheaders()
        connection.send(prefix)
        with path.open('rb') as stream:
            while block := stream.read(1024 * 1024):
                connection.send(block)
        connection.send(suffix)
        response = connection.getresponse()
        if response.status != 201:
            raise RuntimeError(f'Asset upload HTTP {response.status}; read release state before retrying')
        return json.loads(response.read(1024 * 1024))
    finally:
        connection.close()


def main():
    if os.environ.get('GITEA_ACTIONS') != 'true' or os.environ.get('GITHUB_SERVER_URL') != GITEA:
        raise SystemExit('Publication runs only in the canonical Gitea Downloads workflow')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if revision != os.environ['RELEASE_REVISION'] or not re.fullmatch('[0-9a-f]{40}', revision):
        raise SystemExit('Checkout does not match the requested source commit')
    version_data = json.loads((ROOT / 'version.json').read_text())
    version, code = version_data['version'], version_data['version_code']
    notes = re.search(r'^## \[' + re.escape(version) + r'\] - [^\n]+\n(.*?)(?=^## |\Z)',
                      (ROOT / 'src/CHANGELOG.md').read_text(), re.M | re.S)[1].strip()
    github_token, gitea_token = os.environ['SHOVEY_BUILD_TOKEN'], os.environ['SHOVEY_RELEASE_TOKEN']
    api = GITEA + '/api/v1/repos/' + REPO
    release = request(api, f'/releases/tags/v{version}', gitea_token, missing=True)
    if release and not release['draft']:
        print(f'Shovey {version} is already public; its release stays unchanged', flush=True)
        return
    # Source sync can lag the canonical push; never dispatch another revision.
    deadline = time.monotonic() + 20 * 60
    while True:
        head = request(GITHUB, '/commits/master', github_token)['sha']
        if head == revision:
            break
        if time.monotonic() > deadline:
            raise SystemExit('Exact source is not mirrored to the build backend yet')
        time.sleep(20)
    title = 'Shovey build ' + revision
    def runs():
        return [r for r in request(GITHUB, '/actions/workflows/downloads.yml/runs?event=workflow_dispatch&per_page=100', github_token)['workflow_runs']
                if r['head_sha'] == revision and r['display_title'] == title]
    candidates = runs()
    if not candidates:
        request(GITHUB, '/actions/workflows/downloads.yml/dispatches', github_token, 'POST',
                {'ref': 'master', 'inputs': {'revision': revision, 'rehearse': 'true'}})
        for _ in range(12):
            time.sleep(5)
            candidates = runs()
            if candidates:
                break
        if not candidates:
            raise SystemExit('Build dispatch outcome unknown; do not dispatch again without readback')
    run = candidates[0]
    print('Exact build:', run['html_url'], flush=True)
    deadline = time.monotonic() + 3 * 60 * 60
    while run['status'] != 'completed':
        if time.monotonic() > deadline:
            raise SystemExit('Build still pending; release remains unpublished')
        time.sleep(30)
        run = request(GITHUB, f'/actions/runs/{run["id"]}', github_token)
    if run['conclusion'] != 'success':
        raise SystemExit('Downloads validation failed; release remains unpublished: ' + run['html_url'])
    output = ROOT / 'build' / 'release'
    output.mkdir(parents=True, exist_ok=True)
    downloads = collect(run['id'], github_token, output, version)
    verify(downloads, output, version, code)
    if not release:
        release = request(api, '/releases', gitea_token, 'POST', {'tag_name': 'v' + version,
                          'target_commitish': revision, 'name': 'Shovey ' + version, 'body': notes, 'draft': True})
    tag = request(api, '/tags/v' + version, gitea_token, missing=True)
    if ((tag and tag['commit']['sha'] != revision) or
            (not tag and release['target_commitish'] != revision)):
        raise SystemExit('Release tag points to another source commit')
    assets = {a['name']: a for a in release['assets']}
    if assets.keys() - names(version):
        raise SystemExit('Unexpected assets in existing draft; preserve for review')
    for path in sorted(downloads.iterdir()):
        asset = assets.get(path.name) or upload(release['id'], path, gitea_token)
        readback = output / ('readback-' + path.name)
        download(asset['browser_download_url'], readback, gitea_token)
        if digest(readback) != digest(path):
            raise SystemExit('Uploaded asset differs; release remains a draft')
        readback.unlink()
    request(api, f'/releases/{release["id"]}', gitea_token, 'PATCH', {'draft': False})
    if request(api, '/tags/v' + version, gitea_token)['commit']['sha'] != revision:
        raise SystemExit('Published tag verification failed')
    print(f'Published {GITEA}/{REPO}/releases/tag/v{version}', flush=True)
    # The Play workflow keeps its own signing and account credentials.
    play = request(GITHUB, '/actions/workflows/play-bundle.yml/runs?event=workflow_dispatch&per_page=100', github_token)['workflow_runs']
    if not any(r['head_sha'] == revision for r in play):
        request(GITHUB, '/actions/workflows/play-bundle.yml/dispatches', github_token, 'POST',
                {'ref': 'master', 'inputs': {'revision': revision, 'product_pack': '10'}})


if __name__ == '__main__':
    main()
