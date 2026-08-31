const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { EventEmitter } = require('events');

const ROOT = path.resolve(__dirname, '..');
const TEMPLATE = path.join(ROOT, 'builder/clients/nodejs/templates/messenger-client.js');

function renderElectronPrefix(source) {
  source = source.split('/* ARG PARSING */', 1)[0];
  const output = [];
  const stack = [];
  for (const line of source.split(/\r?\n/)) {
    const directive = line.trim();
    if (directive === '{% if electron %}') {
      stack.push(false);
      continue;
    }
    if (directive === '{% if not electron %}') {
      stack.push(true);
      continue;
    }
    if (directive === '{% else %}') {
      stack[stack.length - 1] = !stack[stack.length - 1];
      continue;
    }
    if (directive === '{% endif %}') {
      stack.pop();
      continue;
    }
    if (stack.every(Boolean)) output.push(line);
  }
  return output.join('\n');
}

class FakeWebSocket {
  static OPEN = 1;
  static nextServerFrame = null;
  static last = null;
  static nextSendError = null;

  constructor() {
    this.readyState = FakeWebSocket.OPEN;
    this.listeners = new Map();
    this.sent = [];
    FakeWebSocket.last = this;
    queueMicrotask(() => this.emit('open', {}));
  }

  addEventListener(name, callback, options = {}) {
    const entries = this.listeners.get(name) || [];
    entries.push({ callback, once: Boolean(options.once) });
    this.listeners.set(name, entries);
  }

  emit(name, event) {
    const entries = [...(this.listeners.get(name) || [])];
    for (const entry of entries) {
      entry.callback(event);
      if (entry.once) {
        const current = this.listeners.get(name) || [];
        this.listeners.set(name, current.filter(candidate => candidate !== entry));
      }
    }
  }

  send(data, callback) {
    this.sent.push(Buffer.from(data));
    const sendError = FakeWebSocket.nextSendError;
    FakeWebSocket.nextSendError = null;
    if (callback) queueMicrotask(() => callback(sendError));
    if (FakeWebSocket.nextServerFrame) {
      const frame = FakeWebSocket.nextServerFrame;
      FakeWebSocket.nextServerFrame = null;
      // A real network reply cannot be emitted synchronously inside send().
      // Deliver it on the next event-loop turn, when socket I/O could fire.
      setImmediate(() => this.emit('message', { data: frame }));
    }
  }

  close() {
    if (this.readyState !== 3) {
      this.readyState = 3;
      this.emit('close', { code: 1000, reason: '' });
    }
  }
}

const context = vm.createContext({
  require,
  Buffer,
  console,
  URL,
  AbortController,
  fetch,
  WebSocket: FakeWebSocket,
  setTimeout,
  clearTimeout,
  queueMicrotask,
});
const source = renderElectronPrefix(fs.readFileSync(TEMPLATE, 'utf8'));
vm.runInContext(source + `
globalThis.__clientExports = {
  Client, WSClient, HTTPClient, MessageBuilder, DecryptionError,
  CheckInMessage, InitiateBINDReq, SendDataMessage, CheckOutMessage
};`, context, { filename: TEMPLATE });

const C = context.__clientExports;
const KEY = crypto.createHash('sha256').update('test-key').digest();
const checkoutFrame = () => {
  const frame = Buffer.alloc(8);
  frame.writeUInt32BE(0x07, 0);
  frame.writeUInt32BE(8, 4);
  return frame;
};

class RecordingClient extends C.Client {
  constructor() {
    super(KEY, 'test-agent');
    this.sent = [];
  }
  async sendUpstreamMessage(message) {
    this.sent.push(message);
  }
}

class FakeSocket extends EventEmitter {
  constructor() {
    super();
    this.writes = [];
    this.destroyed = false;
    this.resumed = false;
  }
  write(data) { this.writes.push(Buffer.from(data)); return true; }
  destroy() { this.destroyed = true; }
  resume() { this.resumed = true; }
}

let failures = 0;
async function test(name, body) {
  try {
    await body();
    console.log(`PASS ${name}`);
  } catch (error) {
    failures += 1;
    console.log(`FAIL ${name}: ${error.message}`);
  }
}

(async () => {
  await test('concatenated server messages preserve order', async () => {
    const client = new RecordingClient();
    const raw = Buffer.concat([
      client.serializeMessages([
        C.CheckInMessage('client-1'),
        C.InitiateBINDReq('B', '127.0.0.1', 0, '127.0.0.1', 80),
      ]),
      checkoutFrame(),
    ]);
    assert.strictEqual(
      client.deserializeMessages(raw).map(message => message.kind).join(','),
      'CheckInMessage,InitiateBINDReq,CheckOutMessage'
    );
  });

  await test('decryption error propagates', async () => {
    const client = new RecordingClient();
    const raw = Buffer.from(client.serializeMessages([C.SendDataMessage('T', Buffer.from('hello'))]));
    raw[raw.length - 1] ^= 0xff;
    assert.throws(() => client.deserializeMessages(raw), C.DecryptionError);
  });

  await test('data then empty data closes only matching connection', async () => {
    const client = new RecordingClient();
    const socket = new FakeSocket();
    const other = new FakeSocket();
    client.tcpClients.set('T', socket);
    client.tcpClients.set('OTHER', other);
    await client.dispatchMessage(C.SendDataMessage('T', Buffer.from('abc')));
    assert.deepStrictEqual(socket.writes, [Buffer.from('abc')]);
    await client.dispatchMessage(C.SendDataMessage('T', Buffer.alloc(0)));
    assert(socket.destroyed);
    assert(!client.tcpClients.has('T'));
    assert(client.tcpClients.has('OTHER'));
  });

  await test('unknown late data is ignored', async () => {
    const client = new RecordingClient();
    await client.dispatchMessage(C.SendDataMessage('missing', Buffer.from('late')));
    assert.strictEqual(client.tcpClients.size, 0);
  });

  await test('failed TCP reply closes waiting RPF socket', async () => {
    const client = new RecordingClient();
    const socket = new FakeSocket();
    client.tcpClients.set('T', socket);
    await client.dispatchMessage({
      kind: 'InitiateTCPClientRep', client_id: 'T', reason: 5
    });
    assert(socket.destroyed);
    assert(!client.tcpClients.has('T'));
  });

  await test('successful TCP reply resumes waiting RPF socket', async () => {
    const client = new RecordingClient();
    const socket = new FakeSocket();
    client.tcpClients.set('T', socket);
    await client.dispatchMessage({
      kind: 'InitiateTCPClientRep', client_id: 'T', reason: 0
    });
    assert(socket.resumed);
    assert(client.tcpClients.has('T'));
  });

  await test('real bind then same-ID stop finishes stopped', async () => {
    const client = new RecordingClient();
    await client.handleBind(C.InitiateBINDReq('B', '127.0.0.1', 0, '127.0.0.1', 80));
    assert.strictEqual(client.remotePortForwarders.length, 1);
    const owned = new FakeSocket();
    owned._bindId = 'B';
    const unrelated = new FakeSocket();
    unrelated._bindId = 'OTHER';
    client.tcpClients.set('owned', owned);
    client.tcpClients.set('other', unrelated);
    await client.handleBind(C.InitiateBINDReq('B', '', 0, '', 0));
    await new Promise(resolve => setImmediate(resolve));
    assert.strictEqual(client.remotePortForwarders.length, 0);
    assert(owned.destroyed);
    assert(!unrelated.destroyed);
    assert(!client.tcpClients.has('owned'));
    assert(client.tcpClients.has('other'));
  });

  await test('checkout overrides a mixed WebSocket batch', async () => {
    const client = new C.WSClient('ws://127.0.0.1', KEY, 'test-agent');
    client.ws = new FakeWebSocket();
    await new Promise(resolve => queueMicrotask(resolve));
    const started = client.start();
    await new Promise(resolve => queueMicrotask(resolve));
    const mixed = Buffer.concat([
      client.serializeMessages([C.InitiateBINDReq('B', '127.0.0.1', 0, '127.0.0.1', 80)]),
      checkoutFrame(),
    ]);
    client.ws.emit('message', { data: mixed });
    await started;
    assert(client.killed);
    assert.strictEqual(client.remotePortForwarders.length, 0);
  });

  await test('known-ID HTTP reconnect dispatches queued checkout', async () => {
    const client = new C.HTTPClient('http://127.0.0.1', KEY, 'test-agent');
    client.identifier = 'known-id';
    client._postBinary = async () => checkoutFrame();
    await client.connect();
    assert(client.killed, 'known-ID connect ignored the server response containing queued Checkout');
  });

  await test('known-ID WebSocket reconnect receives immediate queued checkout', async () => {
    const client = new C.WSClient('ws://127.0.0.1', KEY, 'test-agent');
    client.identifier = 'known-id';
    FakeWebSocket.nextServerFrame = checkoutFrame();
    await client.connect();
    const started = client.start();
    setTimeout(() => client.ws.close(), 10);
    await started;
    assert(client.killed, 'immediate reconnect frame arrived before the persistent message listener');
  });

  await test('WebSocket pending batch survives send failure', async () => {
    const client = new C.WSClient('ws://127.0.0.1', KEY, 'test-agent');
    client.identifier = 'known-id';
    const message = C.SendDataMessage('T', Buffer.from('ordered'));
    client.sendUpstreamMessage(message);
    client.ws = new FakeWebSocket();
    await new Promise(resolve => queueMicrotask(resolve));
    FakeWebSocket.nextSendError = new Error('injected send failure');
    await client.sendLoop();
    assert.strictEqual(client._pending.length, 1);

    const replacement = new FakeWebSocket();
    client.ws = replacement;
    await new Promise(resolve => queueMicrotask(resolve));
    const sender = client.sendLoop();
    await new Promise(resolve => setImmediate(resolve));
    replacement.close();
    client._signalSendLoop();
    await sender;

    assert.strictEqual(client._pending.length, 0);
    const parsed = client.deserializeMessages(replacement.sent[0]);
    assert.strictEqual(parsed.map(item => item.kind).join(','), 'CheckInMessage,SendDataMessage');
    assert.deepStrictEqual(Buffer.from(parsed[1].data), Buffer.from('ordered'));
  });

  process.exitCode = failures ? 1 : 0;
})();
