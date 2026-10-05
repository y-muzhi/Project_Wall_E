import {test} from 'node:test';
import assert from 'node:assert/strict';
import {RequirementWorkbench,defaultWorkbenchQuery} from '../src/requirements/workbench.ts';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('leaving workbench aborts only owned read, retains confirmed list, ignores late result and allows fresh return',async()=>{
  const calls=[],api={listRequirements(input,signal){let resolve;const promise=new Promise(yes=>{resolve=yes;});calls.push({input,signal,resolve});return promise;}};
  const response=id=>({data:{items:[{id}]},meta:{pagination:{page:1,page_size:20,total:1,total_pages:1}}});
  const controller=new RequirementWorkbench(api);let request=controller.query();await tick();calls[0].resolve(response(1));await request;
  const confirmed=controller.state.result;request=controller.query({...defaultWorkbenchQuery,keyword:'新条件'});await tick();controller.pause();
  assert.equal(calls[1].signal.aborted,true);assert.equal(controller.state.result,confirmed);calls[1].resolve(response(2));await request;
  assert.equal(controller.state.result,confirmed);assert.equal(controller.state.loading,false);
  const returned=controller.refresh();await tick();assert.equal(controller.phase,'REFRESHING');assert.equal(calls[2].input.keyword,'新条件');calls[2].resolve(response(3));await returned;
  assert.equal(controller.state.result.items[0].id,3);controller.dispose();
});
