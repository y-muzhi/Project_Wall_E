"""Provider-specific technical evidence over the shared admission file/lock flow."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3

from backend.app.shared.json_canonical import canonical_input

from .collaboration_admission import CollaborationAdmission, _profile_digest, evidence_database
from .collaboration_resources import sha256
from .model_profile import ModelProfile
from .openai_protocol import MODEL, usage
from .resources import ConfigInvalid
from .schema_transport import compact


def validate_measurements(raw, *, release, request_tokens, input_tokens, output_tokens):
    try:
        if raw.get('object') != 'response' or raw.get('model') != MODEL:
            raise ValueError('OpenAI actual model differs')
        incoming, outgoing, _ = usage(raw)
        if (
            type(request_tokens) is not int
            or request_tokens <= 0
            or incoming != request_tokens
            or incoming != input_tokens
            or outgoing != output_tokens
            or incoming > release['input_limit']
            or outgoing > release['output_limit']
            or incoming + outgoing > release['total_limit']
        ):
            raise ValueError('OpenAI actual usage differs from its complete count or limits')
    except (ValueError, KeyError, TypeError) as error:
        raise ConfigInvalid('OpenAI actual usage failed its exact request count') from error


def _review_evidence(path):
    from .formation_database import FormationDatabase
    from .review_schema import load_review_release, supports_review_layout

    source = Path(path)
    if not source.is_absolute() or not source.is_file():
        return None
    try:
        with closing(
            sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)
        ) as connection:
            if not supports_review_layout(connection):
                return None
    except sqlite3.Error:
        return None
    return FormationDatabase(source, formation_release=load_review_release(), read_only=True)


class OpenAIAdmission(CollaborationAdmission):
    """Native evidence interpretation and the pinned review layout on readback."""

    def _evidence_database(self, path):
        if Path(path).resolve() == Path(self.database.path).resolve():
            return self.database
        return _review_evidence(path)

    def _saved(self, path, identity):
        review = self._evidence_database(path)
        if review is None:
            return super()._saved(path, identity)
        with review.transaction() as connection:
            row = connection.execute(
                'SELECT * FROM llm_uses WHERE id=? AND guide_run_id IS NOT NULL', (identity,)
            ).fetchone()
            if row is None:
                raise ConfigInvalid('The original admitted call is unavailable')
            return dict(row)

    def _observation(self, row, profile_snapshot):
        from backend.app.guide.collaboration_counting import restore_counted, verify_counted

        try:
            snapshot = json.loads(row['request_snapshot_json'])
            profile = ModelProfile.from_snapshot(profile_snapshot)
            if (
                profile.provider != 'openai'
                or snapshot['profile'] != profile_snapshot
                or row['function_type'] != 'collaboration_v1'
                or row['call_status'] != 'SUCCEEDED'
                or row['ended_at'] is None
            ):
                raise ValueError('OpenAI evidence must be an occurred native call')
            context = restore_counted(snapshot, self.catalog, profile)
            measurement = verify_counted(context, self.catalog, profile)['count_attempts'][-1][
                'measurement'
            ]
            raw = json.loads(row['raw_response_json'])
            validate_measurements(
                raw,
                release=self.resources.counting,
                request_tokens=measurement['request_tokens'],
                input_tokens=row['input_tokens'],
                output_tokens=row['output_tokens'],
            )
            evidence = {
                'state': 'LIVE_VERIFIED',
                'profile_sha256': _profile_digest(profile_snapshot),
                'release_sha256': self.resources.release_sha256,
                'evidence_ref': 'llm-use:' + str(row['id']),
                'count_request_sha256': measurement['request_sha256'],
                'chat_request_sha256': sha256(compact(profile.request(context))),
                'actual_input_tokens': row['input_tokens'],
                'request_input_tokens': measurement['request_tokens'],
                'count_gap': row['input_tokens'] - measurement['request_tokens'],
                'reserve': 0,
            }
            return self.resources.validate('Admission', evidence)
        except (ValueError, KeyError, TypeError) as error:
            raise ConfigInvalid('Saved OpenAI observation does not prove this release') from error

    def _suspended(self, path, profile_snapshot):
        reference = self.resources.reference('collaboration.release')
        source = self._evidence_database(path) or evidence_database(path)
        with source.transaction() as connection:
            rows = connection.execute(
                """SELECT input_tokens,output_tokens,
                json_extract(raw_response_json,'$.model') AS actual_model,
                json_extract(raw_response_json,'$.object') AS actual_object,
                json_extract(raw_response_json,'$.usage') AS actual_usage,
                json_extract(request_snapshot_json,'$.counting.count_attempts[#-1].measurement.request_tokens') AS counted
                FROM llm_uses WHERE guide_run_id IS NOT NULL AND function_type='collaboration_v1'
                AND call_status='SUCCEEDED'
                AND json_extract(request_snapshot_json,'$.protocol.release.digest')=?
                AND json_extract(request_snapshot_json,'$.profile')=?""",
                (reference['digest'], canonical_input(profile_snapshot)),
            ).fetchall()
            for row in rows:
                try:
                    validate_measurements(
                        {
                            'model': row['actual_model'],
                            'object': row['actual_object'],
                            'usage': None
                            if row['actual_usage'] is None
                            else json.loads(row['actual_usage']),
                        },
                        release=self.resources.counting,
                        request_tokens=row['counted'],
                        input_tokens=row['input_tokens'],
                        output_tokens=row['output_tokens'],
                    )
                except (ConfigInvalid, ValueError, TypeError):
                    return True
        return False


def admission_for(database, lock, catalog):
    mode = catalog.collaboration.release.get('model_transport', {}).get('mode')
    kind = OpenAIAdmission if mode == 'openai_responses_v1' else CollaborationAdmission
    return kind(database, lock, catalog)


def counter_for(profile):
    if profile.provider == 'openai':
        from .openai_counting import OpenAIInputCounter

        return OpenAIInputCounter()
    from .tokenization import TokenizationGateway

    return TokenizationGateway()
