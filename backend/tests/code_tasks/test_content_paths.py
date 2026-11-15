"""Deterministic path boundaries shared by Git baselines and content packages."""

import pytest

from backend.app.infrastructure.content_paths import (
    ContentPathError,
    ContentPathIndex,
    relative_content_path,
    materialized_path,
    content_file_mode,
)


@pytest.mark.parametrize(
    'path',
    [
        '',
        '.',
        '..',
        'a/../b',
        'a//b',
        '/a',
        r'C:\code',
        r'\\server\code',
        r'a\b',
        'a:b',
        'a*',
        'a?',
        'a<',
        'a|',
        'a\0b',
        'a\nb',
        'a\x85b',
        'a/',
        'a.',
        'a ',
        'aux.txt',
        'COM1.log',
        'com¹.txt',
        'LPT³',
        'CONIN$.txt',
        '.git/config',
        'src/.GIT/config',
        'e\u0301.txt',
        '\ud800',
    ],
)
def test_unsafe_paths_are_rejected_without_normalizing_or_revealing_input(path):
    with pytest.raises(ContentPathError) as error:
        relative_content_path(path)
    assert error.value.code == 'SOURCE_UNSUPPORTED'
    assert error.value.reason.startswith(('CONTENT_', 'RELATIVE_'))


def test_unicode_nfc_case_and_bytes_remain_the_original_logical_path():
    for path in (
        'src/Hello.ts',
        '设计/需求😀.md',
        'é.txt',
        '.github/workflows/test.yml',
        'git.txt',
    ):
        assert relative_content_path(path) == path
    assert relative_content_path('src/Hello.ts') != relative_content_path('src/hello.ts')


@pytest.mark.parametrize(
    'first,second,reason',
    [
        ('Src/a.ts', 'src/b.ts', 'CONTENT_PATH_CASE_ALIAS'),
        ('Straße/a', 'STRASSE/b', 'CONTENT_PATH_CASE_ALIAS'),
        ('a', 'a/b', 'CONTENT_FILE_DIRECTORY_CONFLICT'),
        ('a/b', 'a', 'CONTENT_FILE_DIRECTORY_CONFLICT'),
        ('a/b', 'a/b', 'CONTENT_PATH_DUPLICATE'),
        ('A/b', 'a', 'CONTENT_PATH_CASE_ALIAS'),
    ],
)
def test_complete_tree_checks_files_and_all_parent_directory_aliases(first, second, reason):
    tree = ContentPathIndex()
    original = tree.add_file(first, '100644')
    with pytest.raises(ContentPathError, match=reason):
        tree.add_file(second, '100755')
    assert tree.entries() == (original,)


def test_rejected_entry_never_changes_index_and_entries_have_utf8_byte_order():
    tree = ContentPathIndex()
    tree.add_file('z', '100755')
    tree.add_file('é/a', '100644')
    with pytest.raises(ContentPathError):
        tree.add_file('new/../hidden', '100644')
    tree.add_file('new', '100644')
    assert [(entry.path, entry.mode) for entry in tree.entries()] == [
        ('new', '100644'),
        ('z', '100755'),
        ('é/a', '100644'),
    ]


def test_utf16_materialization_limit_includes_absolute_root_separator_and_non_bmp_units():
    root = r'C:\owned'
    path = 'a' * (240 - len(root) - 1)
    assert len(materialized_path(root, path).encode('utf-16-le')) // 2 == 240
    with pytest.raises(ContentPathError, match='CONTENT_FULL_PATH_TOO_LONG'):
        materialized_path(root, path + 'a')
    with pytest.raises(ContentPathError, match='CONTENT_FULL_PATH_TOO_LONG'):
        materialized_path(root, path[:-1] + '😀')
    tree = ContentPathIndex(materialization_root=root)
    with pytest.raises(ContentPathError):
        tree.add_file(path + 'a', '100644')
    assert tree.entries() == ()


@pytest.mark.parametrize('mode', ['120000', '160000', '040000', '100664', 100644, True, None])
def test_only_normal_git_file_modes_are_supported(mode):
    with pytest.raises(ContentPathError, match='CONTENT_FILE_MODE_UNSUPPORTED'):
        content_file_mode(mode)


def test_explicit_archive_directories_share_the_parent_namespace_without_creating_product_entries():
    tree = ContentPathIndex()
    tree.add_directory('Src')
    assert tree.entries() == ()
    tree.add_file('Src/code.py', '100644')
    with pytest.raises(ContentPathError, match='CONTENT_PATH_CASE_ALIAS'):
        tree.add_directory('src')
    with pytest.raises(ContentPathError, match='CONTENT_FILE_DIRECTORY_CONFLICT'):
        tree.add_directory('Src/code.py')
    with pytest.raises(ContentPathError, match='CONTENT_FILE_DIRECTORY_CONFLICT'):
        tree.add_file('Src', '100644')
    assert [entry.path for entry in tree.entries()] == ['Src/code.py']


def test_restoration_projection_removes_only_verified_files():
    from backend.app.infrastructure.content_paths import (
        ContentPathEntry,
        ContentPathError,
        ContentPathIndex,
    )

    index = ContentPathIndex()
    index.add_file('src', '100644')
    index.add_file('kept.txt', '100755')
    index.add_directory('occupied')
    projected = index.without_files([ContentPathEntry('src', '100644')])
    projected.add_file('src/main.py', '100644')
    assert [entry.path for entry in index.entries()] == ['kept.txt', 'src']
    with pytest.raises(ContentPathError):
        projected.add_file('Kept.txt', '100644')
    with pytest.raises(ContentPathError):
        projected.add_file('occupied', '100644')
    with pytest.raises(ContentPathError):
        index.without_files([ContentPathEntry('src', '100755')])
