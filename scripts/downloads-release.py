#!/usr/bin/env python3
"""Publish the downloads Gitea's native jobs built, signed and verified."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

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


def collect(build, revision, version):
    """The downloads this run's native jobs built and signed from one commit."""
    if (build / 'revision').read_text().strip() != revision:
        raise ValueError('Native build belongs to another source commit')
    downloads = build / 'downloads'
    found = {p.name for p in downloads.iterdir()}
    if found != names(version) or any(p.is_symlink() or not p.is_file() for p in downloads.iterdir()):
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


def upload_github(upload_url, path, token):
    base = upload_url.split('{', 1)[0]
    parsed = urllib.parse.urlsplit(base)
    connection = http.client.HTTPSConnection(parsed.netloc, timeout=300)
    try:
        query = urllib.parse.urlencode({'name': path.name})
        connection.putrequest('POST', f'{parsed.path}?{query}')
        connection.putheader('Authorization', 'Bearer ' + token)
        connection.putheader('User-Agent', 'Shovey-Downloads/1.0')
        connection.putheader('Content-Type', 'application/octet-stream')
        connection.putheader('Content-Length', str(path.stat().st_size))
        connection.endheaders()
        with path.open('rb') as stream:
            while block := stream.read(1024 * 1024):
                connection.send(block)
        response = connection.getresponse()
        if response.status != 201:
            raise RuntimeError(f'GitHub asset upload HTTP {response.status}; read release state before retrying')
        return json.loads(response.read(1024 * 1024))
    finally:
        connection.close()


def mirror_github_release(version, revision, notes, downloads, token):
    tag = 'v' + version
    release = request(GITHUB, f'/releases/tags/{tag}', token, missing=True)
    if release and not release.get('draft'):
        print(f'GitHub release {tag} is already public', flush=True)
        return
    if not release:
        releases = request(GITHUB, '/releases?per_page=30', token) or []
        release = next((r for r in releases if r.get('draft') and r.get('tag_name') == tag), None)
    if not release:
        release = request(GITHUB, '/releases', token, 'POST', {
            'tag_name': tag, 'target_commitish': revision,
            'name': 'Shovey ' + version, 'body': notes, 'draft': True,
        })
    assets = {a['name']: a for a in release.get('assets', [])}
    for path in sorted(downloads.iterdir()):
        if path.name not in assets:
            upload_github(release['upload_url'], path, token)
    request(GITHUB, f'/releases/{release["id"]}', token, 'PATCH', {
        'tag_name': tag, 'target_commitish': revision,
        'name': 'Shovey ' + version, 'body': notes,
        'draft': False, 'make_latest': 'true',
    })
    print(f'Mirrored https://github.com/waozixyz/shovey/releases/tag/{tag}', flush=True)


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
    build = Path(os.environ['SHOVEY_NATIVE_BUILD']).resolve(strict=True)
    downloads = collect(build, revision, version)
    verify(downloads, build, version, code)
    if os.environ.get('SHOVEY_REHEARSE') == 'true':
        print(f'Shovey {version} downloads verified; a rehearsal publishes nothing', flush=True)
        return
    github_token, gitea_token = os.environ['SHOVEY_BUILD_TOKEN'], os.environ['SHOVEY_RELEASE_TOKEN']
    api = GITEA + '/api/v1/repos/' + REPO
    release = request(api, f'/releases/tags/v{version}', gitea_token, missing=True)
    if release and not release['draft']:
        print(f'Shovey {version} is already public; its release stays unchanged', flush=True)
        return
    output = ROOT / 'build' / 'release'
    output.mkdir(parents=True, exist_ok=True)
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
    # The mirror's release and the Play upload name this commit; wait for the
    # source mirror rather than tagging another revision there.
    deadline = time.monotonic() + 20 * 60
    while request(GITHUB, '/commits/master', github_token)['sha'] != revision:
        if time.monotonic() > deadline:
            raise SystemExit('Published on Gitea; the GitHub mirror has not received this commit yet')
        time.sleep(20)
    mirror_github_release(version, revision, notes, downloads, github_token)
    # The Play workflow keeps its own signing and account credentials.
    play = request(GITHUB, '/actions/workflows/play-bundle.yml/runs?event=workflow_dispatch&per_page=100', github_token)['workflow_runs']
    if not any(r['head_sha'] == revision for r in play):
        request(GITHUB, '/actions/workflows/play-bundle.yml/dispatches', github_token, 'POST',
                {'ref': 'master', 'inputs': {'revision': revision, 'product_pack': '10'}})


if __name__ == '__main__':
    main()
