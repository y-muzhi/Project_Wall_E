import {useEffect,useRef,useState} from 'react';
import type {SourceReading} from './source-reading.ts';
export function SourceReference({label,read}:Readonly<{label:string;read:(signal:AbortSignal)=>Promise<SourceReading>}>){
 const [value,setValue]=useState<SourceReading|null>(null),[error,setError]=useState<string|null>(null),[loading,setLoading]=useState(false),controller=useRef<AbortController|null>(null),open=useRef(false),request=useRef(read);request.current=read;
 useEffect(()=>()=>{open.current=false;controller.current?.abort();},[]);
 const load=()=>{controller.current?.abort();const actual=new AbortController();controller.current=actual;setLoading(true);setError(null);
  void request.current(actual.signal).then(value=>{if(open.current&&!actual.signal.aborted)setValue(value);},()=>{if(open.current&&!actual.signal.aborted)setError('来源读取失败，已显示内容保留。');}).finally(()=>{if(open.current&&!actual.signal.aborted)setLoading(false);});};
 return <details className="source-reference" onToggle={event=>{open.current=event.currentTarget.open;if(open.current){if(!value&&!loading)load();}else{controller.current?.abort();setLoading(false);}}}><summary>{label}</summary>{loading&&<p role="status">正在读取实际来源…</p>}{error&&<p role="alert">{error}<button className="ui-button" type="button" disabled={loading} onClick={load}>重新读取</button></p>}{value&&<><p><strong>{value.title}</strong></p><pre className="message-content">{value.content}</pre></>}</details>;
}
