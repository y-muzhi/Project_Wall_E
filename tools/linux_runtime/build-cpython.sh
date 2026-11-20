#!/usr/bin/env bash
# Run in an isolated build environment. The installer creates an empty final
# prefix, owned by the build identity, before invoking this stage.
set -euo pipefail
umask 077

prefix=$(realpath -e -- "$1")
inputs=$(realpath -e -- "$2")
[[ "$prefix" = "$1" && "$prefix" != / && ! -L "$1" && -O "$prefix" ]]
[[ "$(uname -sm)" = 'Linux aarch64' ]]
source /etc/os-release
[[ "$ID" = ubuntu && "$VERSION_ID" = 24.04 ]]
[[ -z "$(find "$prefix" -mindepth 1 -print -quit)" ]]
[[ "$prefix" =~ ^/[a-zA-Z0-9/_-][a-zA-Z0-9/_.-]*$ ]]

build=$(mktemp -d "$TMPDIR/walle-cpython.XXXXXXXX")
trap 'rm -rf -- "$build"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
python_archive="$inputs/Python-3.13.18.tar.xz"
sqlite_archive="$inputs/sqlite-amalgamation-3540100.zip"
printf '%s  %s\n' 'abb0102e6d4ae027509bcb82327d9dd85515b44a3ba8ad538cfc5e9847029f68' "$python_archive" |
    sha256sum --check --status

sqlite_member=sqlite-amalgamation-3540100
/usr/bin/python3 -I -B -S - "$sqlite_archive" "$build" "$sqlite_member" <<'PY'
import hashlib
from pathlib import Path
import sys
import zipfile

archive, folder = map(Path, sys.argv[1:3])
member = sys.argv[3]
if hashlib.sha3_256(archive.read_bytes()).hexdigest() != '92281c86e2957f9b9305890f9ac04204caa7b677cc868dc326d942689df28e30':
    raise SystemExit('SQLite archive digest differs')
with zipfile.ZipFile(archive) as bundle:
    source = bundle.read(f'{member}/sqlite3.c')
    if hashlib.sha3_256(source).hexdigest() != 'e2b869d3003b33c942b7dd7063604fbc53553e1b66609570df39b9b7b558ee81':
        raise SystemExit('SQLite member digest differs')
    (folder / 'sqlite3.c').write_bytes(source)
    (folder / 'sqlite3.h').write_bytes(bundle.read(f'{member}/sqlite3.h'))
PY

tar -xJf "$python_archive" -C "$build"
mkdir -- "$prefix/lib" "$prefix/metadata"
sqlite_flags=(-shared -fPIC -O2 -DSQLITE_THREADSAFE=1 -DSQLITE_ENABLE_COLUMN_METADATA -DSQLITE_MAX_TRIGGER_DEPTH=100)
sqlite_link=(-Wl,-soname,libsqlite3.so.0 -lpthread -ldl -lm)
gcc "${sqlite_flags[@]}" -o "$prefix/lib/libsqlite3.so.0" "$build/sqlite3.c" "${sqlite_link[@]}"
ln -s -- "$prefix/lib/libsqlite3.so.0" "$build/libsqlite3.so"

cd "$build/Python-3.13.18"
configure_argv=("--prefix=$prefix" --with-ensurepip=no --disable-test-modules)
export LIBSQLITE3_CFLAGS="-I$build"
export LIBSQLITE3_LIBS="-L$build -Wl,-rpath,$prefix/lib -l:libsqlite3.so.0"
./configure "${configure_argv[@]}"
LD_LIBRARY_PATH="$prefix/lib" make -j2
LD_LIBRARY_PATH="$prefix/lib" make altinstall
unset LIBSQLITE3_CFLAGS LIBSQLITE3_LIBS

/usr/bin/python3 -I -B -S - "$prefix" "$python_archive" "$sqlite_archive" "$build/sqlite3.c" <<'PY'
import hashlib
import json
from pathlib import Path
import subprocess
import sys

prefix, python_source, sqlite_archive, sqlite_source = map(Path, sys.argv[1:])
sqlite_url = 'https://www.sqlite.org/2026/sqlite-amalgamation-3540100.zip'
def source(name, path, url, member=None):
    data = path.read_bytes()
    return dict(name=name, source_url=url, member_path=member,
                sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))

def tool(name, argv):
    return dict(name=name, version=subprocess.check_output(argv, text=True).splitlines()[0])

value = {
    'format_version': 1,
    'sources': [
        source('cpython', python_source, 'https://www.python.org/ftp/python/3.13.18/Python-3.13.18.tar.xz'),
        source('sqlite-amalgamation', sqlite_archive, sqlite_url),
        source('sqlite3.c', sqlite_source, sqlite_url, 'sqlite-amalgamation-3540100/sqlite3.c'),
    ],
    'toolchain': [
        tool('compiler', ['gcc', '--version']),
        tool('linker', ['ld', '--version']),
        tool('distribution', ['lsb_release', '-ds']),
        tool('make', ['make', '--version']),
        {'name': 'installer', 'version': 'pip 26.2.2'},
    ],
    'configure_argv': [f'--prefix={prefix}', '--with-ensurepip=no', '--disable-test-modules'],
    'cflags': ['-shared', '-fPIC', '-O2', '-DSQLITE_THREADSAFE=1',
               '-DSQLITE_ENABLE_COLUMN_METADATA', '-DSQLITE_MAX_TRIGGER_DEPTH=100',
               '-I<temporary-build-root>'],
    'ldflags': ['-Wl,-soname,libsqlite3.so.0', '-lpthread', '-ldl', '-lm',
                '-L<temporary-build-root>', f'-Wl,-rpath,{prefix}/lib', '-l:libsqlite3.so.0'],
    'expected_prefix': str(prefix),
}
with (prefix / 'metadata/build-inputs.v1.json').open('x', encoding='utf-8', newline='\n') as output:
    json.dump(value, output, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    output.write('\n')
PY
