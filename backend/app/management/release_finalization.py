"""Assemble one final fixed build from its protected, verified staging package."""

import os
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    absolute,
    canonical,
    digest,
    exact,
    identity,
    protected_directory,
    require,
)
from backend.app.infrastructure.environment_installation import identity_record, sha_value
from backend.app.infrastructure.environment_release_compatibility import compatibility_reference
from backend.app.infrastructure.schema_v22_publish import publish_directory

from .operation_contract import installed_record, path_reference
from .release_artifacts import external_references
from .release_checks import verification_evidence, verification_readiness
from .release_publication import (
    check_bound_candidate,
    checked_root,
    copy_members,
    disjoint,
    observe_candidate,
    publication_inputs,
    verify_fixed_release,
)

POLICY = 'release-finalization-policy.v1.json'
INVALID = 'RELEASE_FINALIZATION_INTENT_MISMATCH'
UNVERIFIED = 'RELEASE_FINALIZATION_UNVERIFIED'
EVIDENCE_REQUIRED = 'RELEASE_FINALIZATION_EVIDENCE_REQUIRED'
CONFLICT = 'RELEASE_FINALIZATION_CONFLICT'


def finalization_inputs(catalog, args, publication, source, output, descriptor, staged_pin):
    path = args.release_finalization_policy
    pin = args.release_finalization_policy_sha256
    require(path.is_absolute() and path.name == POLICY and sha_value(pin), INVALID)
    record = installed_record(path, pin, code=INVALID)
    compatibility = (
        ('additional_compatibility_refs',) if 'additional_compatibility_refs' in record else ()
    )
    plan = exact(
        record,
        (
            'format_version',
            *catalog.scope,
            'release_id',
            'candidate_sha256',
            'staged_manifest_sha256',
            'finalization_root',
            'additional_verification_refs',
            *compatibility,
        ),
        INVALID,
    )
    require(
        type(plan['format_version']) is int
        and plan['format_version'] == 1
        and all(plan[key] == value for key, value in catalog.scope.items())
        and all(plan[key] == publication[key] for key in ('release_id', 'candidate_sha256'))
        and plan['staged_manifest_sha256'] == staged_pin
        and type(plan['additional_verification_refs']) is list
        and type(plan.get('additional_compatibility_refs', [])) is list,
        INVALID,
    )
    location = exact(plan['finalization_root'], ('path', 'identity'), INVALID)
    identity_record(location['identity'], INVALID)
    root = absolute(location['path'], INVALID)
    schema, _ = path_reference(descriptor['schema_ref'])
    require(
        all(
            disjoint(root, reserved)
            for reserved in (
                source,
                output,
                schema,
                catalog.directory,
                args.anchor.parent,
                args.project,
                args.root,
            )
        ),
        INVALID,
    )
    return plan, root


def require_complete_evidence(catalog, manifest, observed, application):
    _, checks = verification_evidence(
        catalog, manifest, {'tree': observed['source_tree']}, application
    )
    readiness = verification_readiness(checks)
    require(readiness['state'] == 'REQUIRED_EVIDENCE_RECORDED', EVIDENCE_REQUIRED)
    return readiness


def prepare_final_build(catalog, registry, args, entry, tool):
    publication, source, output, descriptor, staged_pin = publication_inputs(catalog, args)
    plan, root = finalization_inputs(
        catalog, args, publication, source, output, descriptor, staged_pin
    )
    target = root / plan['release_id']
    published = False
    matched = False
    try:
        with ExitStack() as roots:
            roots.enter_context(checked_root(source, publication['build_root']['identity']))
            roots.enter_context(checked_root(output, publication['publication_root']['identity']))
            root_fd = roots.enter_context(checked_root(root, plan['finalization_root']['identity']))
            observed = observe_candidate(catalog, registry, args, publication, tool, staged=True)
            checked, manifest, program = verify_fixed_release(
                source, staged_pin, args.sha256, entry
            )
            expected = {
                'release_id': plan['release_id'],
                'candidate_sha256': plan['candidate_sha256'],
                'delivery_operation_id': descriptor['delivery_operation_id'],
                'manifest_sha256': staged_pin,
            }
            check_bound_candidate(expected, observed, checked)
            references = [*manifest['verification_refs'], *plan['additional_verification_refs']]
            external_references(references)
            compatibility = list(manifest['compatibility_refs'])
            for reference in plan.get('additional_compatibility_refs', []):
                path, pin = path_reference(reference)
                compatibility.append(
                    compatibility_reference(
                        path,
                        pin,
                        manifest,
                        observed['schema_contract_sha256'],
                        program,
                        code=UNVERIFIED,
                    )
                )
            external_references(compatibility)
            final = {
                **manifest,
                'verification_refs': references,
                'compatibility_refs': compatibility,
            }
            require_complete_evidence(catalog, final, observed, source / 'application')
            raw = canonical(final)
            final_sha = digest(raw)
            if not os.path.lexists(target):
                with TemporaryDirectory(prefix='.finalize-release-', dir=root) as temporary:
                    assembly = Path(temporary) / plan['release_id']
                    assembly.mkdir()
                    copy_members(source, assembly, manifest, staged_pin, output_manifest=raw)
                    require(
                        verify_fixed_release(assembly, final_sha, args.sha256, entry)[2] == program,
                        UNVERIFIED,
                    )
                    require_complete_evidence(catalog, final, observed, assembly / 'application')
                    with checked_root(root, plan['finalization_root']['identity']):
                        try:
                            publish_directory(assembly, target)
                            published = True
                        except FileExistsError:
                            pass
                        if published:
                            with protected_directory(Path(temporary)) as temporary_fd:
                                os.fsync(temporary_fd)
            try:
                require(
                    verify_fixed_release(target, final_sha, args.sha256, entry)[2] == program,
                    CONFLICT,
                )
            except (OSError, ValueError, RuntimeError) as error:
                raise EnvironmentFailure(CONFLICT) from error
            matched = True
            readiness = require_complete_evidence(catalog, final, observed, target / 'application')
            with checked_root(root, plan['finalization_root']['identity']):
                os.fsync(root_fd)
                with protected_directory(target) as target_fd:
                    build_root = {'path': str(target), 'identity': identity(os.fstat(target_fd))}
    except (EnvironmentFailure, OSError, ValueError, KeyError, TypeError) as error:
        if published or matched:
            raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
        raise
    candidate = {
        **descriptor,
        'manifest_ref': {**descriptor['manifest_ref'], 'sha256': final_sha},
    }
    return {
        'status': 'RELEASE_FINAL_BUILD_PREPARED',
        'release_id': plan['release_id'],
        'staged_manifest_sha256': staged_pin,
        'manifest_sha256': final_sha,
        'verification_readiness': readiness,
        'build_root': build_root,
        'candidate': candidate,
        'candidate_sha256': digest(canonical(candidate)),
    }
