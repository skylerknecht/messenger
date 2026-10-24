// Run against a rendered client: node tests/polling_node.js client.js [fixed]
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const fixed = process.argv[3] === 'fixed';
const source = fs.readFileSync(process.argv[2], 'utf8');
class Client {
  constructor() { this.killed = false; this.identifier = 'test'; }
  async readvertiseForwarders() {}
  async dispatchMessage() {}
  handleCheckout() { this.killed = true; }
}
const sandbox = {
  Client, setTimeout, clearTimeout, Buffer, URL,
  http: { Agent: class { destroy() {} } }, https: { Agent: class { destroy() {} } },
  Math: Object.assign(Object.create(Math), { random: () => 0.5 }),
  MAX_BATCH_SIZE: 100,
  CheckInMessage: () => ({ kind: 'CheckInMessage' }),
  DecryptionError: class extends Error {},
};
vm.runInNewContext(source.slice(source.indexOf('class HTTPClient'), source.indexOf('/* REMOTE PORT FORWARDER */'))
                   + '\nglobalThis.HTTPClient = HTTPClient;', sandbox);
const create = () => new sandbox.HTTPClient('http://localhost', Buffer.alloc(32), 'test');

async function main() {
  const client = create();
  const batches = [], delays = [];
  client.serializeMessages = batch => { batches.push(batch); return Buffer.alloc(0); };
  client._postBinary = async () => batches.length === 51 ? Buffer.alloc(0) : Buffer.from('response');
  client.deserializeMessages = () => [{ kind: batches.length === 52 ? 'SendDataMessage' : 'CheckInMessage' }];
  client._waitForPoll = async delay => {
    delays.push(delay);
    if (delays.length === 50) await client.sendUpstreamMessage({ kind: 'SendDataMessage' });
    if (delays.length === 53) client.handleCheckout();
  };
  await client.start();
  if (fixed) assert(delays.every(delay => delay === 100));
  else {
    assert(Math.abs(delays[0] - 110) < 1e-8);
    assert.strictEqual(delays[49], 10000);
    assert.strictEqual(batches[50].length, 2);
    assert.strictEqual(delays[50], 100);
    assert.strictEqual(delays[51], 100);
    assert(Math.abs(delays[52] - 110) < 1e-8);
  }
  for (const action of ['send', 'checkout', 'close']) {
    const next = create();
    let completed = false;
    const waiting = next._waitForPoll(10000).then(() => { completed = true; });
    if (action === 'send') await next.sendUpstreamMessage({ kind: 'SendDataMessage' });
    else if (action === 'checkout') next.handleCheckout();
    else next.closeTransport();
    await new Promise(resolve => setImmediate(resolve));
    if (fixed && action === 'send') {
      assert(!completed);
      next.handleCheckout();
    }
    const timeout = setTimeout(() => { throw new Error('Polling wait did not wake'); }, 500);
    try { await waiting; } finally { clearTimeout(timeout); }
    assert.strictEqual(next._pollWake, null);
  }
  console.log(`PASS Node polling (${fixed ? 'fixed' : 'adaptive'})`);
}
main().catch(error => { console.error(error); process.exitCode = 1; });
