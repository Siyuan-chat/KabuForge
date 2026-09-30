"""Content-bound local Parquet snapshots shared by validation and execution."""
import hashlib
from io import BytesIO
from pathlib import Path, PureWindowsPath
import re


def parquet_entries(manifest_path, manifest):
    from .config import ConfigError
    if set(manifest) != {'format', 'datasets'} or manifest['format'] != 'snapshot.parquet.v1':
        raise ConfigError('unsupported parquet snapshot manifest')
    if not isinstance(manifest['datasets'], dict) or not manifest['datasets']:
        raise ConfigError('empty parquet snapshot')
    root = Path(manifest_path).resolve().parent
    entries = {}
    for name, item in manifest['datasets'].items():
        if not isinstance(item, dict) or set(item) != {'path', 'sha256', 'rows'}:
            raise ConfigError('invalid parquet dataset entry: ' + name)
        reference = item['path']
        if not isinstance(reference, str) or PureWindowsPath(reference).is_absolute() or Path(reference).is_absolute():
            raise ConfigError('parquet path must be relative')
        target = (root / reference).resolve()
        if not target.is_relative_to(root) or target.suffix != '.parquet':
            raise ConfigError('parquet path escapes snapshot or has unsupported type')
        if not isinstance(item['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', item['sha256']):
            raise ConfigError('invalid parquet SHA256')
        if type(item['rows']) is not int or item['rows'] < 0:
            raise ConfigError('invalid parquet row count')
        entries[name] = (target, item)
    return entries


def verified_bytes(path, expected):
    from .config import ConfigError
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ConfigError('snapshot dataset changed: ' + str(path))
    return raw


def snapshot_dependencies(path, manifest):
    dependencies = {}
    for target, item in parquet_entries(path, manifest).values():
        verified_bytes(target, item['sha256'])
        dependencies[str(target)] = item['sha256']
    return dependencies


def snapshot_frames(path, manifest):
    import pandas as pd
    from .config import ConfigError
    if manifest.get('format') == 'snapshot.parquet.v1':
        frames = {}
        for name, (target, item) in parquet_entries(path, manifest).items():
            frame = pd.read_parquet(BytesIO(verified_bytes(target, item['sha256'])))
            if len(frame) != item['rows']:
                raise ConfigError('snapshot row count mismatch: ' + name)
            frames[name] = frame
        return frames
    if set(manifest) != {'format', 'datasets'} or manifest['format'] != 'snapshot.inline.v1':
        raise ConfigError('unsupported snapshot manifest')
    frames = {}
    for name, item in manifest['datasets'].items():
        if set(item) != {'columns', 'rows'} or len(set(item['columns'])) != len(item['columns']):
            raise ConfigError('invalid inline snapshot dataset: ' + name)
        frames[name] = pd.DataFrame(item['rows'], columns=item['columns'])
    return frames
