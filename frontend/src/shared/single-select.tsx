import {useLayoutEffect,useRef} from 'react';
import {createSingleSelect} from './single-select.ts';
import type {SingleSelectConfig} from './single-select.ts';

export function SingleSelect(props:SingleSelectConfig){
  const host=useRef<HTMLSpanElement>(null),control=useRef<ReturnType<typeof createSingleSelect>|null>(null);
  useLayoutEffect(()=>{
    const instance=createSingleSelect(host.current!.ownerDocument,props);control.current=instance;host.current!.append(instance.element);
    return ()=>{instance.destroy();control.current=null;};
    // The DOM owner is stable; controlled updates below refresh callbacks too.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[]);
  useLayoutEffect(()=>{control.current?.update(props);});
  return <span className="single-select-host" ref={host}/>;
}
