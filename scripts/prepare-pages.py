#!/usr/bin/env python3
"""Package a built release for Pages without changing its runtime or identity."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 25 * 1024 * 1024
CHUNK_SIZE = 16 * 1024 * 1024
START = '      // The game travels'
END = '      Promise.all(['


def prepare_pages(output, packaging_revision=None):
    output = Path(output)
    if output.is_symlink() or not output.is_dir():
        raise ValueError('Pages output must be a real directory')
    for path in output.rglob('*'):
        if path.is_symlink():
            raise ValueError(f'Symlink in Pages output: {path}')
        if path.is_file() and path.name not in ('runtime.data', 'runtime.data.gz') and path.stat().st_size > LIMIT:
            raise ValueError(f'Pages file exceeds 25 MiB: {path}')
        if path.name.startswith('runtime.data.part-') and not path.is_file():
            raise ValueError(f'Invalid chunk path: {path}')
    data = output / 'runtime.data'
    page = output / 'index.html'
    html = page.read_text()
    template = (ROOT / 'site/index.html').read_text()
    # Fail before mutating if the loader is not the supported page entry.
    begin, end = html.index(START), html.index(END, html.index(START))
    loader = template[template.index(START):template.index(END, template.index(START))]
    receipt = json.loads((output / 'build.json').read_text())
    original = hashlib.sha256()
    for name in ('runtime.js', 'runtime.wasm', 'runtime.data', 'arcade.json'):
        original.update(name.encode() + b'\0')
        with (output / name).open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                original.update(block)
    if original.hexdigest() != receipt['assets_sha256']:
        raise ValueError('Released site assets do not match build.json')
    manifest = dict(format=1, size=data.stat().st_size, sha256='', chunks=[])
    digest = hashlib.sha256()
    with data.open('rb') as source:
        while block := source.read(CHUNK_SIZE):
            name = f'runtime.data.part-{len(manifest["chunks"]):04d}'
            (output / name).write_bytes(block)
            digest.update(block)
            manifest['chunks'].append(dict(name=name, size=len(block), sha256=hashlib.sha256(block).hexdigest()))
    if not manifest['size']:
        raise ValueError('Empty game data')
    manifest['sha256'] = digest.hexdigest()
    (output / 'runtime.data.json').write_text(json.dumps(manifest, indent=2) + '\n')
    page.write_text(html[:begin] + loader + html[end:])
    data.unlink()
    data.with_suffix('.data.gz').unlink(missing_ok=True)
    build = output / 'build.json'
    receipt['packaging_revision'] = packaging_revision or subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    receipt['data_manifest_sha256'] = hashlib.sha256((output / 'runtime.data.json').read_bytes()).hexdigest()
    build.write_text(json.dumps(receipt) + '\n')
    # Check the entire deployment, including any future additional files.
    for path in output.rglob('*'):
        if path.is_symlink():
            raise ValueError(f'Symlink in Pages output: {path}')
        if path.is_file() and path.stat().st_size > LIMIT:
            raise ValueError(f'Pages file exceeds 25 MiB: {path}')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare_pages(args.output), indent=2))
