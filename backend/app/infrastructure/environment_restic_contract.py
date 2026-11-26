"""Fixed Restic version and evidence shared by command and management readers."""

VERSION = '0.19.1'
PUBLISHED = 'LOCAL_SNAPSHOT_PUBLISHED'
RETRIEVED = 'LOCAL_SNAPSHOT_RETRIEVED'
OFFHOST_RETRIEVED = 'OFFHOST_SNAPSHOT_RETRIEVED'
OFFHOST_UPLOADED = 'OFFHOST_SNAPSHOT_UPLOADED'
OFFHOST_BINDING = (
    'source_host_id',
    'verification_host_id',
    'verification_anchor_sha256',
    'storage_profile_sha256',
    'repository_id',
)
BACKUP_POINT_FIELDS = (
    'backup_id',
    'source_data_generation',
    'source_deployment_id',
    'source_control_revision',
    'cutoff_at',
    'backup_manifest_sha256',
    'logical_content_sha256',
)
OFFHOST_RECEIPT_FIELDS = (
    'status',
    'verification_id',
    'verification_policy_sha256',
    'publication_operation_id',
    *OFFHOST_BINDING,
    'source_environment_id',
    *BACKUP_POINT_FIELDS,
    'snapshot_id',
    'restic_sha256',
    'restic_version',
    'snapshot_bytes',
    'snapshot_entries',
    'retrieved_at',
)
OFFHOST_PUBLICATION_FIELDS = (
    'status',
    'publication_operation_id',
    'publication_policy_sha256',
    'source_host_id',
    'source_host_anchor_sha256',
    'source_machine_id_sha256',
    'source_environment_id',
    *BACKUP_POINT_FIELDS,
    'storage_profile_sha256',
    'repository_id',
    'snapshot_id',
    'snapshot_subdirectory',
    'restic_sha256',
    'restic_version',
    'published_at',
)
INTENT_STATUS = 'LOCAL_PUBLICATION_INTENT'
INTENT_FIELDS = ('operation_id', 'backup_id', 'backup_manifest_sha256', 'repository_id')
PROVENANCE_FIELDS = ('policy_sha256', 'restic_sha256', 'restic_version')


def offhost_verification_filename(verification_id):
    return f'verify-{verification_id}-offhost-result.v1.json'


def offhost_publication_filename(operation_id):
    return f'publish-{operation_id}-offhost-result.v1.json'


def publication_intent(record):
    return {
        'format_version': 1,
        'status': INTENT_STATUS,
        **{key: record[key] for key in (*INTENT_FIELDS, *PROVENANCE_FIELDS)},
    }
