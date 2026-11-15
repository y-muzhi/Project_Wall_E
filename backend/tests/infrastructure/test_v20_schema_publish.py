"""Release resources/pin publication in owned directories, no actual pin changes."""

from pathlib import Path
from unittest.mock import patch
import os

import pytest

from backend.app.infrastructure import schema_v20_publish as publisher
from backend.app.infrastructure.schema_v20_release import _load_verified_release, SchemaMismatch
from backend.tests.requirements.test_v15_foundation import tmp_path


def test_resource_bytes_publish_before_real_compiled_pin_and_existing_release_is_immutable(
    tmp_path,
):
    parent = tmp_path / 'releases'
    pin = tmp_path / 'test_pin.py'
    real = publisher._save_pin
    facts = []

    def last(data, expected):
        assert (parent / 'reviewed-r1' / 'manifest.json').is_file()
        assert not pin.exists()
        facts.append(True)
        return real(data, expected)

    with (
        patch.object(publisher, 'RELEASE_PARENT', parent),
        patch.object(publisher, 'PIN_PATH', pin),
    ):
        with patch.object(publisher, '_save_pin', last):
            release = publisher.publish_release('reviewed-r1')
        assert facts == [True]
        value = pin.read_text(encoding='utf-8')
        assert repr(release.manifest_sha256) in value and "'reviewed-r1'" in value
        assert _load_verified_release(parent / 'reviewed-r1', release.manifest_sha256) == release
        before = pin.read_bytes()
        with pytest.raises(SchemaMismatch, match='new immutable'):
            publisher.publish_release('reviewed-r1')
        assert pin.read_bytes() == before
    assert not list(parent.glob('.schema-stage-*'))


def test_failed_last_pin_keeps_prior_pin_and_immutable_resources_without_fake_admission(tmp_path):
    parent = tmp_path / 'releases'
    pin = tmp_path / 'test_pin.py'
    with pin.open('xb') as stream:
        stream.write(b'prior original pin\r\n')
    before = pin.read_bytes()
    with (
        patch.object(publisher, 'RELEASE_PARENT', parent),
        patch.object(publisher, 'PIN_PATH', pin),
    ):
        with patch.object(publisher, '_save_pin', side_effect=OSError('Injected last publication')):
            with pytest.raises(OSError, match='Injected'):
                publisher.publish_release('reviewed-r2')
    assert pin.read_bytes() == before
    assert (parent / 'reviewed-r2' / 'manifest.json').is_file()
    assert not list(parent.glob('.schema-stage-*'))


def test_pin_atomic_replacement_preserves_original_bytes_on_changed_baseline_and_cleans_temp(
    tmp_path,
):
    pin = tmp_path / 'test_pin.py'
    with pin.open('xb') as stream:
        stream.write(b'actual new content\r\n')
    with patch.object(publisher, 'PIN_PATH', pin):
        with pytest.raises(SchemaMismatch, match='concurrently'):
            publisher._save_pin(b'replacement\n', b'old expected\n')
    assert pin.read_bytes() == b'actual new content\r\n'
    assert not list(tmp_path.glob('.schema-pin-*'))
