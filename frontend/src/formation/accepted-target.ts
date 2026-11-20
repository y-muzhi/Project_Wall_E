import type { GuideSummary } from '../api/models.ts';
/** Immutable public Run target; never the user's later next-round draft. */
export function acceptedReplyTarget(run: GuideSummary): string | null {
  if (!('accepted_target' in run)) return null;
  const target = run.accepted_target;
  const step =
    target.discussion_step_ref === null ? '整份文档' : '步骤 ' + target.discussion_step_ref;
  return (
    '本条回复：' +
    step +
    (target.discussion_branch_ref === null ? '' : ' · 支线 ' + target.discussion_branch_ref)
  );
}
