import {useLayoutEffect,useRef,useState} from 'react';
import {LayoutMotion,motionTiming,reducedMotion} from './motion.ts';

export function useLayoutMotion():LayoutMotion{
 const ref=useRef<LayoutMotion|null>(null);if(ref.current===null)ref.current=new LayoutMotion();
 useLayoutEffect(()=>{const motion=ref.current!;motion.activate();return()=>motion.dispose();},[]);return ref.current;
}
/** Keep only the visual shell briefly. Callers must immediately make a closed
 * region inert/aria-hidden and stop its reads; closing is not a new authority. */
export function useMotionPresence(open:boolean,duration:number=motionTiming.overlay):boolean{
 const [retained,setRetained]=useState(open);
 useLayoutEffect(()=>{
  if(open){setRetained(true);return;}
  if(reducedMotion(window)){setRetained(false);return;}
  const media=window.matchMedia('(prefers-reduced-motion: reduce)'),finish=()=>{if(media.matches)setRetained(false);};
  const timer=window.setTimeout(()=>setRetained(false),duration);media.addEventListener('change',finish);
  return()=>{window.clearTimeout(timer);media.removeEventListener('change',finish);};
 },[open,duration]);return open||retained;
}
