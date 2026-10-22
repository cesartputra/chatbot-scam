import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const html = readFileSync(new URL('../widget/iasc-ai-widget.html',import.meta.url),'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const snapshot = {
  session_id:'session_dummy_123',revision:4,state:'TERLAPOR_DETAILS',active_wizard_step:2,
  data:{tahap2:{}},dom_patches:[],quick_replies:[],simulation:false,
  assistant_message:'Ketik nomor WhatsApp atau tautan akun pelaku.',
};

function widget(chatResponse = () => ({status:200,data:snapshot})) {
  const nodes = new Map();
  class Node {
    constructor(tag = 'div') { this.tag = tag; this.children = []; this.listeners = {}; this.disabled = false; this.value = ''; this.className = ''; this.text = ''; this.classList = {add:name => {this.className += ' ' + name;}}; }
    set id(value) { this._id = value; nodes.set(value,this); }
    get id() { return this._id; }
    set textContent(value) { this.text = String(value); this.children = []; }
    get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.text = ''; this.children = children; }
    setAttribute(name,value) { this[name] = value; }
    addEventListener(name,listener) { this.listeners[name] = listener; }
    querySelectorAll(tag) { return this.children.flatMap(child => [...(child.tag === tag ? [child] : []),...child.querySelectorAll(tag)]); }
  }
  for (const [,id] of html.matchAll(/\bid="([^"]+)"/g)) { const node = new Node(); node.id = id; }
  const document = {getElementById:id => nodes.get(id),createElement:tag => new Node(tag),createTextNode:text => {const node = new Node('#text'); node.textContent = text; return node;},addEventListener() {}};
  const window = {addEventListener() {}}; window.parent = window;
  const calls = [];
  const fetch = async (path,options) => {
    calls.push({path,options});
    const result = path.endsWith('/chat') ? chatResponse(JSON.parse(options.body)) : {status:200,data:snapshot};
    return {status:result.status,ok:result.status < 400,json:async () => structuredClone(result.data)};
  };
  runInNewContext(script,{document,window,location:{search:'?embed=1',origin:'http://127.0.0.1:8787',protocol:'http:'},URL,URLSearchParams,FormData,AbortController,setTimeout,clearTimeout,fetch});
  const ready = async () => {
    for (let index = 0; index < 20; index++) {
      await new Promise(setImmediate);
      if (!nodes.get('send').disabled) return;
    }
    assert.fail('Widget remained busy after request completed');
  };
  const send = async text => { nodes.get('chat-input').value = text; nodes.get('composer').listeners.submit({preventDefault() {}}); await ready(); };
  const messages = () => nodes.get('messages').children;
  return {nodes,calls,ready,send,messages};
}

test('each user message gets an assistant response even when the draft is unchanged',async () => {
  const chat = widget(); await chat.ready();
  assert.equal(chat.messages().length,1);
  await chat.send('whatsapp');
  await chat.send('halo');
  assert.equal(chat.messages().filter(node => node.className.includes('message assistant')).length,3);
  assert.equal(chat.messages().filter(node => node.className.includes('message user')).length,2);
  assert.equal(chat.messages().filter(node => node.className.includes('fill-notice')).length,0);
  assert.equal(chat.nodes.get('chat-input').disabled,false);
  assert.equal(chat.calls.filter(call => call.path.endsWith('/chat')).length,2);
});

test('validation errors remain visible and the status recovery does not duplicate the same question',async () => {
  const chat = widget(() => ({status:422,data:{detail:'Mohon isi nomor atau tautan WhatsApp pelaku.'}}));
  await chat.ready(); await chat.send('whatsapp');
  const error = chat.messages().find(node => node.className.includes('error-message'));
  assert.ok(error.textContent.includes('nomor atau tautan WhatsApp'));
  assert.equal(chat.nodes.get('send').disabled,false);
  const assistantCount = chat.messages().filter(node => node.className.includes('message assistant')).length;
  chat.nodes.get('recover-status').listeners.click(); await chat.ready();
  assert.equal(chat.messages().filter(node => node.className.includes('message assistant')).length,assistantCount);
});
