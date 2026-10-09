import {commandsCtx} from '@milkdown/kit/core';
import type {Ctx} from '@milkdown/kit/ctx';
import type {Node} from '@milkdown/kit/prose/model';
import {Selection,TextSelection} from '@milkdown/kit/prose/state';
import type {Command,EditorState,Transaction} from '@milkdown/kit/prose/state';
import {toggleStrongCommand,toggleEmphasisCommand,toggleInlineCodeCommand,turnIntoTextCommand,wrapInHeadingCommand,
  wrapInBulletListCommand,wrapInOrderedListCommand,wrapInBlockquoteCommand,createCodeBlockCommand,insertHrCommand} from '@milkdown/kit/preset/commonmark';
import {toggleStrikethroughCommand,insertTableCommand} from '@milkdown/kit/preset/gfm';
import {undo,redo} from '@milkdown/kit/prose/history';

export function listCommand(ctx:Ctx,ordered:boolean):Command{
  const command=ctx.get(commandsCtx).get(ordered?wrapInOrderedListCommand.key:wrapInBulletListCommand.key)();
  return (state,dispatch,view)=>command(state,dispatch&& (transaction=>{
    const original=new Set<Node>();state.doc.descendants(node=>{original.add(node);});
    // Crepe defaults every new item to spread=true, even one paragraph. That
    // flag cannot survive Markdown parsing. Canonicalize only generated list
    // spacing attributes; the existing snapshot equivalence check stays intact.
    transaction.doc.descendants((node,pos)=>{
      if(original.has(node))return;
      if(node.type.name==='list_item')transaction.setNodeMarkup(pos,undefined,{...node.attrs,spread:node.childCount>1});
      if(node.type.name==='bullet_list'||node.type.name==='ordered_list'){
        let loose=!!node.attrs.spread;node.forEach(item=>{if(item.childCount>1)loose=true;});
        if(loose!==node.attrs.spread)transaction.setNodeMarkup(pos,undefined,{...node.attrs,spread:loose});
      }
    });dispatch(transaction);
  }),view);
}

export type FormatAction='text'|'h1'|'h2'|'h3'|'bold'|'italic'|'strike'|'inlineCode'|'bullet'|'ordered'|'quote'|'code'|'hr'|'table'|'undo'|'redo';
export function formatCommand(ctx:Ctx,action:FormatAction):Command{
  const commands=ctx.get(commandsCtx);
  switch(action){
    case 'text':return (state,dispatch,view)=>state.selection.$from.parent.type.name==='paragraph'?(dispatch?.(state.tr),true):commands.get(turnIntoTextCommand.key)()(state,dispatch,view);
    case 'h1':case 'h2':case 'h3':return commands.get(wrapInHeadingCommand.key)(Number(action[1]));
    case 'bold':return commands.get(toggleStrongCommand.key)();
    case 'italic':return commands.get(toggleEmphasisCommand.key)();
    case 'strike':return commands.get(toggleStrikethroughCommand.key)();
    case 'inlineCode':return commands.get(toggleInlineCodeCommand.key)();
    case 'bullet':return listCommand(ctx,false);
    case 'ordered':return listCommand(ctx,true);
    case 'quote':return commands.get(wrapInBlockquoteCommand.key)();
    case 'code':return commands.get(createCodeBlockCommand.key)();
    case 'hr':return commands.get(insertHrCommand.key)();
    case 'table':return commands.get(insertTableCommand.key)({row:3,col:3});
    case 'undo':return undo;
    case 'redo':return redo;
  }
}

export type SlashMatch=Readonly<{from:number;to:number;query:string}>;
/** Only a paragraph prefix at its cursor, never a URL, code or selected text. */
export function slashMatch(state:EditorState):SlashMatch|null{
  const {selection}=state;
  if(!(selection instanceof TextSelection)||!selection.empty||selection.$from.parent.type.name!=='paragraph')return null;
  const before=selection.$from.parent.textBetween(0,selection.$from.parentOffset,'','\ufffc');
  if(!/^\/[^\s/]{0,32}$/u.test(before))return null;
  return {from:selection.from-before.length,to:selection.from,query:before.slice(1)};
}
/** Query removal and insertion form ONE owned transaction. An unavailable
 * command leaves the query untouched; unrelated text and IDs are not reparsed. */
export function replaceSlash(match:SlashMatch,command:Command):Command{
  return (state,dispatch,view)=>{
    const actual=slashMatch(state);
    if(!actual||actual.from!==match.from||actual.to!==match.to||actual.query!==match.query)return false;
    const transaction=state.tr.delete(match.from,match.to),candidate=state.apply(transaction);
    let result:Transaction|undefined;
    if(!command(candidate,dispatch?(value=>{result=value;}):undefined,view))return false;
    if(!dispatch)return true;
    if(result){
      for(const step of result.steps)transaction.step(step);
      transaction.setSelection(Selection.fromJSON(transaction.doc,result.selection.toJSON()));
      if(result.storedMarksSet)transaction.setStoredMarks(result.storedMarks);
      if(result.scrolledIntoView)transaction.scrollIntoView();
    }
    dispatch(transaction);return true;
  };
}
export function linkCommand(href:string,insertLabel=false):Command{
  return (state,dispatch)=>{const type=state.schema.marks.link;if(!type)return false;const mark=type.create({href});
    dispatch?.(state.selection.empty?(insertLabel?state.tr.replaceSelectionWith(state.schema.text(href,[mark]),false):state.tr.addStoredMark(mark)):state.tr.addMark(state.selection.from,state.selection.to,mark));return true;
  };
}
export function validLink(value:string):boolean{
  try{return ['http:','https:','mailto:'].includes(new URL(value).protocol);}catch{return false;}
}
