"""Startup uses existing V1.5 admission; no provider or real server is started."""
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
import os

import pytest

from backend.tests.requirements.test_v15_foundation import tmp_path, setup
from backend.tests.documents.test_v15_documents import workspace
from backend.tests.guide.test_v15_acceptance import accept
from backend.tests.guide.test_v15_counting import offline_gate
from backend.tests.guide.test_v15_execution import execute, Gateway, PROFILE
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.infrastructure.collaboration_admission import CollaborationAdmission
from backend.app.shared.command_execution import operation_time


def tool():
    spec=spec_from_file_location('walle_v15_startup_tool_test',Path('tools/ai-service.py'))
    module=module_from_spec(spec);spec.loader.exec_module(module);return module


def test_readiness_does_not_read_credentials_database_or_start_server(monkeypatch,capsys):
    value=tool()
    def forbidden(*args,**kwargs):raise AssertionError('Readiness may not open user state or start services')
    monkeypatch.setattr(value,'read_local_credential',forbidden)
    monkeypatch.setattr('backend.app.infrastructure.database.Database',forbidden)
    monkeypatch.setattr('backend.app.__main__.main',forbidden)
    assert value.main([])==0
    text=capsys.readouterr().out
    assert 'collaboration_context_v1' in text and 'provider_calls=0' in text and 'database_opened=0' in text
    assert 'context_projection_v1' not in text
    with pytest.raises(SystemExit):value.main(['--credential-file','not-read'])


def test_start_requires_existing_new_database_and_real_saved_admission_before_key(workspace,monkeypatch):
    value=tool()
    def forbidden(*args,**kwargs):raise AssertionError('Not admitted; credentials/server must stay untouched')
    monkeypatch.setattr(value,'read_local_credential',forbidden)
    monkeypatch.setattr('backend.app.__main__.main',forbidden)
    monkeypatch.delenv('WALLE_DATABASE_PATH',raising=False)
    with pytest.raises(ConfigInvalid):value.main(['--start'])
    monkeypatch.setenv('WALLE_DATABASE_PATH','relative.sqlite')
    with pytest.raises(ConfigInvalid):value.main(['--start'])
    monkeypatch.setenv('WALLE_DATABASE_PATH',str(workspace[0].path))
    with pytest.raises(ConfigInvalid):value.main(['--start'])
    from contextlib import closing
    import sqlite3
    from backend.app.infrastructure.database import SchemaMismatch
    old=workspace[0].path.with_name('old-schema.sqlite')
    with closing(sqlite3.connect(old)) as connection:connection.execute('PRAGMA user_version=4')
    before=old.read_bytes();monkeypatch.setenv('WALLE_DATABASE_PATH',str(old))
    with pytest.raises(SchemaMismatch):value.main(['--start'])
    assert old.read_bytes()==before


def test_explicit_start_uses_same_release_admission_and_private_environment_only(workspace,monkeypatch,capsys):
    value=tool()
    with monkeypatch.context() as gate:
        offline_gate(gate)
        assert accept(workspace)['code']=='GUIDE_ACCEPTED'
        assert execute(workspace,Gateway())['code']=='AI_FINISHED'
        # Use actual program evidence and validator, not a forged LIVE flag.
        store=CollaborationAdmission(workspace[0],workspace[1].process_lock,workspace[2])
        assert store.approve_saved_call(workspace[0].path,1,operation_time(None))['state']=='LIVE_VERIFIED'
    monkeypatch.setenv('WALLE_DATABASE_PATH',str(workspace[0].path))
    monkeypatch.setenv('WALLE_MODEL_API_KEY','old-environment-value')
    monkeypatch.setenv('WALLE_MODEL_ID',PROFILE.model_name)
    monkeypatch.setenv('WALLE_MODEL_VERSION',PROFILE.model_version)
    secret='startup-private-fixture-key-only';seen=[]
    monkeypatch.setattr(value,'read_local_credential',lambda path:secret)
    monkeypatch.setattr('backend.app.__main__.main',lambda:seen.append({key:os.environ[key]
        for key in ('WALLE_MODEL_API_KEY','WALLE_MODEL_ID','WALLE_MODEL_VERSION')}))
    assert value.main(['--start','--credential-file',str(workspace[0].path.with_name('explicit.env'))])==0
    assert seen==[{'WALLE_MODEL_API_KEY':secret,'WALLE_MODEL_ID':PROFILE.model_name,'WALLE_MODEL_VERSION':PROFILE.model_version}]
    assert secret not in capsys.readouterr().out


def test_invalid_model_environment_is_rejected_before_credentials_or_start(monkeypatch):
    value=tool()
    def forbidden(*args,**kwargs):raise AssertionError('Invalid profile must not read credentials or start')
    monkeypatch.setattr(value,'read_local_credential',forbidden)
    monkeypatch.setattr('backend.app.__main__.main',forbidden)
    monkeypatch.setenv('WALLE_MODEL_ID','unapproved-model')
    with pytest.raises(ConfigInvalid,match='approved exact model/version'):
        value.main(['--start'])
