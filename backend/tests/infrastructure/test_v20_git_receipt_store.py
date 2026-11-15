"""Actual private Git receipt append/recovery; no Git, task or service side effect."""

import hashlib
from dataclasses import replace
from unittest.mock import patch

import pytest

from backend.app.infrastructure import git_receipt_store as stores
from backend.app.infrastructure import windows_config_source as sources
from backend.app.infrastructure import windows_private_record as records
from backend.app.infrastructure.git_receipts import GitReceiptError, encode_receipt
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal
from backend.app.infrastructure.windows_local_paths import PathBoundaryError
from backend.app.infrastructure.windows_private_package import create_private_package
from backend.tests.code_tasks.test_git_receipts import binding, facts, receipt
from backend.tests.requirements.test_v15_foundation import tmp_path


@pytest.fixture
def setup(tmp_path):
    root = create_private_package(tmp_path / 'git-evidence')
    with LaunchJournal(root) as journal:
        store = stores.GitReceiptStore(journal, binding(), max_receipt_bytes=4096, max_records=100)
        try:
            yield store, journal
        finally:
            store.close()


class Proxy:
    def __init__(self, kernel, **overrides):
        self.kernel, self.overrides = kernel, overrides

    def __getattr__(self, name):
        return self.overrides.get(name, getattr(self.kernel, name))


def test_actual_append_read_private_identity_and_separate_phases(setup):
    store, journal = setup
    original = receipt()
    first = store.append(original)
    second = store.append(replace(original, phase='EXITED', facts=facts(exit_code=0)))
    assert first.filename != second.filename
    assert store.read(first) == original and store.read(second).phase == 'EXITED'
    assert not store._pending and not store._retained_reads
    assert (journal.root / first.filename).read_bytes() == encode_receipt(
        original, max_receipt_bytes=4096
    )
    assert journal._package.verify_member(first.filename, directory=False) == first.file
    # Native nonce state remains absent: appending evidence never prepares a
    # process or dispatches work through this same original private journal.
    assert journal.inspect(binding().scope) is None


def test_original_phase_is_observable_after_reopen_and_cannot_be_appended_twice(setup):
    _, journal = setup
    limits = dict(max_receipt_bytes=4096, max_records=100, unique_phases=True)
    prepared = receipt()
    from contextlib import closing

    with closing(stores.GitReceiptStore(journal, binding(), **limits)) as store:
        assert store.read_phase(prepared.phase) is None
        original = store.append(prepared)
    with closing(stores.GitReceiptStore(journal, binding(), **limits)) as reopened:
        assert reopened.read_phase(prepared.phase) == (original, prepared)
        with pytest.raises(stores.GitReceiptStoreError, match='REQUIRES_OBSERVATION'):
            reopened.append(prepared)
        assert reopened.read_phase(prepared.phase) == (original, prepared)
    other = replace(binding(), scope=replace(binding().scope, operation_id=12))
    with closing(stores.GitReceiptStore(journal, other, **limits)) as unrelated:
        assert unrelated.read_phase(prepared.phase) is None
    assert list(journal.root.glob('*.git.json')) == [journal.root / original.filename]


def test_binding_mismatch_or_secret_fact_rejected_before_publication(setup):
    store, journal = setup
    with pytest.raises(stores.GitReceiptStoreError, match='BINDING_DIFFERS'):
        store.append(replace(receipt(), binding=replace(binding(), repository_id=99)))
    fields = receipt().facts
    with pytest.raises(GitReceiptError):
        store.append(replace(receipt(), facts={'stdout': 'PRIVATE_BODY'}))
    assert not list(journal.root.glob('*.git.json'))
    assert fields == receipt().facts


def test_store_read_does_not_follow_other_original_operation(setup):
    store, journal = setup
    reference = store.append(receipt())
    other = stores.GitReceiptStore(
        journal,
        replace(binding(), scope=replace(binding().scope, operation_id=12)),
        max_receipt_bytes=4096,
        max_records=100,
    )
    with pytest.raises(GitReceiptError, match='BINDING_DIFFERS'):
        other.read(reference)


def test_changed_bytes_and_replaced_file_identity_rejected(setup):
    store, journal = setup
    reference = store.append(receipt())
    path = journal.root / reference.filename
    with path.open('r+b') as stream:
        stream.seek(0)
        stream.write(b'X')
    with pytest.raises(stores.GitReceiptStoreError, match='ORIGINAL_BYTES_DIFFER'):
        store.read(reference)
    path.unlink()  # Inactive owned fixture only.
    with path.open('xb') as stream:
        stream.write(encode_receipt(receipt(), max_receipt_bytes=4096))
    with pytest.raises(sources.ConfigReadError, match='ORIGINAL_FILE_DIFFERS'):
        store.read(reference)


def test_unknown_published_flush_reconciles_same_original_without_new_append(setup):
    store, journal = setup
    api = records.record_api()
    calls = []

    def flush(handle):
        calls.append(handle)
        # Initial staged fsync succeeds; post-rename flush outcome is unknown.
        return api.FlushFileBuffers(handle) if len(calls) == 1 else False

    with patch.object(records, 'record_api', return_value=Proxy(api, FlushFileBuffers=flush)):
        with pytest.raises(stores.GitReceiptStoreError, match='APPEND_UNVERIFIED') as caught:
            store.append(receipt())
    assert caught.value.retained_owner is store and len(store._pending) == 1
    writer = store._pending[0]
    assert writer._rename_may and not writer._published and writer._target.exists()
    with pytest.raises(stores.GitReceiptStoreError, match='REQUIRES_OBSERVATION'):
        store.append(receipt())
    original_names = tuple(path.name for path in journal.root.glob('*.git.json'))
    writer._kernel = api
    with patch.object(
        records.PrivateRecordAppend, 'publish', side_effect=AssertionError('No rename')
    ):
        result = store.reconcile_pending()
    assert len(result) == 1 and result[0][1] == receipt()
    assert store.read(result[0][0]) == receipt()
    assert tuple(path.name for path in journal.root.glob('*.git.json')) == original_names
    assert not store._pending


def test_unconfirmed_rename_not_proved_unsent_by_absent_final_file(setup):
    store, journal = setup
    api = records.record_api()

    def info(handle, kind, data, length):
        return False if kind == 3 else api.SetFileInformationByHandle(handle, kind, data, length)

    with patch.object(
        records, 'record_api', return_value=Proxy(api, SetFileInformationByHandle=info)
    ):
        with pytest.raises(stores.GitReceiptStoreError, match='APPEND_UNVERIFIED'):
            store.append(receipt())
    writer = store._pending[0]
    assert writer._stage.exists() and not writer._target.exists()
    writer._kernel = api
    with pytest.raises(stores.GitReceiptStoreError, match='STILL_UNVERIFIED'):
        store.reconcile_pending()
    assert writer in store._pending and writer._stage.exists()
    store.close()
    assert writer._stage.exists() and writer._handle is None
    assert not list(journal.root.glob('*.git.json'))


def test_capacity_is_scoped_private_evidence_count_not_overwrite(setup):
    store, journal = setup
    limited = stores.GitReceiptStore(journal, binding(), max_receipt_bytes=4096, max_records=1)
    first = limited.append(receipt())
    with pytest.raises(stores.GitReceiptStoreError, match='CAPACITY_EXHAUSTED'):
        limited.append(replace(receipt(), phase='EXITED'))
    assert limited.read(first) == receipt()
    assert len(list(journal.root.glob('*.git.json'))) == 1


def test_read_reference_fields_are_not_arbitrary_paths(setup):
    store, _ = setup
    reference = store.append(receipt())
    for invalid in (
        replace(reference, filename='../secret'),
        replace(reference, sha256='A' * 64),
        replace(reference, byte_count=False),
        replace(reference, file={}),
    ):
        with pytest.raises(stores.GitReceiptStoreError, match='ORIGINAL_GIT_RECEIPT_REFERENCE'):
            store.read(invalid)


def test_file_hash_matches_but_noncanonical_extra_secret_is_still_rejected(setup):
    store, journal = setup
    reference = store.append(receipt())
    path = journal.root / reference.filename
    raw = path.read_bytes().replace(b'"facts":{', b'"facts":{"stderr":"PRIVATE",')
    with path.open('r+b') as stream:
        stream.seek(0)
        stream.write(raw)
        stream.truncate()
    modified = replace(reference, sha256=hashlib.sha256(raw).hexdigest(), byte_count=len(raw))
    with pytest.raises(GitReceiptError, match='FIELDS_INVALID') as caught:
        store.read(modified)
    assert 'PRIVATE' not in str(caught.value)


def test_failed_postpublish_read_close_retains_original_child_owner(setup):
    store, _ = setup
    api = sources.read_api()
    wrapped = Proxy(api, CloseHandle=lambda handle: False)
    try:
        with patch.object(sources, 'read_api', return_value=wrapped):
            with pytest.raises(stores.GitReceiptStoreError, match='APPEND_UNVERIFIED') as caught:
                store.append(receipt())
        assert caught.value.retained_owner is store
        assert store._pending and store._retained_reads
        assert all(source._handle for source in store._retained_reads)
    finally:
        for source in store._retained_reads:
            source._kernel = api
        store.close()
    assert not store._retained_reads
    assert store.reconcile_pending()[0][1] == receipt()
