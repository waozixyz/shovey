// Real browser input against a disposable headless Chromium profile.
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {readFile,mkdtemp,mkdir,rm} from 'node:fs/promises';
import {join,extname,resolve} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
const root=resolve('build/shared-progress-browser-test');
const types={'.html':'text/html','.js':'text/javascript','.wasm':'application/wasm','.png':'image/png','.wav':'audio/wav','.json':'application/json'};
const missing=[],errors=[];
const server=createServer(async(req,res)=>{const url=new URL(req.url,'http://x');const path=url.pathname;if(path==='/favicon.ico'){res.writeHead(204);res.end();return}if(path==='/browser-storage.html'){res.writeHead(200,{'Content-Type':'text/html'});res.end('<!doctype html><title>Browser storage setup</title><link rel="icon" href="data:,">');return}try{const file=resolve(root,'.'+(path==='/'?'/index.html':path));if(!file.startsWith(root+'/'))throw Error('Path');const data=await readFile(file);res.writeHead(200,{'Content-Type':types[extname(file)]||'application/octet-stream'});res.end(data)}catch{missing.push(path);res.writeHead(404);res.end()}});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
await mkdir('work',{recursive:true});
const profile=await mkdtemp(resolve('work/shovey-progress-browser-'));
const env={...process.env,YUE_DESKTOP_RECOVERY:'0'};for(const key of ['DISPLAY','WAYLAND_DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS','SESSION_MANAGER'])delete env[key];
const browser=spawn(process.env.CHROMIUM||'chromium',['--headless=new','--disable-gpu','--mute-audio','--no-sandbox','--disable-dev-shm-usage','--no-first-run','--remote-debugging-port=0',`--user-data-dir=${profile}`,'about:blank'],{env,stdio:['ignore','ignore','pipe']});
let browserFailure='',browserDiagnostics='';browser.on('error',error=>{browserFailure=error.message});browser.stderr.on('data',chunk=>{browserDiagnostics=(browserDiagnostics+chunk).slice(-2000)});
let socket,sequence=0;const pending=new Map();
const command=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;const timer=setTimeout(()=>{pending.delete(id);reject(Error(method+' timed out'))},20000);pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}))});
const evaluate=async expression=>{const result=await command('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw Error(result.exceptionDetails.text);return result.result.value};
const until=async(expression,timeout=120000)=>{const start=Date.now();while(Date.now()-start<timeout){if(await evaluate(expression))return;await delay(100)}throw Error('Timed out: '+expression+'\n'+errors.slice(-8).join('\n'))};
try{
 let port;for(let i=0;i<600;i++){if(browserFailure||(browser.exitCode!==null||browser.signalCode!==null))throw Error('Browser could not start: '+(browserFailure||browserDiagnostics));try{port=(await readFile(join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];break}catch{}await delay(50)}if(!port)throw Error('Browser startup timed out: '+browserDiagnostics);
 const targets=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);await new Promise((r,j)=>{socket.onopen=r;socket.onerror=j});
 socket.onmessage=e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);if(m.method==='Runtime.consoleAPICalled'&&m.params.type==='error')errors.push(m.params.args.map(a=>a.value||a.description).join(' '));const p=pending.get(m.id);if(!p)return;clearTimeout(p.timer);pending.delete(m.id);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result)};
 await command('Runtime.enable');await command('Page.enable');
 await command('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/`});
 await until('typeof globalThis.progressTestResult==="number"');
 const result=await evaluate('globalThis.progressTestResult');
 if(result!==0||errors.length)throw Error(`Production browser progress adapter failed: ${result}, ${errors.join(' ')}`);
 await command('Page.addScriptToEvaluateOnNewDocument',{source:'globalThis.progressRecovery=true'});
 await command('Page.reload');
 await until('globalThis.progressRecovery===true && typeof globalThis.progressTestResult==="number"');
 const recovered=await evaluate('globalThis.progressTestResult');
 if(recovered!==0||errors.length)throw Error(`Production browser recovery failed: ${recovered}, ${errors.join(' ')}`);
 await command('Page.addScriptToEvaluateOnNewDocument',{source:'globalThis.progressRecovery=2'});
 await command('Page.reload');
 await until('globalThis.progressRecovery===2 && typeof globalThis.progressTestResult==="number"');
 const final=await evaluate('globalThis.progressTestResult');
 if(final!==0)throw Error('Acknowledged save did not survive reload: '+final);
 console.log('Shovey local browser adapter tests passed: before-ready, failed flush suppresses upload/durable ack, recovery, atomic earned+pending reload, new account isolation.');
}finally{
 const exited=!browser.pid||(browser.exitCode!==null||browser.signalCode!==null)?Promise.resolve():new Promise(r=>browser.once('exit',r));
 if(socket?.readyState===WebSocket.OPEN)await command('Browser.close').catch(()=>{});
 if((browser.exitCode===null&&browser.signalCode===null))browser.kill('SIGTERM');
 await exited;socket?.close();server.closeAllConnections();await new Promise(r=>server.close(r));
 await rm(profile,{recursive:true,force:true,maxRetries:10,retryDelay:200});
}
