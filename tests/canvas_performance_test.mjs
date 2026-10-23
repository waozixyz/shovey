// Compare two preserved Shovey web builds in fresh private browser profiles.
// Usage: node tests/canvas_performance_test.mjs BEFORE_DIR AFTER_DIR RESULT.json
// Measures full frame busy time between Asyncify resume and the next RAF wait;
// the game remains capped at 60 FPS. Service requests use a refused test route.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile,mkdtemp,rm,writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import {createHash} from 'node:crypto';
const [before,after,receipt]=process.argv.slice(2);
assert(before && after && receipt, 'before-dir after-dir result.json required');
const artifacts={};
for(const directory of [before,after]) {
  artifacts[resolve(directory)]={};
  for(const name of ['index.js','index.wasm','runtime.data','shovey.zib']) {
    artifacts[resolve(directory)][name]=createHash('sha256').update(await readFile(join(directory,name))).digest('hex');
  }
}
const hook=`
  globalThis.frameTimes=[];globalThis.frameStart=0;
  for(const method of ['instantiate','instantiateStreaming']) {
    const original=WebAssembly[method];
    WebAssembly[method]=function(source,imports,...rest) {
      if(imports) for(const namespace of Object.values(imports)) {
        if(!namespace.js_web_next_frame || namespace.js_web_next_frame.measured) continue;
        const next=namespace.js_web_next_frame;
        const measured=function(...args) {
          const state=globalThis.Asyncify?.state;
          if(state===2) globalThis.frameStart=performance.now();
          if(state===0 && globalThis.frameStart) {
            globalThis.frameTimes.push(performance.now()-globalThis.frameStart);
            globalThis.frameStart=0;
          }
          return next(...args);
        };
        measured.measured=true;measured.isAsync=next.isAsync;
        namespace.js_web_next_frame=measured;
      }
      return original.call(this,source,imports,...rest);
    };
  }
  document.addEventListener('DOMContentLoaded',()=>{
    Module.preRun=Module.preRun||[]; Module.preRun.push(()=>{
      ENV.KRYON_TEST_DRIVER='/tmp/test-driver';Module.FS.mkdirTree('/tmp/test-driver');
    });
  },{once:true});`;
async function sample(directory) {
 const profile=await mkdtemp(join(tmpdir(),'shovey-perf-'));
 const server=createServer(async(req,res)=>{
  try {const path=decodeURIComponent(new URL(req.url,'http://localhost').pathname);assert(!path.includes('..'));
   const data=await readFile(join(directory,path==='/'?'index.html':path));
   res.setHeader('Content-Type',path.endsWith('.wasm')?'application/wasm':path.endsWith('.js')?'text/javascript':path.endsWith('.png')?'image/png':path.endsWith('.html')?'text/html':'application/octet-stream');
   res.end(data);
  }catch{res.writeHead(404).end();}
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const env={...process.env};for(const key of ['DISPLAY','WAYLAND_DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS','SESSION_MANAGER','GDK_DISPLAY'])delete env[key];
 const browser=spawn('chromium',['--headless','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-first-run','--no-default-browser-check','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{env,detached:true,stdio:['ignore','ignore','pipe']});
 let socket,errors='';browser.stderr.on('data',v=>errors=(errors+v).slice(-3000));
 try {
  let port;for(const end=Date.now()+20000;Date.now()<end&&!port;){try{port=(await readFile(join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];}catch{assert.equal(browser.exitCode,null,errors);await delay(50);}}
  assert(port,errors);const pages=await(await fetch('http://127.0.0.1:'+port+'/json/list')).json();
  socket=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);await new Promise(r=>socket.addEventListener('open',r,{once:true}));
  let id=0;const pending=new Map();const failures=[];
  socket.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')failures.push(m.params);if(m.method==='Fetch.requestPaused')call('Fetch.failRequest',{requestId:m.params.requestId,errorReason:'ConnectionRefused'});if(pending.has(m.id)){pending.get(m.id)(m);pending.delete(m.id);}});
  async function call(method,params={}){const request=++id;const result=new Promise((r,j)=>{pending.set(request,r);setTimeout(()=>{if(pending.delete(request))j(Error(method+' timed out'));},30000).unref();});socket.send(JSON.stringify({id:request,method,params}));const m=await result;assert(!m.error,JSON.stringify(m.error));return m.result;}
  async function evaluate(expression){const r=await call('Runtime.evaluate',{expression,returnByValue:true});assert(!r.exceptionDetails,JSON.stringify(r.exceptionDetails));return r.result.value;}
  async function wait(expression){for(const end=Date.now()+90000;Date.now()<end;){if(await evaluate(expression))return;await delay(100);}throw Error('Timed out '+expression+' '+JSON.stringify(failures));}
  await call('Runtime.enable');await call('Page.enable');await call('Page.addScriptToEvaluateOnNewDocument',{source:hook});
  await call('Fetch.enable',{patterns:[{urlPattern:'https://api.waozi.xyz/*'}]});
  await call('Emulation.setDeviceMetricsOverride',{width:390,height:700,deviceScaleFactor:1,mobile:true});
  await call('Page.navigate',{url:'http://127.0.0.1:'+server.address().port+'/index.html?mini'});
  await wait('globalThis.Module?.profileReady && document.querySelector("#loading-screen").classList.contains("is-hidden")');
  await evaluate('Module.FS.writeFile("/tmp/test-driver/command","1\\ttree\\n")');
  await wait('Module.FS.analyzePath("/tmp/test-driver/reply").exists');
  const tree=JSON.parse(await evaluate('Module.FS.readFile("/tmp/test-driver/reply",{encoding:"utf8"})'));
  assert(tree.ok);assert(tree.nodes.some(n=>/^Level 1 \/ /.test(n.label)),'Not on level one');
  await wait('globalThis.frameTimes.length>60');
  const assets=await evaluate(`(()=>{const hashes={};for(const path of ['/app.zib','/entity.zib','/kryon-font.ttf']){const bytes=Module.FS.readFile(path);let h=2166136261;for(const x of bytes)h=Math.imul(h^x,16777619);hashes[path]={length:bytes.length,hash:h>>>0};}return hashes;})()`);
  await evaluate('globalThis.frameTimes=[]');
  await call('Profiler.enable');await call('Profiler.start');
  await wait('globalThis.frameTimes.length>=180');
  const times=await evaluate('globalThis.frameTimes.slice(0,180)');
  const cpu=await call('Profiler.stop');
  assert.equal(failures.length,0,JSON.stringify(failures));
  return {times,assets,browser:await call('Browser.getVersion'),labels:tree.nodes.map(n=>n.label).filter(s=>s.startsWith('Level ')),cpu:cpu.profile};
 } finally {
  socket?.close();if(browser.exitCode===null&&browser.signalCode===null){const done=new Promise(r=>browser.once('exit',r));process.kill(-browser.pid,'SIGTERM');await done;}
  server.close();await rm(profile,{recursive:true,force:true});
 }
}
const samples=[];
for(const version of ['before','after','after','before']){
 console.log('Measuring '+version);
 const result=await sample(resolve(version==='before'?before:after));
 if(samples.length) assert.deepEqual(result.assets,samples[0].assets,'Embedded assets changed');
 const sorted=[...result.times].sort((a,b)=>a-b);console.log(version+' median '+sorted[Math.floor(sorted.length/2)]+' ms');
 samples.push({version,...result});await writeFile(receipt,JSON.stringify({artifacts,samples,limitations:'Warm private headless Chromium at 390x700 on one shared machine. Level 1, original portable game bundle, refused external service. Busy frame time excludes RAF waits; this is throughput capacity, not observed FPS or a claim about other levels/devices.'},null,2)+'\n');
}
const median=values=>values.sort((a,b)=>a-b)[Math.floor(values.length/2)];
const measured=version=>median(samples.filter(s=>s.version===version).flatMap(s=>s.times));
const beforeMs=measured('before'),afterMs=measured('after');
const summary={beforeMs,afterMs,throughputGainPercent:(beforeMs/afterMs-1)*100,busyTimeReductionPercent:(1-afterMs/beforeMs)*100};
await writeFile(receipt,JSON.stringify({artifacts,samples,summary,limitations:'Warm private headless Chromium at 390x700 on one shared machine. Level 1, same portable game bundle, refused external service. Busy frame time excludes RAF waits; this is throughput capacity, not observed FPS or a claim about other levels/devices.'},null,2)+'\n');
console.log(JSON.stringify(summary));

if(process.env.PERFORMANCE_MIN_GAIN !== undefined) {
  const minimum=Number(process.env.PERFORMANCE_MIN_GAIN);
  assert(Number.isFinite(minimum) && minimum >= 0, 'PERFORMANCE_MIN_GAIN must be a nonnegative percentage');
  assert(summary.throughputGainPercent >= minimum, `Throughput gain ${summary.throughputGainPercent.toFixed(1)}% is below ${minimum}%`);
}
