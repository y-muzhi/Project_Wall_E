export type SelectionBounds=Readonly<{left:number;right:number;top:number;bottom:number}>;
/** A selection toolbar never flips beneath the text. If it cannot fit above
 * the visible selection, the fixed format toolbar remains the available UI. */
export function selectionToolbarPosition(selection:SelectionBounds,port:SelectionBounds,width:number,height:number):Readonly<{left:number;top:number}>|null{
  if(selection.bottom<=port.top||selection.top>=port.bottom||port.right-port.left<width)return null;
  const top=selection.top-height-8;
  if(top<port.top)return null;
  return {left:Math.max(port.left,Math.min((selection.left+selection.right-width)/2,port.right-width)),top};
}
