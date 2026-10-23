import type {DetailSnapshot} from './detail-read.ts';

/** Conditions from FE/APP-REQ. They never replace the native transaction's
 * checks. Title deliberately has no IDLE condition; mode is creation-only. */
export function detailPermissions(snapshot:DetailSnapshot|null,ready:boolean,blocked=false,history=false){
  const usable=!!snapshot&&ready&&!blocked&&!history,root=snapshot?.requirement;
  const idle=root?.document_work_state==='IDLE',document=snapshot?.current,maintain=!!document&&document.archived_at===null;
  return Object.freeze({title:usable,mode:false,
    complete_initialization:false,complete_requirement:false,reactivate:false,
    manual_start:usable&&maintain&&idle,initialize:false,
    ask:usable&&idle,review:usable&&idle,modify:usable&&idle,
    comment_write:usable&&maintain&&idle,revision_save:usable&&maintain&&idle});
}
