import {ApiRejected} from '../../src/api/client.ts';
import type {WalleApi} from '../../src/api/walle.ts';
import {require} from '../../src/api/decoding.ts';

/** This entry writes isolated creations only when explicitly invoked. */
export async function readLimitsProbe(api:WalleApi){
 const created=(await api.prepareCreateRequirement({title:'😀'.repeat(20),requirement_type:'CHANGE',initial_idea:'😀'.repeat(10000)}).submit()).data;
 require(created.documents.length===0&&created.requirement.title==='😀'.repeat(20));
 for(const changes of [{title:'😀'.repeat(21)},{initial_idea:'😀'.repeat(10001)}]){
  try{await api.prepareCreateRequirement({title:'边界诊断',requirement_type:'CHANGE',initial_idea:'隔离数据',...changes}).submit();throw Error('Expected actual native rejection');}
  catch(error){require(error instanceof ApiRejected&&error.code==='VALIDATION_FAILED');}
 }
 return {passed:true,identity:created.requirement.id,scope:'V1.5 native title/initial idea codepoint bounds; no automatic draft or model'};
}
