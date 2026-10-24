const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[2], 'utf8').split('/* ARG PARSING */')[0];
const sandbox = { require, Buffer, URL, console, process, setTimeout, clearTimeout };
vm.runInNewContext(source + '\nglobalThis.HTTPClient = HTTPClient;', sandbox);
const client = new sandbox.HTTPClient('http://localhost', Buffer.from(process.argv[4], 'hex'), 'test');
for (const message of client.deserializeMessages(Buffer.from(process.argv[3], 'hex'))) {
  client.dispatchMessage(message);
}
assert.strictEqual(client.tcpClients.size, 0);
assert.strictEqual(client.upstream_messages.length, 0);
assert.strictEqual(client.killed, false);
client.closeTransport();
console.log('PASS Node: encrypted keep-alive discarded without creating a TCP connection');
