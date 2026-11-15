import { useState } from 'react';
import { positiveInteger } from '../api/client.ts';
import type { CodeTaskView } from '../api/code-task-creation.ts';
import { testingAuthorizationPath } from '../api/testing-policy.ts';
import { testingTasksPath } from '../api/testing-tasks.ts';
import type { WalleApi } from '../api/walle.ts';
import { CreateTestingTaskDrawer } from '../testing/create-task.tsx';
import type { CreationReceipt } from '../testing/create-task.tsx';
import { OriginalTaskRequests, useTestingRecovery } from '../testing/task-recovery.tsx';

export function CreateTestingFromCandidate({
  api,
  task,
  ready,
}: Readonly<{
  api: WalleApi;
  task: CodeTaskView;
  ready: boolean;
}>) {
  const [open, setOpen] = useState(false);
  const [received, setReceived] = useState<CreationReceipt | null>(null);
  const access = useTestingRecovery(
    api,
    (record) => record.path === testingTasksPath || record.path === testingAuthorizationPath,
    (record, result) => {
      const outcome = result.original_receipt?.original_outcome;
      if (outcome?.success !== true) return;
      setReceived(
        record.path === testingTasksPath
          ? {
              key: record.key,
              kind: 'create',
              id: positiveInteger((outcome.data as { testing_task_id: number }).testing_task_id),
            }
          : {
              key: record.key,
              kind: 'approve',
              id: positiveInteger((outcome.data as { id: number }).id),
            },
      );
    },
  );
  const candidate = task.current_candidate_id;
  return (
    <>
      <div className="code-task-toolbar">
        <button
          type="button"
          className="ui-button"
          disabled={!ready || candidate === null}
          title={!ready ? '正在核对当前候选' : undefined}
          onClick={() => setOpen(true)}
        >
          从此候选创建独立测试
        </button>
      </div>
      <OriginalTaskRequests access={access} />
      {open && candidate !== null && (
        <CreateTestingTaskDrawer
          api={api}
          access={access}
          received={received}
          pinned={{
            task: task.id,
            candidate,
            requirement_id: task.requirement_id,
            document_id: task.document_id,
            design_revision_id: task.design_revision_id,
            material_refs: task.material_refs,
          }}
          close={() => setOpen(false)}
          created={(id) => window.location.assign('/testing/tasks/' + id)}
        />
      )}
    </>
  );
}
