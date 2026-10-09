import test from 'node:test';
import assert from 'node:assert/strict';
import {selectionToolbarPosition} from '../src/documents/selection-toolbar-position.ts';
const port={left:100,right:900,top:76,bottom:800};
test('selection toolbar is centered above the entire range, independent of selection direction',()=>{
 const selection={left:300,right:500,top:400,bottom:428};
 assert.deepEqual(selectionToolbarPosition(selection,port,200,40),{left:300,top:352});
 assert.deepEqual(selectionToolbarPosition({...selection,bottom:550},port,200,40),{left:300,top:352});
});
test('editor edge clamps horizontally; toolbar never flips below near the upper edge',()=>{
 assert.deepEqual(selectionToolbarPosition({left:110,right:150,top:300,bottom:328},port,300,40),{left:100,top:252});
 assert.deepEqual(selectionToolbarPosition({left:880,right:899,top:300,bottom:328},port,300,40),{left:600,top:252});
 assert.equal(selectionToolbarPosition({left:300,right:500,top:100,bottom:128},port,300,40),null);
});
test('outside selection is hidden; scrolling the selection back recalculates its upper anchor',()=>{
 assert.equal(selectionToolbarPosition({left:300,right:500,top:820,bottom:848},port,300,40),null);
 assert.deepEqual(selectionToolbarPosition({left:300,right:500,top:420,bottom:448},port,300,40),{left:250,top:372});
 assert.equal(selectionToolbarPosition({left:300,right:500,top:400,bottom:428},{...port,right:250},300,40),null);
});
