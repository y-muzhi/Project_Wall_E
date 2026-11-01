import assert from 'node:assert/strict';
import test from 'node:test';
import { DisclosureMotion } from '../src/shared/disclosure-motion.ts';
import { motionTiming } from '../src/shared/motion.ts';

function fixture(count=1) {
 const media=Object.assign(new EventTarget(),{matches:false}),frames=new Map(),animations=[];
 let frameId=0,moved=0;
 const browser=Object.assign(new EventTarget(),{matchMedia:()=>media,requestAnimationFrame:callback=>{frames.set(++frameId,callback);return frameId;},cancelAnimationFrame:id=>frames.delete(id),getComputedStyle:element=>({display:element.hidden?'none':'block',getPropertyValue:property=>element.displayed?.[property]??element.natural[property]})});
 const elements=Array.from({length:count},()=>({ownerDocument:{defaultView:browser},isConnected:true,hidden:false,displayed:null,natural:{height:'84px','margin-top':'12px','margin-bottom':'16px','padding-top':'4px','padding-bottom':'4px','border-top-width':'1px','border-bottom-width':'1px',opacity:'1'},animate(keyframes,options){
  let resolve,reject;const element=this,finished=new Promise((yes,no)=>{resolve=yes;reject=no;});
  const animation={keyframes,options,finished,cancelled:false,cancel(){this.cancelled=true;element.displayed=null;reject(Error('cancelled'));},finish(){resolve();}};
  animations.push(animation);return animation;
 }}));
 const motion=new DisclosureMotion();
 return {motion,elements,animations,media,browser,frames,get moved(){return moved;},run(collapsed,enabled=true){motion.run(elements.map(element=>({element,collapsed})),active=>{for(const element of elements)element.hidden=!active&&collapsed;},()=>moved++,enabled);},flush(){const jobs=[...frames.values()];frames.clear();jobs.forEach(job=>job());}};
}

test('measured tracks collapse and expand with final visibility and no retained animation overrides',async()=>{
 const f=fixture();f.run(true);
 assert.equal(f.elements[0].hidden,false);assert.equal(f.animations[0].keyframes[0].height,'84px');assert.equal(f.animations[0].keyframes[1].height,'0px');
 assert.equal(f.animations[0].keyframes[1].marginTop,'0px');assert.equal(f.animations[0].options.duration,motionTiming.disclosure);
 f.flush();assert.equal(f.moved,1);f.animations[0].finish();await Promise.resolve();
 assert.equal(f.elements[0].hidden,true);assert.equal(f.animations[0].cancelled,true);assert.equal(f.frames.size,0);
 f.run(false);assert.equal(f.animations[1].keyframes[0].height,'0px');assert.equal(f.animations[1].keyframes[1].height,'84px');
 f.animations[1].finish();await Promise.resolve();assert.equal(f.elements[0].hidden,false);assert.equal(f.animations[1].cancelled,true);f.motion.dispose();
});

test('rapid reversal samples the current interpolated size and ignores obsolete completion',async()=>{
 const f=fixture();f.run(true);f.elements[0].displayed={height:'41px',opacity:'.4','margin-top':'5px'};
 f.run(false);assert.equal(f.animations[0].cancelled,true);assert.equal(f.animations[1].keyframes[0].height,'41px');assert.equal(f.animations[1].keyframes[0].marginTop,'5px');
 await Promise.resolve();assert.equal(f.animations[1].cancelled,false);f.motion.dispose();assert.equal(f.frames.size,0);
});

test('multiple tracks retain their endpoint until all finish, then release every filled animation',async()=>{
 const f=fixture(2);f.run(true);f.animations[0].finish();await Promise.resolve();
 assert.equal(f.animations[0].cancelled,false);assert.equal(f.elements[0].hidden,false);
 f.animations[1].finish();await Promise.resolve();assert(f.animations.every(animation=>animation.cancelled));assert(f.elements.every(element=>element.hidden));assert.equal(f.frames.size,0);f.motion.dispose();
});

test('an already hidden track stays at zero while another interrupted track finishes',async()=>{
 const f=fixture(2);f.elements[1].hidden=true;f.run(true);
 assert.equal(f.animations.length,2);assert.equal(f.animations[1].keyframes[0].height,'0px');assert.equal(f.animations[1].keyframes[1].height,'0px');
 f.animations.forEach(animation=>animation.finish());await Promise.resolve();assert(f.elements.every(element=>element.hidden));assert(f.animations.every(animation=>animation.cancelled));f.motion.dispose();
});

test('reduced motion and viewport changes settle immediately and cancel all queued frame ownership',async()=>{
 const f=fixture();f.media.matches=true;f.run(true);assert.equal(f.animations.length,0);assert.equal(f.elements[0].hidden,true);
 f.media.matches=false;f.run(false);f.media.matches=true;f.media.dispatchEvent(new Event('change'));
 assert.equal(f.animations[0].cancelled,true);assert.equal(f.elements[0].hidden,false);assert.equal(f.frames.size,0);
 f.media.matches=false;f.run(true);f.browser.dispatchEvent(new Event('resize'));assert.equal(f.elements[0].hidden,true);assert.equal(f.frames.size,0);
 await Promise.resolve();f.motion.dispose();
});

test('unsupported, failed or disabled motion still applies visibility; disposal suppresses late callbacks',async()=>{
 for(const mode of ['missing','throw','disabled','detached']) {
  const f=fixture();if(mode==='missing')f.elements[0].animate=undefined;if(mode==='throw')f.elements[0].animate=()=>{throw Error('unsupported');};if(mode==='detached')f.elements[0].isConnected=false;
  f.run(true,mode!=='disabled');assert.equal(f.elements[0].hidden,true);assert.equal(f.frames.size,0);f.motion.dispose();
 }
 const f=fixture();f.run(true);f.motion.dispose();const moved=f.moved;f.animations[0].finish();await Promise.resolve();f.flush();assert.equal(f.moved,moved);assert.equal(f.frames.size,0);
});
