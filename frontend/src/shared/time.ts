/** SHR-TIME display only. Ordering continues to use the server result order. */
export function localTime(input:string):string {
  if(!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(input)||input.startsWith('0000-'))return '--';
  const date=new Date(input);if(!Number.isFinite(date.getTime())||date.toISOString()!==input)return '--';
  const pad=(value:number)=>String(value).padStart(2,'0');
  return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Compact conversation display; the time element retains the full server instant. */
export function conversationTime(input:string):string {
  const display=localTime(input);
  return display.replace(/^\d+-/,'');
}
