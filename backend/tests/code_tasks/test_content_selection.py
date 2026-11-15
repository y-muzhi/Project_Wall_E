"""Selection decisions, not a filesystem/Git capture acceptance."""

from dataclasses import FrozenInstanceError
import pytest

from backend.app.infrastructure.content_paths import ContentPathEntry, ContentPathError
from backend.app.infrastructure.content_selection import ContentSelection


def selection(include=None, exclude=None, baseline=(), mode='100644'):
    return ContentSelection(
        product_include_paths=['.'] if include is None else include,
        nonproduct_exclude_paths=[] if exclude is None else exclude,
        new_file_mode=mode,
        baseline_entries=baseline,
    )


def test_exact_files_directory_boundaries_root_and_empty_include():
    chosen = selection(['src/', 'README.md'])
    assert chosen.file('src/a.py') == ContentPathEntry('src/a.py', '100644')
    assert chosen.file('src/deep/b') is not None
    assert chosen.file('README.md') is not None
    for path in ('src', 'src-extra/a.py', 'readme.md.bak', 'other/README.md'):
        assert chosen.file(path) is None
    assert selection([]).file('new.txt') is None
    assert selection().file('任意/二进制.bin') is not None


def test_existing_modes_are_fixed_without_include_and_new_mode_is_explicit():
    baseline = (ContentPathEntry('src/tool', '100755'), ContentPathEntry('README', '100644'))
    chosen = selection([], [], baseline, '100755')
    assert chosen.file('src/tool').mode == '100755'
    assert chosen.file('README').mode == '100644'
    assert chosen.file('new.txt') is None
    changed = selection(['new/'], [], baseline, '100755')
    assert changed.file('new/tool').mode == '100755'
    assert changed.file('src/tool').mode == '100755'


@pytest.mark.parametrize('rule', ['build/', 'build/file', 'build/deep/'])
def test_exclude_matches_any_fixed_tracked_path_even_if_later_deleted(rule):
    baseline = (
        ContentPathEntry('build/deep/file', '100644'),
        ContentPathEntry('build/file', '100755'),
    )
    with pytest.raises(ContentPathError, match='EXCLUDES_TRACKED'):
        selection(['.'], [rule], baseline)


def test_pruning_is_explicit_nonproduct_only_and_does_not_need_body_reads():
    chosen = selection(
        ['src/'], ['build/', 'src/generated/', 'out.txt'], (ContentPathEntry('docs/old', '100755'),)
    )
    assert chosen.prune_directory('build')
    assert chosen.prune_directory('build/deep')
    assert chosen.prune_directory('src/generated')
    assert not chosen.prune_directory('build-other')
    assert not chosen.prune_directory('out.txt.bak')
    assert not chosen.prune_directory('docs')  # Contains a tracked file, despite no include.
    assert not chosen.prune_directory('unmatched')
    assert chosen.file('docs/old').mode == '100755'
    assert chosen.file('src/generated/a') is None
    assert chosen.file('out.txt') is None
    assert chosen.file('src/product') is not None


@pytest.mark.parametrize(
    'include,exclude',
    [
        (['.', '.'], []),
        (['src/', 'src/'], []),
        (['a'], ['a']),
        (['src/'], ['src/']),
        (['src/file'], ['src/']),
        (['src/deep/'], ['src/']),
        (['a', 'a/'], []),
        (['src/a', 'Src/b'], []),
        (['src/'], ['Src/generated/']),
        (['a', 'a/child'], []),
        (['Src/a'], ['src/b']),
    ],
)
def test_rule_duplicates_aliases_types_and_fully_shadowed_includes_fail(include, exclude):
    with pytest.raises(ContentPathError):
        selection(include, exclude)


def test_normal_overlapping_include_is_boolean_and_does_not_mutate_input():
    includes = ['.', 'src/', 'src/file']
    excludes = ['src/nonproduct/']
    chosen = selection(includes, excludes)
    includes.append('late')
    excludes.clear()
    assert chosen.file('src/file') == ContentPathEntry('src/file', '100644')
    assert chosen.file('src/nonproduct/cache') is None
    with pytest.raises(TypeError):
        chosen._tracked_modes['other'] = '100755'
    with pytest.raises(FrozenInstanceError):
        chosen.new_file_mode = '100755'


@pytest.mark.parametrize(
    'value',
    [
        '',
        './src',
        'src//',
        'src//file',
        '/abs',
        '../x',
        'a/../b',
        'a\\b',
        'a*',
        'a?',
        'C:/x',
        '.git/',
        'a/.git/x',
        'a/CON',
        'a/end.',
        'a/end ',
        'a/\0x',
        'e\u0301',
    ],
)
def test_invalid_rules_are_never_normalized(value):
    with pytest.raises(ContentPathError):
        selection([value], [])
    with pytest.raises(ContentPathError):
        selection(['.'], [value])


def test_exclude_root_is_not_supported():
    with pytest.raises(ContentPathError):
        selection(['.'], ['.'])


def test_legal_literal_characters_do_not_expand_globs_negation_or_shell():
    for literal in ('!a', 'a[0]', 'a$' + '{x}', 'a$(x)'):
        chosen = selection([literal])
        assert chosen.file(literal) is not None
        assert chosen.file('expanded') is None
    assert selection(['a[0]']).file('a0') is None


@pytest.mark.parametrize('value', [None, True, 'src/', ('src/',), {}, [None], [True], [1]])
def test_arrays_and_members_are_strict(value):
    for include, exclude in ((value, []), (['.'], value)):
        with pytest.raises(ContentPathError):
            ContentSelection(
                product_include_paths=include,
                nonproduct_exclude_paths=exclude,
                baseline_entries=(),
                new_file_mode='100644',
            )


@pytest.mark.parametrize(
    'baseline',
    [
        [ContentPathEntry('a', '100644'), ContentPathEntry('a', '100644')],
        [ContentPathEntry('Src/a', '100644'), ContentPathEntry('src/b', '100644')],
        [ContentPathEntry('a', '100644'), ContentPathEntry('a/b', '100644')],
        [ContentPathEntry('a', '120000')],
        [{'path': 'a', 'mode': '100644'}],
        None,
    ],
)
def test_full_baseline_is_validated_before_selecting_anything(baseline):
    with pytest.raises(ContentPathError):
        selection([], [], baseline)


@pytest.mark.parametrize(
    'include,exclude,path,directory',
    [
        (['src/'], [], 'Src/a', False),
        (['.'], ['build/'], 'Build/a', False),
        (['.'], ['build/'], 'Build', True),
        (['.', 'src/a'], [], 'Src/b', False),
    ],
)
def test_aliases_are_not_hidden_by_earlier_root_match_or_exclude(include, exclude, path, directory):
    chosen = selection(include, exclude)
    with pytest.raises(ContentPathError, match='CASE_ALIAS'):
        chosen.prune_directory(path) if directory else chosen.file(path)


def test_rules_against_baseline_cannot_use_different_parent_spelling():
    for includes, excludes in [(['src/a'], []), (['.'], ['src/generated/'])]:
        with pytest.raises(ContentPathError, match='CASE_ALIAS'):
            selection(includes, excludes, (ContentPathEntry('Src/b', '100644'),))


def test_file_rule_does_not_prune_or_select_adjacent_directory():
    chosen = selection(['exact'], [])
    assert chosen.file('exact') is not None
    assert chosen.file('exact/child') is None
    assert not chosen.prune_directory('exact')
    excluded = selection(['.'], ['exact'])
    assert excluded.file('exact') is None
    assert excluded.file('exact/child') is not None
    assert not excluded.prune_directory('exact')
