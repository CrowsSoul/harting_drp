"""Refresh separate source and desktop-release manifests from the repository root."""
from pathlib import Path
import hashlib
import os

SKIP = {'.git', '.desktop-venv', '.venv', '.python', '.pytest_cache', '.uv-cache',
        '.tools', '__pycache__', 'node_modules', 'build', 'dist',
        'runtime', '.cache', 'report_archives', 'release'}


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def public_files(root):
    for folder, directories, names in os.walk(root, followlinks=False):
        directories[:] = sorted(name for name in directories if name not in SKIP
            and not (Path(folder) == root and name == 'verification')
            and not name.startswith(('pytest-cache-files-', 'web-test-'))
            and not (Path(folder) / name).is_symlink())
        for name in sorted(names):
            path = Path(folder) / name
            if name.startswith('.env') and name != '.env.example':
                continue
            if (name not in {'SHA256.txt', 'desktop.log'}
                    and not name.startswith('accounts.sqlite3')
                    and path.suffix.lower() not in {'.pyc', '.pyo', '.pem', '.pfx', '.key', '.lic'}
                    and not path.is_symlink()):
                yield path


def write_manifest(root):
    files = sorted(public_files(root))
    (root / 'SHA256.txt').write_text(''.join(
        f'{digest(path)}  {path.relative_to(root).as_posix()}\n'
        for path in files), encoding='utf-8')
    return len(files)


def main():
    root = Path(__file__).resolve().parents[1]
    source_count = write_manifest(root)
    release = root / 'release'
    release_count = write_manifest(release) if release.is_dir() else 0
    print(f'Checksums updated: {source_count} source files, {release_count} release files')


if __name__ == '__main__':
    main()
