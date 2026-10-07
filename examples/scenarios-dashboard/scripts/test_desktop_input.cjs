// Exercise the actual input bridge with RFB/DOM fakes; no ROS or hardware.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('platforms/macos/clipboard.js', 'utf8').replace('export function', 'function');
function setup() {
  const listeners = {}, events = {}, sent = [], writes = [];
  const control = () => ({hidden:true,value:'',disabled:false,setAttribute(){},focus(){},select(){}});
  const area=control(),panel={hidden:true,contains:target=>target===area},toggle=control();
  const client={addEventListener:(name,cb)=>events[name]=cb,sendKey:(...args)=>sent.push(['key',...args]),
    clipboardPasteFrom:value=>sent.push(['clipboard',value]),focus:()=>sent.push(['focus'])};
  const document={addEventListener:(name,cb)=>listeners[name]=cb,
    removeEventListener:(name,cb)=>{assert.equal(listeners[name],cb);delete listeners[name];}};
  const options={client,screen:{},area,panel,toggle,paste:control(),copy:control(),close:control(),
    message:{textContent:''},caps:control(),document,navigator:{clipboard:{writeText:async text=>writes.push(text)}}};
  let now=10000;
  const context=vm.createContext({options,Date:{now:()=>now}});
  vm.runInContext(source+'; cleanup=attachDesktopInput(options);', context);
  const event=(extra={})=>({target:{},type:'keydown',getModifierState:()=>false,
    preventDefault(){this.prevented=true;},stopImmediatePropagation(){this.stopped=true;},...extra});
  events.connect();return {listeners,events,sent,writes,options,event,context,advance:ms=>now+=ms};
}
(async()=>{
  const a=setup();
  const shortcut=a.event({metaKey:true,code:'KeyV'});a.listeners.keydown(shortcut);
  assert(shortcut.stopped&&!shortcut.prevented,'Native paste must remain available without reading clipboard permissions');
  const nativePaste=a.event({ctrlKey:true,shiftKey:true,code:'KeyV'});a.listeners.keydown(nativePaste);
  assert(!nativePaste.stopped,'Linux Ctrl+Shift+V must use the Linux clipboard');
  const command='ros2 service call /axiom/connect axiom_interfaces/srv/Connect \'{device_uri: ""}\'';
  const paste=a.event({clipboardData:{getData:()=>command}});a.listeners.paste(paste);
  assert(paste.prevented&&paste.stopped);
  assert.equal(a.sent.find(x=>x[0]==='clipboard')[1],command);
  const keys=a.sent.filter(x=>x[0]==='key');
  assert.equal(keys.some(x=>x[1]===0xff0d),false,'Paste must never send Enter');
  assert.deepEqual(keys.slice(-4).map(x=>x.slice(1)),[[0xffe1,'ShiftLeft',true],[0xff63,'Insert',true],[0xff63,'Insert',false],[0xffe1,'ShiftLeft',false]]);
  const before=a.sent.length;
  a.listeners.paste(a.event({target:a.options.area,clipboardData:{getData:()=>command}}));
  assert.equal(a.sent.length,before,'Pasting in the fallback editor must not send a command');
  a.options.document.activeElement=a.options.area;
  a.events.clipboard({detail:{text:'Connect'}});
  assert.equal(a.options.area.value,'Connect','A delayed Linux Copy must update the panel even after it receives focus');
  assert.equal(a.options.message.textContent,'Linux clipboard updated. Ctrl+Shift+V pastes in the terminal.');
  assert.equal(a.writes.length,0,'Selection must not overwrite host clipboard');
  a.options.copy.onclick();await Promise.resolve();assert.deepEqual(a.writes,['Connect']);
  a.listeners.keydown(a.event({metaKey:true,code:'KeyC'}));await Promise.resolve();assert.deepEqual(a.writes,['Connect','Connect']);
  a.listeners.keydown(a.event({ctrlKey:true,shiftKey:true,code:'KeyC'}));
  a.events.clipboard({detail:{text:'selected terminal text'}});await Promise.resolve();
  assert.equal(a.writes.at(-1),'selected terminal text');
  a.listeners.keydown(a.event({ctrlKey:true,shiftKey:true,code:'KeyC'}));await Promise.resolve();
  const writeCount=a.writes.length;a.advance(2000);
  a.events.clipboard({detail:{text:'unrelated later selection'}});await Promise.resolve();
  assert.equal(a.writes.length,writeCount,'An expired copy gesture must not mirror later selections');
  const capsDown=a.event({code:'CapsLock',getModifierState:()=>true});
  const capsUp=a.event({type:'keyup',code:'CapsLock',getModifierState:()=>true});
  a.listeners.keydown(capsDown);a.listeners.keyup(capsUp);
  assert(capsDown.stopped&&capsUp.stopped,'Suppress both of the macOS lock-key toggles');
  assert.equal(a.options.caps.hidden,false);
  const letter=a.event({code:'KeyA',key:'A',getModifierState:()=>true});a.listeners.keydown(letter);
  assert(!letter.stopped,'Uppercase letter keysyms must still reach Linux');
  a.listeners.keydown(a.event({code:'KeyA',key:'a'}));assert.equal(a.options.caps.hidden,true);
  a.events.disconnect();const count=a.sent.length;
  a.options.area.value=command;a.options.paste.onclick();assert.equal(a.sent.length,count);
  assert.equal(a.options.area.value,command);assert.equal(a.options.toggle.disabled,true);
  vm.runInContext('cleanup()',a.context);assert.equal(Object.keys(a.listeners).length,0);
  const b=setup();b.options.area.value='ros2 topic echo /é';b.options.paste.onclick();
  assert(b.sent.some(x=>x[0]==='clipboard'),'Latin-1 text remains supported');
  const c=setup();c.options.area.value='ros2 topic echo /α';c.options.paste.onclick();
  assert(!c.sent.some(x=>x[0]==='clipboard'),'Unsupported characters must not silently change the command');
  assert(!c.options.panel.hidden);
  console.log('Clipboard transfer, explicit copy, disconnected state, Caps Lock, and reconnect cleanup passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
