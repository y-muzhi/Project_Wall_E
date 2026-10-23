import type {GuideRun} from '../api/models.ts';

type Analysis=NonNullable<NonNullable<GuideRun['final_result']>['analysis']>;
const conclusions={RESULT:'分析完成',NO_CHANGE:'无需修改',NEED_EVIDENCE:'需要补充依据',INCOMPLETE:'分析未完成'};
const severities={INFO:'说明',WARNING:'注意',CONFLICT:'冲突'};
/** Read only the validated result saved by this run; no inferred conclusions. */
export function AnalysisResult({value}:Readonly<{value:Analysis}>){
 const {findings,unresolved,covered_refs:covered}=value;
 return <section aria-label="分析结果">
  <p><strong>{conclusions[value.conclusion]}</strong></p><p>{value.summary}</p>
  {findings.length>0&&<><h4>检查结果</h4><ul>{findings.map(item=><li key={item.ref}><strong>{severities[item.severity]}：</strong>{item.message}{item.source_refs.length>0&&<p>相关材料：{item.source_refs.join('、')}</p>}</li>)}</ul></>}
  {unresolved.length>0&&<><h4>未决事项</h4><ul>{unresolved.map(item=><li key={item.ref}>{item.description}<p>影响：{item.impact}</p>{item.source_refs.length>0&&<p>相关材料：{item.source_refs.join('、')}</p>}</li>)}</ul></>}
  <p>覆盖材料：{covered.length?covered.join('、'):'未声明具体材料'}</p>
 </section>;
}
