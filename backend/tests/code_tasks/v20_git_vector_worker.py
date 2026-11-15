"""Fixed MinGit object vectors in a freshly owned test root, never a user repo."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
BODIES = (b'', b'\xef\xbb\xbfhello\r\n\0\xff', bytes(range(256)) * 257 + '中文😀'.encode('utf-8'))


def owned_git_environment(root):
    home = root / 'home'
    home.mkdir()
    template = root / 'empty-template'
    template.mkdir()
    empty = home / 'empty.config'
    empty.open('xb').close()
    system = os.environ['SystemRoot']
    return {
        'SystemRoot': system,
        'PATH': str(Path(system) / 'System32'),
        'HOME': str(home),
        'USERPROFILE': str(home),
        'XDG_CONFIG_HOME': str(home),
        'APPDATA': str(home),
        'LOCALAPPDATA': str(home),
        'TEMP': str(root),
        'TMP': str(root),
        'GIT_CONFIG_NOSYSTEM': '1',
        'GIT_CONFIG_SYSTEM': str(empty),
        'GIT_CONFIG_GLOBAL': str(empty),
        'GIT_CONFIG_COUNT': '0',
        'GIT_OPTIONAL_LOCKS': '0',
        'GIT_LITERAL_PATHSPECS': '1',
        'GIT_CEILING_DIRECTORIES': str(root.parent),
        'GIT_ATTR_NOSYSTEM': '1',
        'GIT_NO_LAZY_FETCH': '1',
        'GIT_NO_REPLACE_OBJECTS': '1',
        'GIT_TERMINAL_PROMPT': '0',
        'GCM_INTERACTIVE': 'never',
        'GIT_TEMPLATE_DIR': str(template),
        'LANG': 'C',
        'LC_ALL': 'C',
    }


def owned_ref_vectors(invoke, *, program, prefix, root, environment, parent_oid, planned_oid):
    """Independent exact wire oracle in this new test bare repo, no product imports."""
    from queue import Queue
    from threading import Thread

    format_spec = '--format=%(refname)%00%(objectname)%00%(symref)%00'
    target = 'refs/heads/vector-target'
    baseline = 'refs/walle/baselines/12'
    alias = 'refs/heads/vector-alias'
    basic = ['update-ref', '--no-deref', '--stdin', '-z']
    delivery = ['update-ref', '--no-deref', '--create-reflog', '-m', 'WALLE:31', '--stdin', '-z']
    ref_env = dict(
        environment,
        GIT_COMMITTER_NAME='Controlled Fixture',
        GIT_COMMITTER_EMAIL='fixture@example.invalid',
        GIT_COMMITTER_DATE='1700000000 +0000',
    )

    def observe(ref):
        return invoke(prefix + ['for-each-ref', format_spec, ref])

    def exchange(arguments, prepare, ending, ref, expected):
        child = subprocess.Popen(
            [str(program), *prefix, *arguments],
            cwd=root,
            env=ref_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        queue = Queue(maxsize=8)

        def read_lines():
            total = 0
            try:
                while True:
                    line = child.stdout.readline(4097)
                    total += len(line)
                    if total > 256:
                        queue.put(ValueError('Owned ACK output exceeded bound'))
                        return
                    queue.put(line)
                    if not line:
                        return
            except Exception as error:
                queue.put(type(error).__name__)

        thread = Thread(target=read_lines, daemon=True)
        thread.start()

        def read_ack(expected):
            actual = queue.get(timeout=5)
            if actual != expected:
                raise ValueError('Original Git ACK differs')
            return actual

        def send(raw):
            offset = 0
            while offset < len(raw):
                sent = child.stdin.write(raw[offset:])
                if not sent or sent > len(raw) - offset:
                    raise ValueError('Owned Git input write failed')
                offset += sent
            child.stdin.flush()

        try:
            # Commit is NOT written until both ACKs and the real held-ref query.
            send(prepare)
            acks = read_ack(b'start: ok\n') + read_ack(b'prepare: ok\n')
            observation = observe(ref)
            if observation != expected:
                send(b'abort\0')
                raise ValueError('Original prepared reference differs')
            send(ending)
            child.stdin.close()
            last = b'commit: ok\n' if ending == b'commit\0' else b'abort: ok\n'
            acks += read_ack(last)
            if child.wait(timeout=5) != 0:
                raise ValueError('Owned ref transaction failed')
            if queue.get(timeout=5) != b'':
                raise ValueError('Extra original Git ACK output')
            if child.stderr.read(65537):
                raise ValueError('Unexpected owned Git stderr')
            return {
                'prepare_hex': prepare.hex(),
                'ack_hex': acks.hex(),
                'prepared_ref_hex': observation.hex(),
            }
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stdin.close()
            child.stdout.close()
            child.stderr.close()
            thread.join(timeout=1)

    def rejected(arguments, prepare):
        result = subprocess.run(
            [str(program), *prefix, *arguments],
            cwd=root,
            env=ref_env,
            input=prepare,
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0 or result.stdout != b'start: ok\n' or len(result.stderr) > 65536:
            raise ValueError('Owned expected-conflict transaction was not rejected')
        return {
            'prepare_hex': prepare.hex(),
            'ack_hex': result.stdout.hex(),
            'exit_code': result.returncode,
        }

    create = b'start\0create ' + baseline.encode() + b'\0' + parent_oid.encode() + b'\0prepare\0'
    created = exchange(basic, create, b'commit\0', baseline, b'')
    expected_baseline = baseline.encode() + b'\0' + parent_oid.encode() + b'\0\0\n'
    if observe(baseline) != expected_baseline:
        raise ValueError('Original baseline retention ref differs')
    collision = rejected(basic, create)
    if observe(baseline) != expected_baseline:
        raise ValueError('Rejected baseline create changed the ref')
    setup = b'start\0create ' + target.encode() + b'\0' + parent_oid.encode() + b'\0prepare\0'
    exchange(basic, setup, b'commit\0', target, b'')
    before = target.encode() + b'\0' + parent_oid.encode() + b'\0\0\n'
    correct = (
        b'start\0update '
        + target.encode()
        + b'\0'
        + planned_oid.encode()
        + b'\0'
        + parent_oid.encode()
        + b'\0prepare\0'
    )
    wrong = (
        b'start\0update '
        + target.encode()
        + b'\0'
        + planned_oid.encode()
        + b'\0'
        + planned_oid.encode()
        + b'\0prepare\0'
    )
    conflict = rejected(delivery, wrong)
    if observe(target) != before:
        raise ValueError('Rejected expected value changed the target')
    aborted = exchange(delivery, correct, b'abort\0', target, before)
    if observe(target) != before:
        raise ValueError('Prepared abort changed the target')
    committed = exchange(delivery, correct, b'commit\0', target, before)
    after = target.encode() + b'\0' + planned_oid.encode() + b'\0\0\n'
    if observe(target) != after:
        raise ValueError('Committed original target differs')
    invoke(prefix + ['symbolic-ref', alias, target])
    symbolic = alias.encode() + b'\0' + planned_oid.encode() + b'\0' + target.encode() + b'\0\n'
    symbolic_prepare = (
        b'start\0update '
        + alias.encode()
        + b'\0'
        + parent_oid.encode()
        + b'\0'
        + planned_oid.encode()
        + b'\0prepare\0'
    )
    symbolic_abort = exchange(delivery, symbolic_prepare, b'abort\0', alias, symbolic)
    if observe(alias) != symbolic or observe(target) != after:
        raise ValueError('Aborted symbolic reference changed its target')
    messages = invoke(prefix + ['reflog', 'show', '--format=%gs', target])
    if messages != b'WALLE:31\n':
        raise ValueError('Original reflog reason differs')
    valid_refs = [
        'refs/heads/main',
        'refs/heads/子目录/版本',
        'refs/heads/-literal',
        'refs/heads/a@b',
        'refs/heads/topic./child',
        'refs/heads/at@',
        'refs/heads/close]',
    ]
    for ref in valid_refs:
        if invoke(['check-ref-format', ref]):
            raise ValueError('Unexpected check-ref-format output')
    return {
        'baseline': created,
        'baseline_collision': collision,
        'expected_conflict': conflict,
        'abort': aborted,
        'commit': committed,
        'symbolic_abort': symbolic_abort,
        'final_ref_hex': after.hex(),
        'baseline_ref_hex': expected_baseline.hex(),
        'reflog_hex': messages.hex(),
        'checked_refs': valid_refs,
    }


def owned_worktree_vectors(invoke, *, prefix, root, format, parent_oid):
    """Fixture creation only: all checkout/delete operations stay in this new root."""
    import shutil

    bad_heads = invoke(
        prefix
        + [
            'for-each-ref',
            '--format=%(refname)%00%(objectname)%00%(objecttype)%00%(symref)%00',
            'refs/heads/',
        ]
    )
    # Reconfigure only the symbolic fixture that the previous vector proved intact.
    invoke(prefix + ['symbolic-ref', '--delete', 'refs/heads/vector-alias'])
    invoke(prefix + ['update-ref', 'refs/heads/idle', parent_oid])
    attached = root / (format + ' attached 工作区')
    detached = root / (format + ' detached')
    missing = root / (format + ' missing')
    for path in (attached, detached, missing):
        if path.resolve().parent != root.resolve() or path.exists():
            raise ValueError('Only new original test worktrees may be created')
    invoke(prefix + ['worktree', 'add', str(attached), 'vector-target'])
    invoke(prefix + ['worktree', 'add', '--detach', str(detached), parent_oid])
    invoke(
        prefix + ['worktree', 'lock', '--reason', 'PRIVATE_LOCK_REASON\nSECOND_LINE', str(detached)]
    )
    invoke(prefix + ['worktree', 'lock', str(attached)])
    healthy = invoke(prefix + ['worktree', 'list', '--porcelain', '-z'])
    heads = invoke(
        prefix
        + [
            'for-each-ref',
            '--format=%(refname)%00%(objectname)%00%(objecttype)%00%(symref)%00',
            'refs/heads/',
        ]
    )
    invoke(prefix + ['worktree', 'add', '--detach', str(missing), parent_oid])
    resolved = missing.resolve(strict=True)
    if (
        resolved.parent != root.resolve()
        or resolved.name != format + ' missing'
        or missing.is_symlink()
    ):
        raise ValueError('Refuse cleanup outside this exact owned test worktree')
    # Capture ONLY this newly created missing fixture's administrative path.
    raw_pointer = (missing / '.git').read_bytes().decode('utf-8')
    if not raw_pointer.startswith('gitdir: ') or not raw_pointer.endswith('\n'):
        raise ValueError('Unexpected new fixture Git pointer')
    missing_admin = Path(raw_pointer[8:-1]).resolve(strict=True)
    repository = root / ('probe-' + format + '.git')
    expected_admin_parent = (repository / 'worktrees').resolve(strict=True)
    if (
        prefix != ['--git-dir=' + str(repository)]
        or repository.resolve().parent != root.resolve()
        or missing_admin.parent != expected_admin_parent
        or not missing_admin.is_dir()
        or missing_admin.is_symlink()
    ):
        raise ValueError('Refuse cleanup outside original new fixture metadata')
    shutil.rmtree(resolved)
    broken = invoke(prefix + ['worktree', 'list', '--porcelain', '-z', '--expire=now'])
    if b'prunable ' not in broken:
        raise ValueError('Missing test worktree was not reported prunable')
    # Restore just this synthetic fixture AFTER recording the negative vector.
    # Product code never prunes/repairs metadata; this is new owned test data.
    if missing_admin.resolve(strict=True).parent != expected_admin_parent:
        raise ValueError('Original missing-fixture metadata changed')
    shutil.rmtree(missing_admin)
    restored = invoke(prefix + ['worktree', 'list', '--porcelain', '-z'])
    if restored != healthy:
        raise ValueError('Healthy actual worktree cohort not restored')
    return {
        'restored_hex': restored.hex(),
        'healthy_hex': healthy.hex(),
        'prunable_hex': broken.hex(),
        'heads_hex': heads.hex(),
        'symbolic_heads_hex': bad_heads.hex(),
        'attached_path': str(attached),
        'detached_path': str(detached),
    }


def main():
    if len(sys.argv) != 3:
        raise ValueError('Explicit owned test root and nonce required')
    root = Path(sys.argv[1]).resolve(strict=True)
    nonce = sys.argv[2]
    if root != Path.cwd().resolve() or len(nonce) != 32:
        raise ValueError('Original owned working root required')
    if (root / '.walle-git-vector-owner').read_text(encoding='ascii') != nonce:
        raise ValueError('Owned test marker differs')
    if any((root / ('probe-' + kind + '.git')).exists() for kind in ('sha1', 'sha256')):
        raise ValueError('Only new test repositories may be initialized')
    program = ROOT / 'backend/runtime/git/2.56.0.windows.4/win-x64/cmd/git.exe'
    environment = owned_git_environment(root)
    step = 'VERSION'
    output = {'completed': False, 'run_nonce': nonce}

    def invoke(arguments, body=None):
        result = subprocess.run(
            [str(program), *arguments],
            cwd=root,
            env=environment,
            input=body,
            capture_output=True,
            check=True,
            timeout=15,
        )
        if len(result.stdout) > 1024 * 1024 or len(result.stderr) > 65536:
            raise ValueError('Owned vector output limit exceeded')
        return result.stdout

    try:
        output['version'] = invoke(['--version']).decode('ascii').strip()
        step = 'CONFIG_EXAMPLES'
        included = root / 'included.config'
        with included.open('xb') as stream:
            stream.write(b'[user]\n name=INCLUDED_SOURCE_MUST_NOT_LOAD\n')
        examples = {
            'implicit': b'[core]\n bare\n',
            'multiline': b'[user]\n name="line one\\nline two"\n',
            'include': ('[include]\n path="' + included.as_posix() + '"\n').encode('utf-8'),
            'forbidden': b'[core]\n hooksPath=PRIVATE_VECTOR_ONLY\n',
        }
        example_output = {}
        for name, source in examples.items():
            private = root / ('example-' + name + '.config')
            if len(source) > 4096 or b'\0' in source:
                raise ValueError('Owned config source is unsupported')
            with private.open('xb') as stream:
                stream.write(source)
            example_output[name] = invoke(
                ['config', '--file', str(private), '--no-includes', '--null', '--list']
            ).hex()
        output['config_examples'] = example_output
        formats = {}
        for kind in ('sha1', 'sha256'):
            step = kind + '.INIT'
            repository = root / ('probe-' + kind + '.git')
            invoke(
                [
                    'init',
                    '--bare',
                    '--initial-branch=walle-probe',
                    '--object-format=' + kind,
                    str(repository),
                ]
            )
            step = kind + '.CONFIG'
            source = (repository / 'config').read_bytes()
            if len(source) > 4096 or b'\0' in source:
                raise ValueError('Owned original config source is unsupported')
            source_sha = hashlib.sha256(source).hexdigest()
            copy = root / ('original-' + kind + '.config')
            with copy.open('xb') as stream:
                stream.write(source)
            config_output = invoke(
                ['config', '--file', str(copy), '--no-includes', '--null', '--list']
            )
            prefix = ['--git-dir=' + str(repository)]
            step = kind + '.BLOBS'
            blobs = []
            for body in BODIES:
                oid = (
                    invoke(prefix + ['hash-object', '-w', '--stdin', '--no-filters'], body)
                    .decode('ascii')
                    .strip()
                )
                if invoke(prefix + ['cat-file', 'blob', oid]) != body:
                    raise ValueError('Actual Git raw bytes differ')
                blobs.append(oid)
            step = kind + '.TREES'
            empty_tree = invoke(prefix + ['mktree', '-z'], b'').decode('ascii').strip()
            records = b''.join(
                ('100644 blob ' + oid + '\t' + str(index) + '.bin\0').encode('ascii')
                for index, oid in enumerate(blobs)
            )
            tree = invoke(prefix + ['mktree', '-z'], records).decode('ascii').strip()
            listing = invoke(prefix + ['ls-tree', '-r', '--full-tree', '-z', tree])
            if listing != records:
                raise ValueError('Actual Git tree entries differ')
            step = kind + '.COMMITS'
            parent_bytes = (
                'tree ' + empty_tree + '\n'
                'author Fixture <fixture@example.invalid> 1600000000 +0000\n'
                'committer Fixture <fixture@example.invalid> 1600000000 +0000\n\n'
                'Private vector parent\n'
            ).encode('utf-8')
            parent_oid = (
                invoke(
                    prefix + ['hash-object', '-t', 'commit', '-w', '--stdin', '--no-filters'],
                    parent_bytes,
                )
                .decode('ascii')
                .strip()
            )
            if invoke(prefix + ['cat-file', 'commit', parent_oid]) != parent_bytes:
                raise ValueError('Actual parent commit bytes differ')
            # Independent fixed wire vector. Production BUILD is not imported.
            delivery_bytes = (
                'tree ' + tree + '\nparent ' + parent_oid + '\n'
                'author 作者 <author@example.invalid> 1700000000 +0000\n'
                'committer 控制方 <committer@example.invalid> 1700000000 +0000\n\n'
                '任务11\n候选22\n结束\nWALL-E-Delivery: 31\n'
            ).encode('utf-8')
            calculated = (
                invoke(
                    prefix + ['hash-object', '-t', 'commit', '--stdin', '--no-filters'],
                    delivery_bytes,
                )
                .decode('ascii')
                .strip()
            )
            written = (
                invoke(
                    prefix + ['hash-object', '-t', 'commit', '-w', '--stdin', '--no-filters'],
                    delivery_bytes,
                )
                .decode('ascii')
                .strip()
            )
            if (
                calculated != written
                or invoke(prefix + ['cat-file', 'commit', written]) != delivery_bytes
            ):
                raise ValueError('Actual delivery commit raw bytes differ')
            step = kind + '.REF_TRANSACTIONS'
            reference_vectors = owned_ref_vectors(
                invoke,
                program=program,
                prefix=prefix,
                root=root,
                environment=environment,
                parent_oid=parent_oid,
                planned_oid=written,
            )
            step = kind + '.WORKTREES'
            worktree_vectors = owned_worktree_vectors(
                invoke,
                prefix=prefix,
                root=root,
                format=kind,
                parent_oid=parent_oid,
            )
            formats[kind] = {
                'config_output': config_output.hex(),
                'config_source_sha256': source_sha,
                'ref_transactions': reference_vectors,
                'worktrees': worktree_vectors,
                'blobs': blobs,
                'empty_tree': empty_tree,
                'tree': tree,
                'delivery_parent': parent_oid,
                'delivery_commit': written,
                'delivery_input_sha256': hashlib.sha256(delivery_bytes).hexdigest(),
                'delivery_payload_bytes': len(delivery_bytes),
            }
        output.update(formats=formats, completed=True)
    except Exception as error:
        output['failed_step'] = step
        output['failure_kind'] = type(error).__name__
        raise
    finally:
        with (root / 'git-vectors.json').open('x', encoding='utf-8') as stream:
            json.dump(output, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())


if __name__ == '__main__':
    main()
