/** A write can retire a shared GET while its panel remains visible. Repeat
 * that read once in the current epoch; a real failure still reaches the UI.
 * Leaving the panel retires this lifetime and must never start another read. */
export async function readVisiblePanel(read:()=>Promise<void>,signal:AbortSignal):Promise<void>{
  for(let attempt=0;attempt<2;attempt++){
    if(signal.aborted)return;
    try{await read();return;}
    catch(error){
      if(signal.aborted)return;
      if(attempt===0&&error instanceof DOMException&&error.name==='AbortError')continue;
      throw error;
    }
  }
}
