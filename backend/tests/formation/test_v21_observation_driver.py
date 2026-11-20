"""CLI observation allowance is enforced by the actual isolated C01/C07 driver."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools'))
import formation_evaluation as inputs
import formation_evaluation_execution as runner
from formation_evaluation import manifest_rows
from formation_evaluation_fixture import prepare_sample
from formation_evaluation_spec import samples

from backend.app.infrastructure.model_profile import ModelProfile
from backend.tests.guide.test_v15_counting import Counter
from backend.tests.guide.test_v15_execution import Gateway


def test_single_observation_driver_never_sends_the_second_prepared_case(
    tmp_path_factory, monkeypatch
):
    tmp_path = tmp_path_factory.mktemp('od')
    manifest = runner.MANIFEST.read_text(encoding='utf-8')
    rows = manifest_rows(manifest)
    profile = ModelProfile('offline-only-observation-driver', 'deepseek-v2')
    report_parent = tmp_path / 'docs/verification/v2.1'
    report_parent.mkdir(parents=True)
    (tmp_path / 'data').mkdir()
    output = tmp_path / 'data/s'
    report = report_parent / 'observation.md'

    def prepare(directory, catalog, actual_profile, content, event):
        cases = []
        assert actual_profile.snapshot == profile.snapshot and content == manifest
        for sample in samples()[:2]:
            target = directory / sample.sample_id
            target.mkdir()
            _, facts = prepare_sample(target, catalog, sample)
            cases.append(
                (
                    sample,
                    target / 'input.sqlite',
                    [row for row in rows if row[0] == sample.sample_id],
                    facts,
                )
            )
        return cases

    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(inputs, 'ROOT', tmp_path)
    monkeypatch.setattr(runner, 'verify_metadata', lambda: manifest)
    monkeypatch.setattr(runner, 'recipe_digest', lambda: 'a' * 64)
    monkeypatch.setattr(runner, 'runner_digest', lambda: 'b' * 64)
    monkeypatch.setattr(runner, 'prepare_all', prepare)
    args = SimpleNamespace(
        allow_chat_calls=1,
        allow_count_batches=2,
        max_total_tokens=139264,
        output_dir=output,
        report=report,
        credential_file=tmp_path / 'must-not-be-read',
    )
    counter, gateway = Counter(['OK']), Gateway()
    assert runner.execute(args, profile=profile, gateway=gateway, counter=counter) == 0
    assert len(counter.calls) == len(gateway.calls) == 1
    summary = report.read_text(encoding='utf-8')
    assert '登记样本：1/60' in summary and 'Chat尝试：1/1' in summary
    assert 'OBSERVATION_FINISHED' in summary
    attempts = report.with_name('observation-attempts.md').read_text(encoding='utf-8')
    assert attempts.count('| NOT_RUN |') == 59
    assert attempts.count('| LIVE_RETURNED |') == 1
    snapshot_body = profile.request(gateway.calls[0])
    assert snapshot_body['response_format']['type'] == 'json_schema'
    assert 'offline-only-observation-driver' not in json.dumps(snapshot_body)
