"""Verify that fixed Linux runtime pins cannot cross architecture boundaries."""

import os
import runpy
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from packaging.tags import Tag
from packaging.utils import parse_wheel_filename


@pytest.fixture
def runtime(monkeypatch):
    entry = Path(__file__).resolve().parents[3] / 'tools' / 'linux_runtime' / 'runtime.py'
    module = runpy.run_path(str(entry))
    functions = module['verify_runtime'].__globals__
    monkeypatch.setitem(functions, 'protected_file', lambda *args: None)
    monkeypatch.setitem(functions, 'protected_directory', lambda *args: None)
    return functions


def platform(architecture):
    return {
        'os': 'linux',
        'architecture': architecture,
        'distribution_id': 'ubuntu',
        'distribution_version': '24.04',
    }


def record_file(runtime, root, relative, record):
    path = root / relative
    if type(record) is not bytes:
        record = runtime['canonical'](record)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(record)
    return {
        'path': relative,
        'bytes': len(record),
        'sha256': runtime['sha256'](path),
    }


def proposed_runtime(runtime, root, target):
    input_lock = record_file(runtime, root, 'metadata/requirements.input.lock', b'test==1\n')
    install_lock = record_file(
        runtime,
        root,
        'metadata/' + runtime['wheel_lock_name'](target),
        b'test==1 --hash=sha256:' + b'1' * 64 + b'\n',
    )
    wheels = {
        'format_version': 1,
        'platform': target,
        'python_version': runtime['PYTHON_VERSION'],
        'input_lock': input_lock,
        'install_lock': install_lock,
        'installer': {},
        'wheels': [],
    }
    build = record_file(runtime, root, runtime['BUILD_INPUTS'], b'{}\n')
    deps = record_file(runtime, root, runtime['DEPENDENCIES'], wheels)
    manifest = {
        'format_version': 1,
        'runtime_id': 'native-sample',
        'platform': target,
        'installation_prefix': str(root),
        'python': {
            'implementation': 'cpython',
            'version': runtime['PYTHON_VERSION'],
            'cache_tag': 'cpython-313',
            'soabi': runtime['target_soabi'](target),
            'executable_ref': 'bin/python3.13',
            'sqlite_extension_ref': 'lib/python3.13/lib-dynload/_sqlite3.so',
            'site_packages_ref': 'lib/python3.13/site-packages',
        },
        'sqlite': {
            'version': runtime['SQLITE_VERSION'],
            'source_id': runtime['SOURCE_ID'],
            'library_ref': 'lib/libsqlite3.so.0',
            'compile_options': ['MAX_TRIGGER_DEPTH=100', 'THREADSAFE=1'],
            'required_features': runtime['FEATURES'],
            'required_limits': runtime['LIMITS'],
        },
        'files_ref': {},
        'dependencies_ref': deps,
        'host_libraries': [],
        'build_ref': build,
        'launch_flags': runtime['FLAGS'],
    }
    return manifest, wheels


def test_registry_recovery_host_enters_verified_python_before_opening_registry(
    runtime, tmp_path, monkeypatch
):
    launcher = Path(__file__).resolve().parents[3] / 'tools/linux_runtime/manage_registry.py'
    main = runpy.run_path(str(launcher))['main']
    globals_ = main.__globals__
    root = tmp_path / 'runtime'
    project = tmp_path / 'program'
    runtime_entry = root / 'metadata/runtime.py'
    executable = root / 'bin/python3.13'
    arguments = [
        str(launcher),
        'place-registry-recovery',
        '--root',
        str(root),
        '--sha256',
        'a' * 64,
        '--project',
        str(project),
        '--program-sha256',
        'b' * 64,
        '--runtime-entry',
        str(runtime_entry),
        '--anchor',
        str(tmp_path / 'manager-installation.v1.json'),
        '--anchor-sha256',
        'c' * 64,
        '--registry-recovery-policy',
        str(tmp_path / 'registry-recovery-policy.v1.json'),
        '--registry-recovery-policy-sha256',
        'd' * 64,
        '--registry-recovery-receipt-sha256',
        'e' * 64,
    ]
    calls = []

    def measured_program(candidate):
        assert candidate == project
        calls.append('program')
        return 'b' * 64

    def measured_runtime(candidate, expected):
        assert candidate == root and expected == 'a' * 64
        assert calls == ['program']
        calls.append('runtime')
        return {'python': {'executable_ref': 'bin/python3.13'}}, {}

    def demand(condition, message):
        assert condition, message

    class EnteredFixedRuntime(BaseException):
        pass

    def replace_process(path, argv, environment):
        assert calls == ['program', 'runtime']
        assert path == executable
        assert argv == [str(executable), *runtime['FLAGS'], *arguments]
        assert environment == {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'TZ': 'UTC'}
        raise EnteredFixedRuntime

    entry = {
        'verify_program': measured_program,
        'verify_runtime': measured_runtime,
        'demand': demand,
        'FLAGS': runtime['FLAGS'],
    }
    monkeypatch.setattr(sys, 'argv', arguments)
    monkeypatch.setitem(
        globals_,
        'os',
        SimpleNamespace(geteuid=lambda: 0, environ={}, execve=replace_process),
    )
    monkeypatch.setitem(
        globals_,
        'sys',
        SimpleNamespace(
            argv=arguments,
            executable='/usr/bin/python3',
            path=[],
            flags=SimpleNamespace(isolated=1, no_site=1),
            dont_write_bytecode=True,
        ),
    )
    monkeypatch.setitem(globals_, 'runpy', SimpleNamespace(run_path=lambda path: entry))
    monkeypatch.setitem(globals_, 'trusted_script', lambda name: None)
    with pytest.raises(EnteredFixedRuntime):
        main()


@pytest.mark.parametrize(('host', 'other'), [('aarch64', 'x86_64'), ('x86_64', 'aarch64')])
def test_runtime_and_wheel_pins_require_native_platform(
    runtime, tmp_path, monkeypatch, host, other
):
    identity = platform(host)
    other_identity = platform(other)
    monkeypatch.setitem(runtime, 'os_release', lambda: identity)
    manifest, wheels = proposed_runtime(runtime, tmp_path, identity)
    known_files = {
        manifest['python']['executable_ref'],
        manifest['python']['sqlite_extension_ref'],
        manifest['sqlite']['library_ref'],
        runtime['DEPENDENCIES'],
        runtime['BUILD_INPUTS'],
        'metadata/runtime.py',
        'lib/walle_environment_lock.so',
    }
    monkeypatch.setitem(
        runtime,
        'verify_files',
        lambda *args: (dict.fromkeys(known_files), {manifest['python']['site_packages_ref']}),
    )
    monkeypatch.setitem(runtime, 'verify_host_libraries', lambda value: value)

    def verify(record):
        ref = record_file(runtime, tmp_path, runtime['RUNTIME_MANIFEST'], record)
        return runtime['verify_runtime'](tmp_path, ref['sha256'])

    assert verify(manifest) == (manifest, [])
    confirmed, _, install_lock = runtime['read_wheel_manifest'](
        tmp_path, manifest['dependencies_ref']['sha256'], identity
    )
    assert confirmed == wheels
    assert install_lock.name == f'requirements-linux-{host}-cp313.lock'
    with pytest.raises(runtime['AdmissionError'], match='Runtime platform differs'):
        verify({**manifest, 'platform': other_identity})
    with pytest.raises(runtime['AdmissionError'], match='Unsupported CPython ABI'):
        verify(
            {
                **manifest,
                'python': {**manifest['python'], 'soabi': runtime['target_soabi'](other_identity)},
            }
        )
    for changed in (
        {**wheels, 'platform': other_identity},
        {
            **wheels,
            'install_lock': record_file(
                runtime, tmp_path, 'metadata/' + runtime['wheel_lock_name'](other_identity), b'x\n'
            ),
        },
    ):
        ref = record_file(runtime, tmp_path, runtime['DEPENDENCIES'], changed)
        with pytest.raises(runtime['AdmissionError'], match='Dependency .* (differs|this target)'):
            runtime['read_wheel_manifest'](tmp_path, ref['sha256'], identity)


def test_explicit_cloud_build_refuses_wrong_kernel_or_interpreter(runtime, monkeypatch):
    identity = platform('x86_64')
    monkeypatch.setitem(runtime, 'os_release', lambda: identity)
    monkeypatch.setitem(
        runtime,
        'sys',
        SimpleNamespace(
            implementation=SimpleNamespace(name='cpython', cache_tag='cpython-313'),
            version_info=(3, 13, 18),
        ),
    )
    monkeypatch.setitem(
        runtime,
        'sysconfig',
        SimpleNamespace(get_config_var=lambda name: 'cpython-313-x86_64-linux-gnu'),
    )
    assert runtime['require_build_target']('x86_64') == identity
    with pytest.raises(runtime['AdmissionError'], match='Build architecture differs'):
        runtime['require_build_target']('aarch64')
    monkeypatch.setattr(
        runtime['sysconfig'], 'get_config_var', lambda name: 'cpython-313-aarch64-linux-gnu'
    )
    with pytest.raises(runtime['AdmissionError'], match='Build interpreter ABI differs'):
        runtime['require_build_target']('x86_64')
    for wrong in ({'distribution_version': '22.04'}, {'architecture': 'amd64'}, {'os': 'win32'}):
        monkeypatch.setitem(runtime, 'os_release', lambda: {**identity, **wrong})
        with pytest.raises(runtime['AdmissionError'], match='Unsupported runtime platform'):
            runtime['require_build_target']('x86_64')


@pytest.fixture
def wheel_recipe(runtime, monkeypatch):
    entry = Path(__file__).resolve().parents[3] / 'tools' / 'linux_runtime' / 'prepare_wheels.py'
    module = runpy.run_path(str(entry))
    functions = module['reuse_wheels'].__globals__
    monkeypatch.setitem(functions, 'runtime', runtime)
    return functions


def draft_wheel(runtime, directory, tag, contents=b'wheel content'):
    name = 'sample'
    version = '1.0'
    filename = f'{name}-{version}-{tag}.whl'
    artifact = record_file(runtime, directory, filename, contents)
    return {
        'name': name,
        'version': version,
        'filename': filename,
        'sha256': artifact['sha256'],
        'bytes': artifact['bytes'],
        'tags': [str(tag)],
        'source_url': f'https://files.pythonhosted.org/packages/{filename}',
    }


def test_reuse_wheels_verifies_snapshot_without_network(
    runtime, wheel_recipe, tmp_path, monkeypatch
):
    target = platform('x86_64')
    monkeypatch.setitem(runtime, 'os_release', lambda: target)
    previous = tmp_path / 'previous'
    wheelhouse = tmp_path / 'wheels'
    bootstrap_name = 'pip-26.2.2-py3-none-any.whl'
    bootstrap_ref = record_file(runtime, previous, 'metadata/' + bootstrap_name, b'fixed pip')
    bootstrap = tmp_path / bootstrap_name
    bootstrap.write_bytes(b'fixed pip')
    relevant_tag = Tag('cp313', 'cp313', 'manylinux_2_28_x86_64')
    foreign_tag = Tag('cp313', 'cp313', 'manylinux_2_28_aarch64')
    row = draft_wheel(runtime, wheelhouse, relevant_tag)
    input_data = b'sample==1.0\n'
    manifest = {
        'format_version': 1,
        'platform': target,
        'python_version': runtime['PYTHON_VERSION'],
        'input_lock': record_file(
            runtime, previous, 'metadata/requirements.input.lock', input_data
        ),
        'install_lock': record_file(
            runtime,
            previous,
            'metadata/' + runtime['wheel_lock_name'](target),
            runtime['wheel_lock_content']([row]),
        ),
        'installer': {'name': 'pip', 'version': '26.2.2', 'bootstrap_wheel': bootstrap_ref},
        'wheels': [row],
    }
    metadata = previous / runtime['DEPENDENCIES']

    def fail_network(*args, **kwargs):
        pytest.fail('The fixed wheel directory must work without network.')

    monkeypatch.setitem(wheel_recipe, 'urlopen', fail_network)

    def reuse(approved=manifest, *, input_bytes=input_data, tags=None, stale=False):
        manifest_reference = record_file(runtime, previous, runtime['DEPENDENCIES'], approved)
        args = SimpleNamespace(
            wheel_manifest=metadata,
            wheel_manifest_sha256='a' * 64 if stale else manifest_reference['sha256'],
            wheelhouse=wheelhouse,
        )
        original_paths = {path: path.read_bytes() for path in previous.rglob('*') if path.is_file()}
        try:
            return wheel_recipe['reuse_wheels'](
                args,
                target,
                {'sample': '1.0'},
                input_bytes,
                bootstrap,
                parse_wheel_filename,
                {relevant_tag} if tags is None else tags,
            )
        finally:
            assert {path: path.read_bytes() for path in original_paths} == original_paths

    assert reuse() == [row]
    with pytest.raises(runtime['AdmissionError'], match='Manifest digest mismatch'):
        reuse(stale=True)
    with pytest.raises(ValueError, match='Input lock differs'):
        reuse(input_bytes=b'sample==2.0\n')
    with pytest.raises(runtime['AdmissionError'], match='Incorrect target wheel identity'):
        reuse(tags={foreign_tag})
    with pytest.raises(runtime['AdmissionError'], match='Unexpected wheel source'):
        reuse({**manifest, 'wheels': [{**row, 'source_url': row['source_url'] + '?outside=1'}]})
    (wheelhouse / 'extra.whl').write_bytes(b'foreign')
    with pytest.raises(ValueError, match='Wheel directory differs'):
        reuse()
    (wheelhouse / 'extra.whl').unlink()
    pinned = wheelhouse / row['filename']
    pinned.write_bytes(b'changed bytes')
    with pytest.raises(runtime['AdmissionError'], match='Artifact mismatch'):
        reuse()
    pinned.write_bytes(b'wheel content')
    bootstrap.write_bytes(b'other pip')
    with pytest.raises(ValueError, match='Bootstrap wheel differs'):
        reuse()


def test_collect_publishes_only_verified_bytes(wheel_recipe, tmp_path, monkeypatch):
    from pip._vendor.packaging.tags import Tag as InstallerTag

    tag = InstallerTag('py3', 'none', 'any')
    filename = 'sample-1.0-py3-none-any.whl'
    url = f'https://files.pythonhosted.org/packages/{filename}'

    class Response(BytesIO):
        pass

    source = {
        'packagetype': 'bdist_wheel',
        'yanked': False,
        'filename': filename,
        'url': url,
        'digests': {'sha256': 'a' * 64},
        'size': 5,
    }

    def fake_response(path, *, timeout):
        assert path == url
        response = Response(b'wheel')
        response.url = url
        return response

    monkeypatch.setitem(wheel_recipe, 'fetch_release', lambda *args: {'urls': [source]})
    monkeypatch.setitem(wheel_recipe, 'urlopen', fake_response)
    with pytest.raises(ValueError, match='Unexpected wheel bytes'):
        wheel_recipe['collect']('sample', '1.0', tmp_path, {tag: 0})
    assert not tuple(tmp_path.iterdir())
    source['digests']['sha256'] = wheel_recipe['hashlib'].sha256(b'wheel').hexdigest()
    collected = wheel_recipe['collect']('sample', '1.0', tmp_path, {tag: 0})
    assert (tmp_path / filename).read_bytes() == b'wheel'
    assert collected['sha256'] == source['digests']['sha256']
    assert sorted(path.name for path in tmp_path.iterdir()) == [filename]


@pytest.mark.parametrize(
    'change',
    (None, 'bytes', 'mode', 'symlink', 'directory-link', 'hardlink', 'unregistered', 'missing'),
)
@pytest.mark.skipif(
    sys.platform != 'linux' or getattr(os, 'geteuid', lambda: 1)() != 0,
    reason='Requires an isolated Linux filesystem with root-owned release inputs',
)
def test_indexed_runtime_checks_every_entry_using_its_opened_inode(tmp_path, change):
    entry = Path(__file__).resolve().parents[3] / 'tools' / 'linux_runtime' / 'runtime.py'
    runtime = runpy.run_path(str(entry))
    root = tmp_path / 'runtime'
    data = record_file(runtime, root, 'lib/input', b'expected')
    file = root / data['path']
    file.chmod(0o444)
    manifest = {
        'files_ref': record_file(
            runtime,
            root,
            runtime['INDEX'],
            {'format_version': 1, 'files': [{**data, 'mode': '0444'}]},
        )
    }
    (root / runtime['INDEX']).chmod(0o444)
    if change == 'bytes':
        file.write_bytes(b'changed!')
    elif change == 'mode':
        file.chmod(0o555)
    elif change == 'symlink':
        outside = tmp_path / 'outside'
        file.rename(outside)
        file.symlink_to(outside)
    elif change == 'directory-link':
        outside = tmp_path / 'outside'
        file.parent.rename(outside)
        (root / 'lib').symlink_to(outside, target_is_directory=True)
    elif change == 'hardlink':
        os.link(file, tmp_path / 'other-name')
    elif change == 'unregistered':
        (root / 'unexpected').mkdir()
    elif change == 'missing':
        file.unlink()

    if change is None:
        rows, directories = runtime['verify_files'](root, manifest)
        assert rows == {data['path']: {**data, 'mode': '0444'}}
        assert directories == {'lib'}
    else:
        with pytest.raises((runtime['AdmissionError'], OSError)):
            runtime['verify_files'](root, manifest)
