"""Build the manual-install ZIP from a strict distribution allowlist."""
import ast
import hashlib
import json
from pathlib import Path
import struct
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'custom_components/mspa_local'
DOCUMENTS = ('README.md', 'LICENSE', 'NOTICE', 'CHANGELOG.md',
             'LICENSES/Nordic-BSD-3-Clause.txt')
BRAND_IMAGES = {'icon.png', 'icon@2x.png', 'logo.png', 'logo@2x.png',
                'dark_logo.png', 'dark_logo@2x.png'}


def main():
    manifest = json.loads((PACKAGE / 'manifest.json').read_text(encoding='utf-8'))
    version = manifest['version']
    assert manifest['domain'] == 'mspa_local'
    assert version and all(c in '0123456789.' for c in version)
    files = [ROOT / name for name in DOCUMENTS]
    for file in PACKAGE.rglob('*'):
        if not file.is_file() or '__pycache__' in file.parts:
            continue
        if file.parent == PACKAGE / 'brand' and file.name in BRAND_IMAGES:
            data = file.read_bytes()
            assert data[:8] == b'\x89PNG\r\n\x1a\n' and data[12:16] == b'IHDR'
            width, height = struct.unpack('>II', data[16:24])
            assert width > 0 and height > 0
            if 'icon' in file.name:
                assert width == height
            files.append(file)
            continue
        if file.suffix not in ('.py', '.json') or file.name == 'mspa_profile.json':
            raise ValueError(f'Unexpected integration file: {file.name}')
        content = file.read_text(encoding='utf-8')
        if file.suffix == '.py':
            ast.parse(content, filename=file.name)
        else:
            json.loads(content)
        files.append(file)
    assert not (PACKAGE / 'energy.py').exists()
    assert json.loads((PACKAGE / 'strings.json').read_text(encoding='utf-8')) == json.loads(
        (PACKAGE / 'translations/en.json').read_text(encoding='utf-8'))
    destination = ROOT / 'dist'
    destination.mkdir(exist_ok=True)
    archive = destination / f'mspa-denver-bt-local-control-{version}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zipped:
        for file in sorted(files):
            # Stable metadata makes identical source produce identical ZIP bytes.
            info = zipfile.ZipInfo(file.relative_to(ROOT).as_posix(), (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            zipped.writestr(info, file.read_bytes())
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        assert 'custom_components/mspa_local/manifest.json' in zipped.namelist()
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = archive.with_suffix('.zip.sha256')
    checksum.write_text(f'{digest}  {archive.name}\n', encoding='utf-8')
    print(f'Built {archive.name}: {len(files)} files; Python, JSON and ZIP checks passed')
    print(f'SHA256: {digest}')


if __name__ == '__main__':
    main()
