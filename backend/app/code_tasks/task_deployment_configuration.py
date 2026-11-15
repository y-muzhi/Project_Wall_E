"""Decode a trusted local TASK resource group without creating OS resources."""

from dataclasses import replace

from backend.app.infrastructure.task_deployment_sources import (
    decode_task_deployment_sources,
    hold_task_deployment_sources,
)
from backend.app.shared.strict_objects import exact
from backend.app.shared.validation import strict_integer

from .task_initial_prompt import NativeCodingPolicy
from .task_instance_driver import TaskLaunchInstallation


def decode_task_deployment(value, registration):
    from backend.app.infrastructure.deployment_manifest import LocalDeploymentError, digest

    value = exact(
        value,
        (
            'executor',
            'runtime_bundle',
            'execution',
            'network',
            'configuration_sha256',
            'startup_timeout_ms',
            'max_diagnostic_output_bytes',
            'agent_ref',
        ),
    )
    if registration.workspace_root is None:
        raise LocalDeploymentError('CODE_DEPLOYMENT_TASK_WORKSPACE_REQUIRED')
    sources = decode_task_deployment_sources(
        {name: value[name] for name in ('executor', 'runtime_bundle', 'execution', 'network')}
    )
    binary, plan = sources.binary, sources.plan
    agent = value['agent_ref']
    if (
        type(agent) is not str
        or not agent
        or len(agent) > 256
        or agent.strip() != agent
        or any(ord(character) < 32 or ord(character) == 127 for character in agent)
    ):
        raise LocalDeploymentError('CODE_DEPLOYMENT_AGENT_REQUIRED')
    launch = TaskLaunchInstallation(
        plan,
        digest(value['configuration_sha256']),
        strict_integer(value['startup_timeout_ms'], 'startup_timeout_ms'),
        coding=NativeCodingPolicy(agent, (('*', '*', 'deny'),)),
        max_diagnostic_output_bytes=strict_integer(
            value['max_diagnostic_output_bytes'], 'max_diagnostic_output_bytes'
        ),
    )
    return replace(registration, executor_binary=binary, task_launch=launch)


def hold_task_deployment(held, installation, *, deadline):
    """Pin fixed binary and manifest, inspect complete bytes; never execute or install."""
    if installation.task_launch is None:
        return
    hold_task_deployment_sources(
        held,
        installation.executor_binary,
        installation.task_launch.plan,
        deadline=deadline,
        cancelled=lambda: False,
    )
