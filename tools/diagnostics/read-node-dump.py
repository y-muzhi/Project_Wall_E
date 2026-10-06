"""Read isolated ProcDump exception plus symbolized raw stack candidates.

No external libraries. Raw candidates are explicitly NOT an unwound stack.
Only commit the small report; keep full memory dumps private in output.
"""
import ctypes as c
from ctypes import wintypes as w
import json, mmap, struct, sys
from pathlib import Path

dump, symbols = map(Path, sys.argv[1:3])
with dump.open('rb') as file:
    data=mmap.mmap(file.fileno(),0,access=mmap.ACCESS_READ)
    def unpack(fmt, offset): return struct.unpack_from('<'+fmt,data,offset)
    def u32(offset): return unpack('I',offset)[0]
    def u64(offset): return unpack('Q',offset)[0]
    assert data[:4]==b'MDMP'
    directories={}
    for i in range(u32(8)):
        kind,size,rva=unpack('III',u32(12)+i*12);directories[kind]=(size,rva)
    modules=[]
    mrva=directories[4][1]
    for i in range(u32(mrva)):
        start=mrva+4+i*108;base=u64(start);size=u32(start+8);nrva=u32(start+20)
        name=data[nrva+4:nrva+4+u32(nrva)].decode('utf-16le')
        modules.append({'name':name,'base':base,'size':size})
    er=directories[6][1];thread=u32(er);code=u32(er+8);address=u64(er+24);params=[u64(er+40+i*8) for i in range(u32(er+32))]
    context_size,context_rva=unpack('II',er+160);rsp=u64(context_rva+152);rip=u64(context_rva+248)
    memory=[]
    if 9 in directories:
        memrva=directories[9][1];loc=u64(memrva+8)
        for i in range(u64(memrva)):
            start,size=unpack('QQ',memrva+16+i*16);memory.append((start,size,loc));loc+=size
    def read(address,size):
        for base,length,rva in memory:
            if base<=address and address+size<=base+length:return data[rva+address-base:rva+address-base+size]
        return b''
    dbg=c.WinDLL('dbghelp',use_last_error=True);handle=c.c_void_p(0x1234)
    dbg.SymInitializeW.argtypes=[c.c_void_p,w.LPCWSTR,w.BOOL];dbg.SymInitializeW.restype=w.BOOL
    dbg.SymSetOptions(0x2|0x4|0x10|0x80000000)
    assert dbg.SymInitializeW(handle,str(symbols.resolve()),False), c.get_last_error()
    dbg.SymLoadModuleExW.argtypes=[c.c_void_p,c.c_void_p,w.LPCWSTR,w.LPCWSTR,c.c_ulonglong,w.DWORD,c.c_void_p,w.DWORD];dbg.SymLoadModuleExW.restype=c.c_ulonglong
    for mod in modules:
        dbg.SymLoadModuleExW(handle,None,mod['name'],None,mod['base'],mod['size'],None,0)
    class Info(c.Structure):
        _fields_=[('SizeOfStruct',w.ULONG),('TypeIndex',w.ULONG),('Reserved',c.c_ulonglong*2),('Index',w.ULONG),('Size',w.ULONG),('ModBase',c.c_ulonglong),('Flags',w.ULONG),('Value',c.c_ulonglong),('Address',c.c_ulonglong),('Register',w.ULONG),('Scope',w.ULONG),('Tag',w.ULONG),('NameLen',w.ULONG),('MaxNameLen',w.ULONG),('Name',c.c_char*1)]
    dbg.SymFromAddr.argtypes=[c.c_void_p,c.c_ulonglong,c.POINTER(c.c_ulonglong),c.POINTER(Info)];dbg.SymFromAddr.restype=w.BOOL
    def symbol(address):
        mod=next((m for m in modules if m['base']<=address<m['base']+m['size']),None)
        if mod is None:return None
        buf=c.create_string_buffer(c.sizeof(Info)+2048);info=c.cast(buf,c.POINTER(Info));info.contents.SizeOfStruct=c.sizeof(Info);info.contents.MaxNameLen=2048;dis=c.c_ulonglong()
        found=dbg.SymFromAddr(handle,address,c.byref(dis),info)
        name=c.string_at(c.addressof(buf)+Info.Name.offset,info.contents.NameLen).decode('utf8','replace') if found else None
        return {'address':hex(address),'module':Path(mod['name']).name,'rva':hex(address-mod['base']),'symbol':name,'displacement':dis.value if found else None}
    candidates=[]
    for offset in range(0,2048,8):
        raw=read(rsp+offset,8)
        if len(raw)!=8:break
        item=symbol(struct.unpack('<Q',raw)[0])
        if item:item['stack_offset']=hex(offset);candidates.append(item)
    report={'scope':'Exception context and symbolized raw stack candidates, not an unwound call stack. Isolated no-credential HTTP reproduction.','dump_sha256':__import__('hashlib').sha256(data).hexdigest(),'thread':thread,'exception_code':hex(code),'exception_parameters':params,'exception':symbol(address),'rip':symbol(rip),'rsp':hex(rsp),'raw_stack_candidates':candidates,'modules':[{'name':Path(m['name']).name,'base':hex(m['base']),'size':m['size']} for m in modules]}
    target=Path('docs/verification/node-windows-dump.json');target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'evidence':str(target),'exception':report['exception'],'parameters':params,'candidates':candidates[:30]},ensure_ascii=False))
