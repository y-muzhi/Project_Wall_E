'use strict';
// Fixed SDK launch adapter. Chromium and its inherited pipes belong to the original Python root.
const {EventEmitter} = require('events');
const {Readable, Writable} = require('stream');
const fs = require('fs');
const path = require('path');

function install(packagePath, send, epoch) {
  let current = null;
  let serial = 0;
  const launcherPath = path.join(packagePath, 'lib/server/utils/processLauncher.js');
  const original = require(launcherPath);
  async function launchProcess(options) {
    if (current || options.stdio !== 'pipe' || options.shell || options.cwd)
      throw new Error('SDK_FIXED_BROWSER_LAUNCH_REQUIRED');
    const token = ++serial;
    const generation = epoch();
    let started;
    const start = new Promise(resolve => { started = resolve; });
    let ended;
    const end = new Promise(resolve => { ended = resolve; });
    const child = new EventEmitter();
    const streams = new Map();
    for (const name of ['stdout','stderr','cdp']) streams.set(name,new Readable({read(){}}));
    child.stdout = streams.get('stdout');
    child.stderr = streams.get('stderr');
    for (const name of ['stdout','stderr']) streams.get(name).on('data',raw=>options.log('[original-browser]['+name+'] '+raw.toString('utf8').slice(-2000)));
    const writer = new Writable({
      write(data, encoding, callback) {
        if (!data.length) {callback();return;}
        if (state.pendingWrite || data.length>8*1024*1024) {
          callback(new Error('SDK_ORIGINAL_BROWSER_WRITE_LIMIT'));return;
        }
        state.pendingWrite={data,offset:0,callback,sequence:0,size:0};
        writeNext(state);
      }
    });
    child.stdio = [null,child.stdout,child.stderr,writer,streams.get('cdp')];
    const state = {token,generation,child,streams,started,ended,code:null,exited:false,eof:new Set(),closed:false,options,pendingWrite:null,writeSequence:0};
    current = state;
    send({event:'BROWSER_START',epoch:generation,browser:token,command:options.command,args:options.args});
    await start;
    const stop = () => send({event:'BROWSER_STOP',epoch:generation,browser:token});
    const kill = async () => {if(!state.closed)stop();await end;};
    const cleanup = async () => {
      for (const folder of options.tempDirectories) await fs.promises.rm(folder,{recursive:true,force:true,maxRetries:3});
    };
    async function gracefullyClose() {
      if (state.closed) return;
      await options.attemptToGracefullyClose().catch(stop);
      await end;
      await cleanup();
    }
    child.kill = () => {stop();return true;};
    options.log('<launched> original-root pid=' + child.pid);
    return {launchedProcess:child,gracefullyClose,kill:async()=>{await kill();await cleanup();}};
  }
  require.cache[require.resolve(launcherPath)].exports = {...original,launchProcess};
  function writeNext(state) {
    const pending=state.pendingWrite;
    const chunk=pending.data.subarray(pending.offset,pending.offset+32768);
    pending.sequence=++state.writeSequence;
    pending.size=chunk.length;
    send({event:'BROWSER_WRITE',epoch:state.generation,browser:state.token,
          write:pending.sequence,data:chunk.toString('base64')});
  }
  function receive(op,value) {
    const state = current;
    if (!state || value.browser !== state.token || value.epoch !== state.generation)
      throw new Error('SDK_ORIGINAL_BROWSER_REQUIRED');
    if (op === 'BROWSER_STARTED') {
      if (!Number.isSafeInteger(value.pid) || value.pid <= 0 || state.child.pid)
        throw new Error('SDK_ORIGINAL_BROWSER_PID_REQUIRED');
      state.child.pid = value.pid;
      state.started();
    } else if (op === 'BROWSER_WRITTEN') {
      const pending=state.pendingWrite;
      if (!pending || !Number.isSafeInteger(value.write) || value.write!==pending.sequence)
        throw new Error('SDK_ORIGINAL_BROWSER_WRITE_ACK_REQUIRED');
      pending.offset+=pending.size;
      if (pending.offset===pending.data.length) {
        state.pendingWrite=null;
        pending.callback();
      } else writeNext(state);
    } else if (op === 'BROWSER_DATA') {
      const stream = state.streams.get(value.stream);
      if (!stream || state.eof.has(value.stream)) throw new Error('SDK_ORIGINAL_BROWSER_STREAM_REQUIRED');
      if (value.data === null) {
        state.eof.add(value.stream);stream.push(null);
      } else {
        const raw = Buffer.from(value.data,'base64');
        if (!raw.length || raw.length>32768 || stream.readableLength+raw.length>2*1024*1024)
          throw new Error('SDK_ORIGINAL_BROWSER_STREAM_LIMIT');
        stream.push(raw);
      }
    } else if (op === 'BROWSER_EXIT') {
      if (!Number.isSafeInteger(value.code) || state.exited) throw new Error('SDK_ORIGINAL_BROWSER_EXIT_REQUIRED');
      state.code=value.code;state.exited=true;
      state.options.log('[original-browser] exit code='+value.code);
      state.child.emit('exit',value.code,null);
    } else throw new Error('SDK_ORIGINAL_BROWSER_MESSAGE_REQUIRED');
    if (state.exited && state.eof.size===3 && !state.closed) {
      state.closed=true;
      state.child.stdio[3].destroy();
      state.options.onExit(state.code,null);
      state.child.emit('close',state.code,null);
      state.ended();current=null;
    }
  }
  return {receive};
}
module.exports = {install};
