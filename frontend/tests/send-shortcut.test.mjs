import {test} from 'node:test';
import assert from 'node:assert/strict';
import {isSendShortcut} from '../src/guide/send-shortcut.ts';

const key={key:'Enter',ctrlKey:false,metaKey:false,altKey:false,shiftKey:false,repeat:false,isComposing:false};
test('only an explicit Ctrl or Command Enter sends; ordinary Enter remains a newline',()=>{
 assert.equal(isSendShortcut(key,true),false);
 assert.equal(isSendShortcut({...key,ctrlKey:true},true),true);
 assert.equal(isSendShortcut({...key,metaKey:true},true),true);
 for(const extra of [{key:'b'},{altKey:true},{shiftKey:true},{repeat:true},{defaultPrevented:true}])
  assert.equal(isSendShortcut({...key,ctrlKey:true,...extra},true),false);
});
test('IME confirmation and blocked button states cannot trigger a keyboard send',()=>{
 for(const extra of [{isComposing:true},{keyCode:229}])
  assert.equal(isSendShortcut({...key,ctrlKey:true,...extra},true),false);
 assert.equal(isSendShortcut({...key,ctrlKey:true},false),false);
 assert.equal(isSendShortcut({...key,metaKey:true},false),false);
});
