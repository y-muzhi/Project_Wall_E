import type {ComposerState} from './composer.ts';
import {ordinaryInput} from '../shared/text.ts';

const effects={
 DISCUSS:'仅讨论，不修改文档。',GENERATE:'生成后直接保存为新文档，初始版本为未确认。',
 REVISE:'修订成功后保存为新版本，原版本保留。',PROPOSE_CHANGES:'先提出修改建议，审阅并完成后才写入文档。',
 COMPARE:'只对照分析所选材料，不修改文档。',REVIEW:'只检查所选材料，不修改文档。',
};
/** Presentation only. The owner and server remain the send permission gates. */
export function composerFeedback(state:ComposerState,available:boolean,allowed:boolean):Readonly<{effect:string;blocked:string|null;configure:boolean}>{
 const effect=effects[state.action],result=(blocked:string|null,configure=false)=>({effect,blocked,configure});
 if(state.phase==='UNKNOWN')return result('发送结果待核实，请先核实原请求。');
 if(['SUBMITTING','READING','CONFIRMED'].includes(state.phase))return result('正在处理本次请求，请稍候。');
 if(state.needs_refresh)return result('当前状态已变化，请先重新读取状态。');
 const occupancy=state.detail.requirement.document_work_state;
 if(occupancy==='MANUAL_EDITING')return result('请先完成或取消人工编辑，再发送 AI 请求。');
 if(occupancy==='SUGGESTION_REVIEWING')return result('请先完成或放弃当前修改建议，再发送 AI 请求。');
 if(occupancy==='GUIDE_ACTIVE')return result('AI 正在处理上一轮请求，请等待结束。');
 if(!available)return result('当前操作暂不可用，请等待状态同步完成。');
 if(state.action==='GENERATE'){
  try{ordinaryInput(state.new_target.name,'文档名称',1,80,false);}catch{return result('请先填写有效的新文档名称（1～80 个字符）。',true);}
 }
 if(['REVISE','PROPOSE_CHANGES'].includes(state.action)&&state.target===null)return result('请先选择本次要修改的目标文档。',true);
 if(['COMPARE','REVIEW'].includes(state.action)&&state.target===null&&state.source_refs.length===0)return result('请先选择工作目标或参考文档。',true);
 if(!allowed)return result('目标或来源已变化，请核对操作设置后再发送。',true);
 return result(null);
}
