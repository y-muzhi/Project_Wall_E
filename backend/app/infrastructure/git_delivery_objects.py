"""Fixed object commands for the original planned local delivery."""

from dataclasses import asdict, dataclass
from hashlib import sha256

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .content_manifest import git_oid
from .content_package import CandidatePackageBinding, _package_trees, verify_candidate_package
from .git_commit_input import DeliveryCommitInput, verify_stored_delivery_commit
from .git_object_read import git_object_id, verify_git_object
from backend.app.shared.json_canonical import canonical_input


class DeliveryObjectError(ValueError):
    pass


@dataclass(frozen=True)
class DeliveryObjectIntent:
    kind: str
    object_format: str
    object_oid: str
    input_bytes: int
    input_sha256: str

    def __post_init__(self):
        if (
            self.kind not in ('WRITE_BLOB', 'WRITE_TREE', 'WRITE_COMMIT')
            or type(self.input_bytes) is not int
            or not 0 <= self.input_bytes <= MAX_SAFE_INTEGER
            or type(self.input_sha256) is not str
            or len(self.input_sha256) != 64
            or any(char not in '0123456789abcdef' for char in self.input_sha256)
        ):
            raise DeliveryObjectError('ORIGINAL_DELIVERY_OBJECT_INTENT_INVALID')
        git_oid(self.object_oid, self.object_format)
        if not self.object_oid.strip('0'):
            raise DeliveryObjectError('ORIGINAL_DELIVERY_OBJECT_ID_INVALID')

    @property
    def digest(self):
        return sha256(canonical_input(asdict(self)).encode('utf-8')).hexdigest()

    def verify_input(self, raw):
        if (
            type(raw) is not bytes
            or len(raw) != self.input_bytes
            or sha256(raw).hexdigest() != self.input_sha256
        ):
            raise DeliveryObjectError('ORIGINAL_DELIVERY_OBJECT_INPUT_DIFFERS')
        if self.kind != 'WRITE_TREE':
            kind = 'blob' if self.kind == 'WRITE_BLOB' else 'commit'
            if git_object_id(raw, format=self.object_format, object_type=kind) != self.object_oid:
                raise DeliveryObjectError('ORIGINAL_DELIVERY_OBJECT_OID_DIFFERS')

    def arguments(self):
        if self.kind == 'WRITE_BLOB':
            return ('hash-object', '-w', '--stdin', '--no-filters')
        if self.kind == 'WRITE_TREE':
            return ('mktree', '-z')
        return ('hash-object', '-t', 'commit', '-w', '--stdin', '--no-filters')

    def verify_output(self, output):
        if output != self.object_oid.encode('ascii') + b'\n':
            raise DeliveryObjectError('ORIGINAL_DELIVERY_OBJECT_OUTPUT_DIFFERS')


def delivery_object_intent(kind, format, oid, raw):
    intent = DeliveryObjectIntent(kind, format, oid, len(raw), sha256(raw).hexdigest())
    intent.verify_input(raw)
    return intent


def build_original_delivery_objects(
    package,
    binding,
    commit,
    *,
    expected_manifest_sha256,
    limits,
    git_limits,
    started_at,
    active,
    exchange=None,
    read_object,
):
    """Verify sealed delivery objects, writing them only when a writer is supplied."""
    if (
        type(commit) is not DeliveryCommitInput
        or type(binding) is not CandidatePackageBinding
        or commit.format != binding.object_format
        or (exchange is not None and not callable(exchange))
        or not callable(read_object)
    ):
        raise DeliveryObjectError('ORIGINAL_DELIVERY_OBJECT_BINDING_REQUIRED')
    checked = verify_stored_delivery_commit(
        commit.payload,
        format=commit.format,
        tree_oid=commit.tree_oid,
        parent_oid=commit.parent_oid,
        delivery_id=commit.delivery_id,
        expected_payload_sha256=commit.payload_sha256,
        expected_commit_oid=commit.commit_oid,
        max_payload_bytes=git_limits.max_object_bytes,
    )
    if checked != commit:
        raise DeliveryObjectError('ORIGINAL_DELIVERY_COMMIT_DIFFERS')

    def observed(kind, oid, maximum):
        active()
        data = read_object(kind, oid, maximum)
        return verify_git_object(
            data, format=commit.format, object_type=kind, oid=oid, max_output_bytes=maximum
        )

    observed('commit', commit.parent_oid, git_limits.max_object_bytes)

    def write(kind, oid, raw):
        if exchange is None:
            return
        active()
        intent = delivery_object_intent(kind, commit.format, oid, raw)
        intent.verify_output(exchange(intent, raw))

    # Verify the original package and the advertised complete root before writing any object.
    options = {
        'limits': limits,
        'git_limits': git_limits,
        'started_at': started_at,
        'active': active,
    }
    original = verify_candidate_package(package, binding, **options)
    if (
        original.manifest_sha256 != expected_manifest_sha256
        or original.manifest.content_tree_oid != commit.tree_oid
    ):
        raise DeliveryObjectError('ORIGINAL_DELIVERY_CANDIDATE_DIFFERS')

    verified_blobs = set()

    def blob(entry, raw):
        if entry.blob_oid in verified_blobs:
            return
        write('WRITE_BLOB', entry.blob_oid, raw)
        actual = observed('blob', entry.blob_oid, max(1, entry.byte_count))
        if actual.raw != raw or actual.sha256 != entry.sha256:
            raise DeliveryObjectError('ORIGINAL_DELIVERY_BLOB_BYTES_DIFFER')
        verified_blobs.add(entry.blob_oid)

    verify_candidate_package(package, binding, expected=original, consume_file=blob, **options)
    root, trees, _ = _package_trees(
        original.manifest.entries, format=commit.format, limits=git_limits
    )
    if root != commit.tree_oid:
        raise DeliveryObjectError('ORIGINAL_DELIVERY_ROOT_DIFFERS')
    for tree in trees:
        write('WRITE_TREE', tree.oid, tree.mktree_input)
        if observed('tree', tree.oid, max(1, len(tree.raw))).raw != tree.raw:
            raise DeliveryObjectError('ORIGINAL_DELIVERY_TREE_BYTES_DIFFER')
    write('WRITE_COMMIT', commit.commit_oid, commit.payload)
    if observed('commit', commit.commit_oid, max(1, len(commit.payload))).raw != commit.payload:
        raise DeliveryObjectError('ORIGINAL_DELIVERY_COMMIT_BYTES_DIFFER')
    return commit.commit_oid
