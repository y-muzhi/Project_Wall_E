import {exact,positiveInteger} from '../api/client.ts';
import type {Cards,Responses} from '../api/models.ts';
import {checkAnswers} from './card-answers.ts';
type Storage=Pick<globalThis.Storage,'getItem'|'setItem'|'removeItem'>;
export type DraftRead=Readonly<{answers:Responses|null;error:string|null}>;
export class CardDrafts{
 private readonly storage:()=>Storage;private readonly now:()=>string;
 constructor(storage:()=>Storage=()=>sessionStorage,now:()=>string=()=>new Date().toISOString()){this.storage=storage;this.now=now;}
 private key(requirement:number,message:number):string{return `walle:v1:cards:${positiveInteger(requirement)}:${positiveInteger(message)}`;}
 load(requirement:number,message:number,cards:Cards):DraftRead{
  try{const raw=this.storage().getItem(this.key(requirement,message));if(raw===null)return {answers:null,error:null};const row=exact(JSON.parse(raw),['schema_version','responses','updated_at']);if(row.schema_version!==1||typeof row.updated_at!=='string'||!Number.isFinite(Date.parse(row.updated_at)))throw TypeError('Invalid card draft');return {answers:checkAnswers(cards,{schema_version:1,responses:row.responses} as Responses,false),error:null};}
  catch{return {answers:null,error:'本地卡片草稿无法读取，未覆盖原记录；请保持页面并重新填写'};}
 }
 save(requirement:number,message:number,answers:Responses):string|null{
  try{this.storage().setItem(this.key(requirement,message),JSON.stringify({schema_version:1,responses:answers.responses,updated_at:this.now()}));return null;}
  catch{return '本地暂存失败，答案仍在当前页面；刷新可能丢失未提交输入';}
 }
 clear(requirement:number,message:number):string|null{try{this.storage().removeItem(this.key(requirement,message));return null;}catch{return '正式状态已确认，但本地草稿清理失败；下次读取正式状态后重试清理';}}
}
