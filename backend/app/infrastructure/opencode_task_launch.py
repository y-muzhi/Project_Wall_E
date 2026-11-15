"""Frozen OpenCode launch input and the original executable lease."""

import hashlib
from dataclasses import asdict, dataclass
from time import monotonic

from .guard_task_network import WfpObservationError, _endpoints
from .opencode_binary import VERSION, OpenCodeBinarySource, pin_opencode_binary
from .opencode_runtime_bundle import is_opencode_runtime_bundle_ref
from .runtime_launch_journal import LaunchOutcomeUnknown, _bytes
from .windows_job import MAX_JOB_PROCESSES


class TaskExecutionError(LaunchOutcomeUnknown):
    pass


@dataclass(frozen=True)
class TaskExecutionPlan:
    binary_ref: str
    runtime_bundle_ref: str
    active_process_limit: int
    job_memory_limit_bytes: int
    endpoints: tuple

    @classmethod
    def parse(cls, execution, network, runtime_bundle_ref):
        if type(execution) is not dict or set(execution) != {
            'binary_ref',
            'version',
            'active_process_limit',
            'job_memory_limit_bytes',
        }:
            raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_FIELDS_REQUIRED')
        binary = execution['binary_ref']
        processes, memory = execution['active_process_limit'], execution['job_memory_limit_bytes']
        if (
            execution['version'] != VERSION
            or not is_opencode_runtime_bundle_ref(runtime_bundle_ref)
            or type(binary) is not str
            or not 1 <= len(binary) <= 256
            or binary != binary.strip()
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in binary)
            or type(processes) is not int
            or not 1 <= processes <= MAX_JOB_PROCESSES
            or type(memory) is not int
            or not 1 <= memory <= 0x7FFFFFFFFFFFFFFF
        ):
            raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_INPUT_DIFFERS')
        try:
            endpoints = _endpoints(network)
        except WfpObservationError as error:
            raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_NETWORK_DIFFERS') from error
        for role in ('model', 'control'):
            if len(endpoints[role]) != 1 or endpoints[role][0][0] != '127.0.0.1':
                raise TaskExecutionError('ORIGINAL_TASK_IPV4_INSTANCE_ENDPOINT_REQUIRED')
        return cls(binary, runtime_bundle_ref, processes, memory, tuple(endpoints.items()))

    @property
    def network(self):
        return dict(self.endpoints)

    @property
    def arguments(self):
        _, port = self.network['control'][0]
        return ('serve', '--hostname', '127.0.0.1', '--port', str(port), '--no-mdns')

    @property
    def executor(self):
        return {
            'version': VERSION,
            'binary_ref': self.binary_ref,
            'runtime_bundle_ref': self.runtime_bundle_ref,
        }


class TaskProgramOwner:
    def __init__(self, source, plan):
        if (
            type(source) is not OpenCodeBinarySource
            or type(plan) is not TaskExecutionPlan
            or not source.matches(plan.executor)
        ):
            raise TaskExecutionError('ORIGINAL_TASK_PROGRAM_DEPLOYMENT_DIFFERS')
        self._source, self.plan = source, plan
        self._image = self._evidence = None
        self._started = False

    def prepare(self, *, deadline, cancelled):
        if self._started:
            raise TaskExecutionError('ORIGINAL_TASK_PROGRAM_ALREADY_PINNED')
        self._started = True
        self._image = pin_opencode_binary(
            self._source,
            self.plan.executor,
            deadline=deadline,
            cancelled=cancelled,
        )
        if cancelled() or monotonic() >= deadline:
            raise TaskExecutionError('ORIGINAL_TASK_PROGRAM_INTERRUPTED')
        self._evidence = self._inspect()
        return self._evidence

    def _inspect(self):
        identity = self._image.verify()
        return hashlib.sha256(
            _bytes(
                {
                    'executor': self.plan.executor,
                    'image': asdict(identity),
                    'arguments': self.plan.arguments,
                }
            )
        ).hexdigest()

    def verify(self):
        if self._evidence is None or self._inspect() != self._evidence:
            raise TaskExecutionError('ORIGINAL_TASK_PROGRAM_EVIDENCE_UNVERIFIED')
        return self._evidence

    def close(self):
        if self._image is not None:
            self._image.close()
            self._image = None
            self._evidence = None
