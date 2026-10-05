import type {DetailSnapshot} from './detail-read.ts';

/** Conditions from FE/APP-REQ. They never replace the native transaction's
 * checks. Title deliberately has no IDLE condition; mode does. */
export function detailPermissions(snapshot:DetailSnapshot|null,ready:boolean,blocked=false,history=false){
  const usable=!!snapshot&&ready&&!blocked&&!history,root=snapshot?.requirement;
  const initializing=root?.status==='INITIALIZING',active=root?.status==='ACTIVE',completed=root?.status==='COMPLETED',idle=root?.document_work_state==='IDLE';
  return Object.freeze({title:usable&&(initializing||active),mode:usable&&initializing&&idle,
    complete_initialization:usable&&initializing&&idle,complete_requirement:usable&&active&&idle,reactivate:usable&&completed&&idle,
    manual_start:usable&&(initializing||active)&&idle,initialize:usable&&initializing&&idle,
    ask:usable&&(active||completed)&&idle,review:usable&&active&&idle,modify:usable&&active&&idle,
    comment_write:usable&&active&&idle,revision_save:usable&&active&&idle});
}
