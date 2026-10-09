import {mountFormatProbe,mountInitializationFormatProbe} from './format-probe.ts';

/** Isolated in-memory inputs. No business API, storage, autosave or model calls. */
async function mount(initializing=false){
  const probe=initializing?await mountInitializationFormatProbe():await mountFormatProbe('# 测试标题\n\n正文测试\n\n插入位置\n');
  const controls=document.createElement('section');controls.setAttribute('aria-label','隔离编辑器检查控制');
  const output=document.createElement('pre');output.setAttribute('role','status');output.setAttribute('aria-label','编辑器检查状态');
  const button=(name:string,action:()=>void)=>{const element=document.createElement('button');element.type='button';element.className='ui-button';element.textContent=name;element.addEventListener('click',action);controls.append(element);};
  button('测试选中正文',()=>probe.select(initializing?'待确认。':'正文测试'));
  button('测试选中插入位置',()=>probe.select(initializing?'待确认。':'插入位置'));
  button('测试选中标题',()=>probe.select(initializing?'背景与目标':'测试标题'));
  button('冻结测试编辑器',()=>probe.readonly(true));button('恢复测试编辑器',()=>probe.readonly(false));
  button('重置普通测试文档',()=>{clearInterval(timer);void probe.destroy().then(()=>mount());});
  button('重置初始化测试文档',()=>{clearInterval(timer);void probe.destroy().then(()=>mount(true));});
  document.body.prepend(controls);document.body.append(output);document.body.style.margin='24px';
  const timer=setInterval(()=>{const state=probe.state();output.textContent=`有效：${state.valid}；只读：${state.readonly}；离开编辑器：${state.blurs}；错误：${state.error??'无'}\n${state.markdown}`;},100);
}
void mount();
