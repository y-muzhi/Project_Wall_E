"""Shared fixed TASK binary/protocol/bundle sources; no business or model configuration."""

from dataclasses import dataclass

from backend.app.shared.strict_objects import exact

from .deployment_manifest import absolute_path
from .opencode_binary import OpenCodeBinarySource, open_opencode_binary
from .opencode_protocol_source import verify_opencode_protocol_source
from .opencode_runtime_bundle import OpenCodeRuntimeBundle, hold_opencode_runtime_bundle
from .opencode_task_launch import TaskExecutionError, TaskExecutionPlan


@dataclass(frozen=True)
class TaskDeploymentSources:
    binary: OpenCodeBinarySource
    plan: TaskExecutionPlan


def decode_task_deployment_sources(value):
    value = exact(value, ('executor', 'runtime_bundle', 'execution', 'network'))
    bundle = exact(value['runtime_bundle'], ('manifest', 'root', 'reference'))
    bundle_source = OpenCodeRuntimeBundle(
        absolute_path(bundle['manifest']), absolute_path(bundle['root'])
    )
    plan = TaskExecutionPlan.parse(value['execution'], value['network'], bundle['reference'])
    executor = exact(value['executor'], ('archive', 'image', 'openapi'))
    binary = OpenCodeBinarySource(
        absolute_path(executor['archive']),
        absolute_path(executor['image']),
        plan.binary_ref,
        plan.runtime_bundle_ref,
        openapi=absolute_path(executor['openapi']),
        bundle=bundle_source,
    )
    return TaskDeploymentSources(binary, plan)


def hold_task_deployment_sources(held, source, plan, *, deadline, cancelled):
    """Reuse exact validators and keep image/manifest objects fixed; never run them."""
    if (
        type(source) is not OpenCodeBinarySource
        or type(plan) is not TaskExecutionPlan
        or not source.matches(plan.executor)
        or source.openapi is None
        or source.bundle is None
    ):
        raise TaskExecutionError('ORIGINAL_TASK_PROGRAM_DEPLOYMENT_DIFFERS')
    image = held.enter_context(
        open_opencode_binary(source, plan.executor, deadline=deadline, cancelled=cancelled)
    ).verify()
    verify_opencode_protocol_source(source.openapi, deadline=deadline, cancelled=cancelled)
    held.enter_context(
        hold_opencode_runtime_bundle(
            source.bundle, plan.runtime_bundle_ref, deadline=deadline, cancelled=cancelled
        )
    )
    return image
