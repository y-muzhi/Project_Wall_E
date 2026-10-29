import {test} from 'node:test';
import assert from 'node:assert/strict';
import {composerShortcut,isSendShortcut} from '../src/guide/send-shortcut.ts';

const key={key:'Enter',ctrlKey:false,metaKey:false,altKey:false,shiftKey:false,repeat:false,isComposing:false};
test('ordinary Enter sends and Ctrl or Command Enter inserts a newline instead',()=>{
 assert.equal(isSendShortcut(key,true),true);
 for(const extra of [{ctrlKey:true},{metaKey:true},{ctrlKey:true,shiftKey:true}]){
  assert.equal(composerShortcut({...key,...extra}),'NEWLINE');assert.equal(isSendShortcut({...key,...extra},true),false);
 }
 for(const extra of [{key:'b'},{altKey:true},{shiftKey:true},{defaultPrevented:true}])assert.equal(composerShortcut({...key,...extra}),null);
});
test('IME confirmation, repeats and blocked send permissions cannot submit',()=>{
 for(const extra of [{isComposing:true},{keyCode:229}]){
  assert.equal(composerShortcut({...key,...extra}),null);assert.equal(composerShortcut({...key,ctrlKey:true,...extra}),null);
 }
 assert.equal(composerShortcut({...key,repeat:true}),'IGNORE');assert.equal(composerShortcut({...key,ctrlKey:true,repeat:true}),'IGNORE');
 assert.equal(isSendShortcut({...key,repeat:true},true),false);assert.equal(isSendShortcut(key,false),false);
});
