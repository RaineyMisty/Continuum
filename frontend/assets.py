"""Fetch pinned Monaco once; subsequent demos run without a CDN or Node build."""
import base64
import hashlib
import io
import json
from pathlib import Path
import tarfile
from urllib.request import urlopen

VERSION = '0.52.2'


def ensure_monaco():
    root = Path(__file__).parent / 'vendor/monaco'
    if (root / '.ready').exists():
        return
    print(f'Preparing Monaco {VERSION} locally (one-time download)...', flush=True)
    with urlopen(f'https://registry.npmjs.org/monaco-editor/{VERSION}', timeout=60) as response:
        metadata = json.load(response)
    with urlopen(metadata['dist']['tarball'], timeout=120) as response:
        data = response.read()
    digest = 'sha512-' + base64.b64encode(hashlib.sha512(data).digest()).decode()
    if digest != metadata['dist']['integrity']:
        raise RuntimeError('Monaco package integrity mismatch')
    root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for member in archive:
            if not member.isfile():
                continue
            if member.name.startswith('package/min/vs/'):
                relative = member.name.removeprefix('package/min/')
            elif member.name == 'package/LICENSE':
                relative = 'LICENSE'
            else:
                continue
            path = (root / relative).resolve()
            if not path.is_relative_to(root.resolve()):
                raise RuntimeError('Invalid archive path')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.extractfile(member).read())
    (root / '.ready').write_text(VERSION)


if __name__ == '__main__':
    ensure_monaco()
