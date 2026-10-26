import {test} from 'node:test';
import assert from 'node:assert/strict';
import {LayoutMotion,motionTiming} from '../src/shared/motion.ts';

function fixture(){
 const media=new EventTarget();media.matches=false;const frames=new Map(),animations=[];let next=0;
 const browser=Object.assign(new EventTarget(),{matchMedia:()=>media,requestAnimationFrame:fn=>{frames.set(++next,fn);return next;},cancelAnimationFrame:id=>frames.delete(id),getComputedStyle:el=>({getPropertyValue:name=>(el.displayed??el.style)[name]??''})});
 const element={ownerDocument:{defaultView:browser},isConnected:true,style:{width:'200px'},displayed:null,animate(keyframes,options){let resolve,reject;const finished=new Promise((a,b)=>{resolve=a;reject=b;});const animation={keyframes,options,finished,cancelled:false,cancel(){this.cancelled=true;element.displayed=null;reject(new Error('cancelled'));},finish(){resolve();}};animations.push(animation);return animation;}};
 const motion=new LayoutMotion(),targets=[{element,properties:['width']}],flush=()=>{const jobs=[...frames.values()];frames.clear();jobs.forEach(fn=>fn());};
 return {motion,element,targets,media,browser,frames,animations,flush};
}
test('one shared layout transition captures actual CSS sizes and settles without retaining a visual override',async()=>{
 const f=fixture();f.motion.run(f.targets,()=>{f.element.style.width='64px';});assert.equal(f.element.style.width,'64px');f.flush();
 assert.deepEqual(f.animations[0].keyframes,[{width:'200px'},{width:'64px'}]);assert.equal(f.animations[0].options.duration,motionTiming.layout);
 f.animations[0].finish();await Promise.resolve();f.motion.dispose();assert.equal(f.animations[0].cancelled,false);
});
test('rapid reversal samples the displayed position before cancellation and old completion cannot cancel the new animation',async()=>{
 const f=fixture();f.motion.run(f.targets,()=>{f.element.style.width='64px';});f.flush();f.element.displayed={width:'137px'};
 f.motion.run(f.targets,()=>{f.element.style.width='200px';});assert.equal(f.animations[0].cancelled,true);f.flush();
 assert.deepEqual(f.animations[1].keyframes,[{width:'137px'},{width:'200px'}]);await Promise.resolve();assert.equal(f.animations[1].cancelled,false);f.motion.dispose();
});

test('CSS property names are converted to Web Animations keyframe names so adjacent layout tracks really interpolate',()=>{
 const f=fixture();f.element.style['grid-template-columns']='200px 1400px';
 f.motion.run([{element:f.element,properties:['grid-template-columns']}],()=>{f.element.style['grid-template-columns']='64px 1536px';});f.flush();
 assert.deepEqual(f.animations[0].keyframes,[{gridTemplateColumns:'200px 1400px'},{gridTemplateColumns:'64px 1536px'}]);f.motion.dispose();
});
test('a newer change before the first frame suppresses the obsolete pending animation',()=>{
 const f=fixture();f.motion.run(f.targets,()=>{f.element.style.width='64px';});f.motion.run(f.targets,()=>{f.element.style.width='200px';});f.flush();
 assert.equal(f.animations.length,1);assert.equal(f.animations[0].keyframes[1].width,'200px');f.motion.dispose();
});
test('reduced motion applies state immediately and preference or viewport changes cancel active work',()=>{
 const f=fixture();f.media.matches=true;f.motion.run(f.targets,()=>{f.element.style.width='64px';});f.flush();assert.equal(f.animations.length,0);
 f.media.matches=false;f.motion.run(f.targets,()=>{f.element.style.width='200px';});f.flush();f.media.matches=true;f.media.dispatchEvent(new Event('change'));assert.equal(f.animations[0].cancelled,true);
 f.media.matches=false;f.motion.run(f.targets,()=>{f.element.style.width='64px';});f.flush();f.browser.dispatchEvent(new Event('resize'));assert.equal(f.animations[1].cancelled,true);f.motion.dispose();
});
test('dragging, missing browser animation support and detached nodes preserve functional updates without motion',()=>{
 const f=fixture();f.motion.run(f.targets,()=>{f.element.style.width='300px';},false);f.flush();assert.equal(f.animations.length,0);
 f.element.isConnected=false;f.motion.run(f.targets,()=>{f.element.style.width='360px';});f.flush();assert.equal(f.animations.length,0);f.motion.dispose();
 const second=fixture();second.element.animate=undefined;second.motion.run(second.targets,()=>{second.element.style.width='64px';});second.flush();assert.equal(second.animations.length,0);second.motion.dispose();
});
test('unmount cancels frames/animations and lifecycle reactivation remains usable',()=>{
 const f=fixture();f.motion.run(f.targets,()=>{f.element.style.width='64px';});f.motion.dispose();assert.equal(f.frames.size,0);f.flush();assert.equal(f.animations.length,0);
 f.motion.run(f.targets,()=>{f.element.style.width='200px';});f.flush();assert.equal(f.animations.length,0);
 f.motion.activate();f.motion.run(f.targets,()=>{f.element.style.width='64px';});f.flush();assert.equal(f.animations.length,1);f.motion.dispose();
});
