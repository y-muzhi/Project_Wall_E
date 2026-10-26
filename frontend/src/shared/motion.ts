/** M15-MOTION-01: visual transitions never own a business state or permission. */
export const motionTiming=Object.freeze({layout:220,disclosure:180,overlay:160,easing:'cubic-bezier(.2,.8,.2,1)'});
export type MotionTarget=Readonly<{element:HTMLElement|null;properties:readonly string[]}>;
export function reducedMotion(browser:Pick<Window,'matchMedia'>):boolean{return browser.matchMedia('(prefers-reduced-motion: reduce)').matches;}
/** Native DOM controls use the same immediate interaction boundary as React
 * shells. CSS owns the visual exit; repeated editor updates do not restart it. */
export function setMotionOpen(element:HTMLElement,open:boolean):void{
 element.inert=!open;element.setAttribute('aria-hidden',String(!open));
 if(element.hidden!==!open)element.hidden=!open;
}
const animationProperty=(property:string)=>property.startsWith('--')?property:property.replace(/-([a-z])/g,(_match,letter:string)=>letter.toUpperCase());

/** Sample before cancelling, so a rapid reversal starts at the displayed size.
 * All geometry is pixels computed by the browser: no text scaling/FLIP blur. */
export class LayoutMotion {
 private frame:number|undefined;private browser:Window|undefined;private media:MediaQueryList|undefined;
 private animations=new Map<HTMLElement,Animation>();private generation=0;private closed=false;
 private readonly preference=()=>{if(this.media?.matches)this.cancel();};
 private readonly resized=()=>this.cancel();
 activate():void{this.closed=false;}
 cancel():void{this.generation++;if(this.frame!==undefined)this.browser?.cancelAnimationFrame(this.frame);this.frame=undefined;
  for(const animation of this.animations.values())animation.cancel();this.animations.clear();}
 run(targets:readonly MotionTarget[],change:()=>void,enabled=true):void{
  if(this.closed){change();return;}
  const actual=targets.filter((target):target is {element:HTMLElement;properties:readonly string[]}=>target.element!==null),browser=actual[0]?.element.ownerDocument.defaultView;
  if(!browser){change();return;}
  if(this.browser!==browser){this.media?.removeEventListener('change',this.preference);this.browser?.removeEventListener('resize',this.resized);this.browser=browser;this.media=browser.matchMedia('(prefers-reduced-motion: reduce)');this.media.addEventListener('change',this.preference);browser.addEventListener('resize',this.resized);}
  const before=actual.map(target=>({target,values:Object.fromEntries(target.properties.map(property=>[animationProperty(property),browser.getComputedStyle(target.element).getPropertyValue(property)]))}));
  this.cancel();change();if(!enabled||this.media?.matches)return;
  const generation=this.generation;
  this.frame=browser.requestAnimationFrame(()=>{this.frame=undefined;if(this.closed||generation!==this.generation||this.media?.matches)return;
   for(const {target,values} of before){const element=target.element;if(!element.isConnected||typeof element.animate!=='function')continue;
    const after=Object.fromEntries(target.properties.map(property=>[animationProperty(property),browser.getComputedStyle(element).getPropertyValue(property)]));
    if(Object.keys(values).every(property=>values[property]===after[property]))continue;
    const animation=element.animate([values,after],{duration:motionTiming.layout,easing:motionTiming.easing});this.animations.set(element,animation);
    void animation.finished.then(()=>{if(this.animations.get(element)===animation)this.animations.delete(element);},()=>{if(this.animations.get(element)===animation)this.animations.delete(element);});
   }
  });
 }
 dispose():void{this.closed=true;this.cancel();this.media?.removeEventListener('change',this.preference);this.browser?.removeEventListener('resize',this.resized);this.media=undefined;this.browser=undefined;}
}
