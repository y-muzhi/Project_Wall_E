"""Production factory/lifespan in process only: no listening server or Chat."""
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.infrastructure.database import Database
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.service import create_app


def test_real_startup_create_framework_and_close_leave_no_ai_work_or_lock():
    with TemporaryDirectory(prefix='walle-v15-asgi-') as directory:
        db = Database(Path(directory) / 'service.sqlite')
        db.initialize()
        app = create_app(database=db)
        with TestClient(app) as client:
            response = client.post('/api/v1/requirements', json={'title': '进程内创建', 'requirement_type': 'NEW', 'initial_idea': '不启动模型'}, headers={'Idempotency-Key': str(uuid4())})
            assert response.status_code == 201, response.text
            assert client.get('/api/v1/requirements/1').status_code == 200
            response = client.post('/api/v1/requirements/1/documents', json={'name': '空白文档', 'document_kind': 'DESIGN', 'template_ref': None}, headers={'Idempotency-Key': str(uuid4())})
            assert response.status_code == 201, response.text
            assert client.get('/api/v1/requirements/1/current-document?document_id=1').status_code == 200
            worker = app.state.walle_worker
            assert worker.accepting and not worker.live_run_ids
            assert worker.catalog.collaboration.release['admission']['state'] == 'OFFLINE_READY'
            assert not any(event['event'].startswith('DISPATCH') for event in worker.events)
            with db.transaction() as connection:
                assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 0
                assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0
        assert app.state.walle_runtime is None
        with ProcessLock.for_database(db.path):
            pass
