import {exact,positiveInteger} from '../api/client.ts';
type StoragePort=Pick<Storage,'getItem'|'setItem'>;
/** A reading preference never becomes an AI target or manual edit identity. */
export class ReadingSelection{
 private readonly key:string;
 private readonly requirement:number;private readonly storage:()=>StoragePort;
 constructor(requirement:number,storage:()=>StoragePort=()=>sessionStorage){this.requirement=positiveInteger(requirement);this.storage=storage;this.key='walle:v1.5:reading:'+this.requirement;}
 load():number|null|undefined{
  try{const raw=this.storage().getItem(this.key);if(raw===null)return undefined;const value=exact(JSON.parse(raw),['schema_version','requirement_id','document_id']);
   if(value.schema_version!==1||value.requirement_id!==this.requirement)throw TypeError('Owned reading preference required');
   return value.document_id===null?null:positiveInteger(value.document_id);
  }catch{return undefined;}
 }
 save(document:number|null):void{try{if(document!==null)positiveInteger(document);this.storage().setItem(this.key,JSON.stringify({schema_version:1,requirement_id:this.requirement,document_id:document}));}catch{/* A failed preference cannot block a consistent read or business command. */}}
}
