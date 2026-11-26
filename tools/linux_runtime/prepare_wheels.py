"""Collect official, target-compatible wheels and install from a closed local set."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import sysconfig
from concurrent.futures import ThreadPoolExecutor
from http.client import IncompleteRead
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

PIP_VERSION = '26.2.2'
runtime = runpy.run_path(str(Path(__file__).resolve().with_name('runtime.py')))
PIP_CLI = (
    'import runpy, sys; sys.path.extend(sys.argv[1:3]); '
    "sys.argv = ['pip', *sys.argv[3:]]; runpy.run_module('pip', run_name='__main__')"
)


def artifact(root, path):
    data = path.read_bytes()
    return {
        'path': path.relative_to(root).as_posix(),
        'sha256': hashlib.sha256(data).hexdigest(),
        'bytes': len(data),
    }


def fetch_release(name, version):
    url = f'https://pypi.org/pypi/{name}/{version}/json'
    for attempt in range(3):
        try:
            with urlopen(url, timeout=25) as response:
                return json.load(response)
        except HTTPError:
            raise
        except (TimeoutError, URLError, IncompleteRead) as error:
            if attempt == 2:
                raise ValueError(f'Unable to read PyPI metadata for {name}=={version}') from error


def collect(name, version, wheelhouse, tag_priority):
    from pip._vendor.packaging.utils import canonicalize_name, parse_wheel_filename

    release = fetch_release(name, version)
    choices = []
    for entry in release['urls']:
        if entry['packagetype'] != 'bdist_wheel' or entry['yanked']:
            continue
        filename = entry['filename']
        parsed_name, parsed_version, build, tags = parse_wheel_filename(filename)
        if canonicalize_name(parsed_name) != name or str(parsed_version) != version:
            raise ValueError(f'Release metadata does not match the pin: {filename}')
        choices_for_target = tags & tag_priority.keys()
        if choices_for_target:
            rank = min(tag_priority[tag] for tag in choices_for_target)
            choices.append((rank, build, filename, tags, entry))
    if not choices:
        raise ValueError(f'No admitted wheel for {name}=={version}')
    _, _, filename, tags, entry = min(choices, key=lambda item: item[:3])
    url = entry['url']
    runtime['validate_wheel_url'](url, filename)
    digest = hashlib.sha256()
    temporary = None
    try:
        with (
            urlopen(url, timeout=60) as response,
            NamedTemporaryFile(dir=wheelhouse, delete=False) as output,
        ):
            temporary = Path(output.name)
            if response.url != url:
                raise ValueError(f'Unexpected wheel redirect: {filename}')
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if (
            digest.hexdigest() != entry['digests']['sha256']
            or temporary.stat().st_size != entry['size']
        ):
            raise ValueError(f'Unexpected wheel bytes: {filename}')
        os.link(temporary, wheelhouse / filename)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {
        'name': name,
        'version': version,
        'filename': filename,
        'sha256': digest.hexdigest(),
        'bytes': entry['size'],
        'tags': sorted(map(str, tags)),
        'source_url': url,
    }


def reuse_wheels(args, target, versions, input_data, bootstrap_source, parse_filename, tags):
    manifest = args.wheel_manifest.absolute()
    root = manifest.parent.parent
    wheelhouse = args.wheelhouse.absolute()
    if (
        manifest != root / runtime['DEPENDENCIES']
        or manifest.resolve(strict=True) != manifest
        or wheelhouse.resolve(strict=True) != wheelhouse
        or not wheelhouse.is_dir()
    ):
        raise ValueError('Expected an original wheel manifest and a local wheel directory')
    original, source_lock, install_lock = runtime['read_wheel_manifest'](
        root, args.wheel_manifest_sha256, target
    )
    if source_lock.read_bytes() != input_data:
        raise ValueError('Input lock differs from the original wheel manifest')
    installer = original['installer']
    runtime['object_fields'](installer, 'name', 'version', 'bootstrap_wheel')
    previous_bootstrap = runtime['artifact'](root, installer['bootstrap_wheel'])
    if (
        installer['name'] != 'pip'
        or installer['version'] != PIP_VERSION
        or previous_bootstrap != root / 'metadata' / bootstrap_source.name
        or runtime['sha256'](bootstrap_source) != installer['bootstrap_wheel']['sha256']
    ):
        raise ValueError('Bootstrap wheel differs from the original build')

    records = original['wheels']
    if type(records) is not list or len(records) != len(versions):
        raise ValueError('Wheel set does not match the input lock')
    identities = [runtime['wheel_identity'](row, parse_filename, tags) for row in records]
    if identities != sorted(versions.items()):
        raise ValueError('Wheel set does not match the input lock')
    if install_lock.read_bytes() != runtime['wheel_lock_content'](records):
        raise ValueError('Install lock differs from the original wheel manifest')
    if {entry.name for entry in wheelhouse.iterdir()} != {row['filename'] for row in records}:
        raise ValueError('Wheel directory differs from the original manifest')
    for row in records:
        runtime['artifact'](
            wheelhouse,
            {'path': row['filename'], 'sha256': row['sha256'], 'bytes': row['bytes']},
        )
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_lock', type=Path)
    parser.add_argument('wheelhouse', type=Path)
    parser.add_argument('--architecture', choices=runtime['BUILD_ARCHITECTURES'], default='aarch64')
    parser.add_argument(
        '--wheel-manifest', type=Path, help='rebuild using an existing, fixed wheel directory'
    )
    parser.add_argument('--wheel-manifest-sha256', help='required SHA256 pin for --wheel-manifest')
    args = parser.parse_args()
    if (args.wheel_manifest is None) != (args.wheel_manifest_sha256 is None):
        parser.error('--wheel-manifest and --wheel-manifest-sha256 must be supplied together')
    if not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode):
        raise ValueError('Run the target interpreter with -I -B -S')
    platform = runtime['require_build_target'](args.architecture)
    prefix = Path(sys.base_prefix)
    metadata = prefix / 'metadata'
    site_packages = Path(sysconfig.get_path('purelib'))
    if not site_packages.is_relative_to(prefix):
        raise ValueError('A private site-packages is required')
    for entry in site_packages.iterdir():
        if entry.name != 'README.txt' or entry.is_symlink() or not entry.is_file():
            raise ValueError('Unexpected input in private site-packages')

    pip_name = f'pip-{PIP_VERSION}-py3-none-any.whl'
    bootstrap_source = prefix / 'lib/python3.13/ensurepip/_bundled' / pip_name
    bootstrap = metadata / pip_name
    sys.path.append(str(bootstrap_source))
    from pip._vendor.packaging.tags import sys_tags
    from pip._vendor.packaging.utils import canonicalize_name, parse_wheel_filename

    input_data = args.input_lock.read_bytes()
    versions = {}
    for line in input_data.decode('utf-8').splitlines():
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([0-9][A-Za-z0-9.]*)', line)
        if not match:
            raise ValueError('Expected an exact requirement lock')
        package = canonicalize_name(match[1])
        if package in versions:
            raise ValueError(f'Duplicate requirement: {package}')
        versions[package] = match[2]
    if len(versions) != 31:
        raise ValueError('Expected the 31 pinned business dependencies')

    tag_priority = {tag: position for position, tag in enumerate(sys_tags())}
    if args.wheel_manifest is None:
        args.wheelhouse.mkdir(mode=0o700, parents=False)
        with ThreadPoolExecutor(max_workers=4) as executor:
            requests = [
                executor.submit(collect, name, version, args.wheelhouse, tag_priority)
                for name, version in sorted(versions.items())
            ]
            records = [request.result() for request in requests]
    else:
        records = reuse_wheels(
            args,
            platform,
            versions,
            input_data,
            bootstrap_source,
            parse_wheel_filename,
            tag_priority.keys(),
        )
    with bootstrap_source.open('rb') as source, bootstrap.open('xb') as output:
        shutil.copyfileobj(source, output)
    source_lock = metadata / 'requirements.input.lock'
    install_lock = metadata / runtime['wheel_lock_name'](platform)
    with source_lock.open('xb') as output:
        output.write(input_data)
    with install_lock.open('xb') as output:
        output.write(runtime['wheel_lock_content'](records))

    env = {
        'HOME': os.environ['HOME'],
        'TMPDIR': os.environ['TMPDIR'],
        'PATH': '/usr/bin:/bin',
        'LANG': 'C.UTF-8',
        'PIP_CONFIG_FILE': '/dev/null',
    }
    pip = [sys.executable, '-I', '-B', '-S', '-c', PIP_CLI, str(bootstrap), str(site_packages)]
    subprocess.run(
        [
            *pip,
            '--disable-pip-version-check',
            '--no-input',
            'install',
            '--no-index',
            '--find-links',
            str(args.wheelhouse),
            '--require-hashes',
            '--only-binary=:all:',
            '--no-cache-dir',
            '--no-compile',
            '--target',
            str(site_packages),
            '-r',
            str(install_lock),
        ],
        env=env,
        check=True,
    )
    subprocess.run([*pip, '--disable-pip-version-check', 'check'], env=env, check=True)
    installed = [
        (canonicalize_name(distribution.metadata['Name']), distribution.version)
        for distribution in importlib.metadata.distributions(path=[str(site_packages)])
    ]
    if sorted(installed) != sorted(versions.items()):
        raise ValueError('Installed distributions differ from the input lock')

    manifest = {
        'format_version': 1,
        'platform': platform,
        'python_version': runtime['PYTHON_VERSION'],
        'input_lock': artifact(prefix, source_lock),
        'install_lock': artifact(prefix, install_lock),
        'installer': {
            'name': 'pip',
            'version': PIP_VERSION,
            'bootstrap_wheel': artifact(prefix, bootstrap),
        },
        'wheels': records,
    }
    with (metadata / 'python-wheels.v1.json').open('x', encoding='utf-8', newline='\n') as output:
        json.dump(manifest, output, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        output.write('\n')


if __name__ == '__main__':
    main()
