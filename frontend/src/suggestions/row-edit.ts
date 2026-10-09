/** A presentation adapter for the existing exact {cells} edit contract. */
export function tableRowCells(content:string,columns:number):readonly string[]|null{
  try{
    const row:unknown=JSON.parse(content);
    if(!row||typeof row!=='object'||Array.isArray(row)||Object.keys(row).length!==1||!('cells' in row))return null;
    const cells=row.cells;
    return Array.isArray(cells)&&cells.length===columns&&cells.every(cell=>typeof cell==='string')?cells:null;
  }catch{return null;}
}
export function replaceRowCell(content:string,columns:number,index:number,value:string):string{
  const cells=tableRowCells(content,columns);
  if(!cells||!Number.isInteger(index)||index<0||index>=columns)throw Error('Cannot change an invalid row draft');
  return JSON.stringify({cells:cells.map((cell,position)=>position===index?value:cell)});
}
