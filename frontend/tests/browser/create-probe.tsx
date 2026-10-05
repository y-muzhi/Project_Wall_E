import { useCallback, useEffect, useState, useSyncExternalStore } from 'react';
import { createRoot } from 'react-dom/client';
import type { WalleApi } from '../../src/api/walle.ts';
import { ApiUnknown } from '../../src/api/client.ts';
import { CreateRequirementFlow } from '../../src/requirements/create.ts';
import { CreateRequirementDrawer } from '../../src/requirements/create_drawer.tsx';
import { Confirmation } from '../../src/shared/confirmation.tsx';
import { ToastViewport } from '../../src/shared/toast.tsx';
import { ToastStore } from '../../src/shared/toast-store.ts';
import { require } from '../../src/api/decoding.ts';
import '../../src/shared/styles.css';

/** Explicit diagnostic response loss AFTER actual native 201, never a mock DB/API. */
export function mountCreateProbe(api: WalleApi) {
  const element = document.createElement('section'); element.id = 'native-create-probe'; document.body.append(element);
  const root = createRoot(element), toast = new ToastStore(); let prepared = 0, submissions = 0, dropped = false;
  let active: CreateRequirementFlow;
  const port: Pick<WalleApi,'prepareCreateRequirement'> = { prepareCreateRequirement(body) {
    prepared++; const original = api.prepareCreateRequirement(body);
    return Object.freeze({ submit: async () => {
      submissions++; const result = await original.submit();
      if (!dropped) { dropped = true; throw new ApiUnknown(true); } return result;
    } });
  } };
  const make = () => new CreateRequirementFlow(port);
  function App() {
    const [flow,setFlow] = useState(make), [open,setOpen] = useState(false), [discard,setDiscard] = useState(false);
    active = flow;
    const subscribe = useCallback((notify: () => void) => flow.subscribe(notify),[flow]);
    const state = useSyncExternalStore(subscribe,() => flow.state);
    useEffect(() => { if (state.result) { setOpen(false); toast.push('success','需求创建成功'); } },[state.result]);
    const cancel = () => { if (state.busy || state.unknown) return; if (flow.hasInput) setDiscard(true); else setOpen(false); };
    return <main style={{padding:24}}><h2>真实创建抽屉诊断</h2><p>正式 API / SQLite，首次实际成功响应在本地丢弃；不调用 Provider。</p>
      <button type="button" data-focus-fallback onClick={() => setOpen(true)}>打开新建诊断</button>
      <CreateRequirementDrawer open={open} state={state} edit={draft => flow.edit(draft)} create={() => { void flow.submit(); }} cancel={cancel} />
      <Confirmation open={discard} title="放弃新建需求？" description="尚未提交的输入将被清空。" busy={false} cancel={() => setDiscard(false)}
        confirmLabel="放弃输入" confirm={() => { flow.dispose(); setFlow(make()); setDiscard(false); setOpen(false); }} />
      <ToastViewport store={toast} />
    </main>;
  }
  root.render(<App />);
  return {
    state: () => ({state:active?.state,prepared,submissions,dropped,overflow:document.body.style.overflow}),
    async inspect() {
      const result=active.state.result; require(result !== null && prepared === 1 && submissions === 2 && dropped);
      const [current,list]=await Promise.all([api.getRequirement(result.requirement.id),api.listRequirements({keyword:'真实抽屉😀'})]);
      require(list.data.items.length === 1 && list.data.items[0]!.id === result.requirement.id && current.data.title === '真实抽屉😀');
      return {passed:true,id:result.requirement.id,guide_run_id:result.guide_run_id,prepared,submissions,dropped,actual_list_count:list.data.items.length,
        scope:'Actual native 201 discarded locally then exact original action replay; no Provider or whole product acceptance'};
    },
    destroy() { active.dispose(); toast.dispose(); root.unmount(); element.remove(); },
  };
}
