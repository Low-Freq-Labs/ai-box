#!/usr/bin/python3
"""Build the existing self-extracting installer with deterministic source hashes."""
import argparse
import gzip
import hashlib
import io
from pathlib import Path
import tarfile


def build(source, destination):
    source = source.resolve()
    destination = destination.resolve()
    if destination.is_relative_to(source):
        raise ValueError('output must be outside the installer source directory')
    files = []
    for path in sorted(source.rglob('*')):
        if '__pycache__' in path.parts or path.suffix in ('.pyc', '.pyo'):
            continue
        if path.is_symlink():
            raise ValueError('source symlinks are not supported')
        if path.is_file():
            files.append((path.relative_to(source).as_posix(), path.read_bytes()))
    checksums = ''.join(hashlib.sha256(data).hexdigest() + '  ' + name + '\n'
                        for name, data in files).encode()
    payload = io.BytesIO()
    with gzip.GzipFile(fileobj=payload, mode='wb', mtime=0, filename='') as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for name, data in files + [('SHA256SUMS', checksums)]:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o755 if data.startswith(b'#!') else 0o644
                info.mtime = 0
                archive.addfile(info, io.BytesIO(data))
    header = (source / 'debian-freq-ai-setup/freq-ai-setup.header').read_bytes()
    if not header.endswith(b'__AI_FREQ_PAYLOAD_BELOW__\n'):
        raise ValueError('invalid self-extracting header')
    output = header + payload.getvalue()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as stream:
        stream.write(output)
    destination.chmod(0o755)
    digest = hashlib.sha256(output).hexdigest()
    destination.with_name(destination.name + '.sha256').write_text(digest + '  ' + destination.name + '\n')
    print('BUILT', destination, 'sha256=' + digest, 'source_files=' + str(len(files)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    build(Path(__file__).resolve().parent, args.output)
