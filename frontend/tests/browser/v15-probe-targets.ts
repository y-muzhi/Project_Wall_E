/** Explicit integration-test fixtures, never a production API adapter. A
 * driver must select an actual requirement/document pair before invoking a
 * document probe. Missing setup fails; no first-CURRENT lookup is permitted. */
import {positiveInteger} from '../../src/api/client.ts';
import type {CreateGuide,WalleApi} from '../../src/api/walle.ts';
import {assertDocumentDetail} from '../../src/requirements/detail-read.ts';
import type {DetailSnapshot,DocumentDetailSnapshot} from '../../src/requirements/detail-read.ts';
import type {RecoveryBinding} from '../../src/documents/recovery-store.ts';

const documents=new Map<number,number>(),drafts=new Map<string,number>();
const bases=new Map<string,number>();
let activeRequirement:number|null=null;
export function configureProbeDocument(requirement:number,document:number):void{documents.set(positiveInteger(requirement),positiveInteger(document));activeRequirement=requirement;}
export function probeDocumentId(requirement:number):number{const identity=documents.get(positiveInteger(requirement));if(identity===undefined)throw Error('Configure the actual V1.5 requirement/document fixture before this probe');return identity;}
export function probeDraftId(requirement:number):number{const identity=drafts.get(JSON.stringify([requirement,probeDocumentId(requirement)]));if(identity===undefined)throw Error('Read or create the actual bound draft before this probe');return identity;}
export function observeProbeData(value:unknown):void{
 if(value===null||typeof value!=='object'||Array.isArray(value))return;
 const row=value as Record<string,unknown>,candidate=row.manual_draft??row;
 if(candidate===null||typeof candidate!=='object'||Array.isArray(candidate))return;
 const draft=candidate as Record<string,unknown>;if(draft.document_type!=='MANUAL_DRAFT')return;
 const req=positiveInteger(draft.requirement_id),target=positiveInteger(draft.target_document_id),identity=positiveInteger(draft.id);
 if(documents.get(req)!==target)throw Error('The returned draft belongs to a different configured document');drafts.set(JSON.stringify([req,target]),identity);bases.set(JSON.stringify([req,target]),positiveInteger(draft.base_content_version));
}
export function probeRecoveryBinding():RecoveryBinding{
 if(activeRequirement===null)throw Error('Configure an explicit edit fixture for this recovery probe');
 const entry:[number,number]=[activeRequirement,probeDocumentId(activeRequirement)];const key=JSON.stringify(entry),draft=drafts.get(key),base=bases.get(key);
 if(draft===undefined||base===undefined)throw Error('Observe the actual bound draft before opening its recovery store');
 return {requirement_id:entry[0],target_document_id:entry[1],manual_draft_id:draft,base_content_version:base};
}
type SelectedProbeDetail=DocumentDetailSnapshot&{comment_index:NonNullable<DetailSnapshot['comment_index']>};
function assertSelectedIndex(value:DocumentDetailSnapshot):asserts value is SelectedProbeDetail{if(value.comment_index===null)throw Error('The selected document index must be read in this fixture');}
export function probeDocumentDetail(value:DetailSnapshot):SelectedProbeDetail{assertDocumentDetail(value);assertSelectedIndex(value);return value;}
/** Formal commit followed by a separate actual GET. This helper does not
 * manufacture a DocumentView from the command's DocumentEffect. */
export function probeCompleteAction(api:WalleApi,requirement:number,version:number){
 const document=probeDocumentId(requirement),draft=probeDraftId(requirement),action=api.prepareCompleteManualDraft(requirement,document,draft,version);
 return {async submit(){const effect=(await action.submit()).data;const actual=await api.getCurrentDocument(requirement,document);if(actual.data.content_version!==effect.after_content_version)throw Error('The actual committed document changed before the probe read');return actual;}};
}

/** The diagnostic driver reads the real discussion version and supplies its
 * configured document; it cannot infer a target from a display selection. */
export async function probeGuideBody(api:WalleApi,requirement:number,operation:CreateGuide['operation'],version:number,instruction:string):Promise<CreateGuide>{
 const root=(await api.getRequirement(requirement)).data;
 return {expected_discussion_version:root.discussion_version,operation,instruction,
  target:{kind:'EXISTING',document_id:probeDocumentId(requirement),expected_content_version:version},
  scope:{scope_type:'DOCUMENT',scope_ref:null},source_refs:[],proposal_ref:null,acknowledge_source_changes:false};
}
