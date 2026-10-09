import {normalizeOrdinary,ordinaryInput} from '../shared/text.ts';

/** UI feedback follows the exact send validator; it never prepares a request. */
export function instructionFeedback(value:string):Readonly<{length:number;valid:boolean;error:string|null}>{
  let length=0;
  try{length=[...normalizeOrdinary(value)].length;}catch{return {length,valid:false,error:'请输入有效的 Unicode 文本'};}
  try{ordinaryInput(value,'AI 指令',1,10000);return {length,valid:true,error:null};}
  catch(error){return {length,valid:false,error:length===0&&error instanceof Error&&error.message==='请填写此项'?'请输入消息后发送。':error instanceof Error?error.message:'请输入有效文本'};}
}
