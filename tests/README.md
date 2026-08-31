# Client conformance tests

This suite tests the client behavior described by `docs/client.pseudo` against
the exact client submodule revisions pinned by the parent Messenger commit.
Generated clients are compiled/executed; template inspection is not used as a
substitute for process-level testing.

## Layers

| Layer | What it proves |
|---|---|
| Builder | The aggregate and direct builders expose the same options, defaults, rendered configuration, and language-specific flags. |
| Protocol contract | Message concatenation/order, AES-CBC behavior, decryption failures, empty-data close, checkout priority, bind stop, and reconnect response behavior. |
| Real CLI E2E | The real server CLI drives generated Python, Node.js, and compiled C# processes over HTTP and WebSocket. Commands are marked `>>> MESSENGER COMMAND:` in the transcript. |
| TCP stream oracle | LPF, RPF, and SOCKS carry 30 numbered and hashed application records over IPv4, hostname resolution, and IPv6. Writes are deliberately fragmented and coalesced. |
| Lifecycle | Listener refusal, client process exit, server TCP-client collections, scanner workers, asyncio tasks, child processes, and Linux `/proc/<pid>/fd` targets are captured around stop/reconnect/checkout. |

TCP is a byte stream and does not preserve packets or individual `send()`
boundaries. `tcp_frames.py` therefore verifies reconstructed application
records and their sequence, digest, content, and total byte count. A dropped,
duplicated, reordered, or corrupted byte fails the test without making a false
claim about packet boundaries.

## Pseudocode coverage

| Pseudocode area | Tests |
|---|---|
| Builders, embedded defaults, runtime overrides, missing/unknown arguments | `test_builders.py`, `test_runtime_args.py`, E2E user-agent/server URL/key checks |
| Crypto, framing, concatenation, malformed/incomplete input, DecryptionError | Python/Node protocol tests and compiled C# contract runner |
| HTTP and WebSocket connect/reconnect/checkout | E2E initial connection, server restart, queued checkout, and terminal process-exit checks |
| TCP request/reply/data/empty close | Protocol tests plus real LPF/RPF/SOCKS streams |
| IPv4, hostname, IPv6 | 30-record tests through every forwarding mode (IPv6 is reported unavailable only if the runner has no IPv6 loopback) |
| Remote bind start/stop and connection ownership | Protocol tests, real remote forwards, listener stop probes, and server collection snapshots |
| SOCKS5 parsing/replies | IPv4/domain/IPv6 CONNECT plus malformed greeting, unsupported command, invalid reserved byte, and unsupported address type |
| Scanner lifecycle | Open/closed results, detailed display, stop, retained stopped display, worker/task cleanup |
| Cleanup and leaked resources | Process exit, listener probes, internal object/task snapshots, and Linux descriptor deltas |

The workflow runs on `ubuntu-latest` and `windows-latest`. Linux retargets a
generated copy of the C# source to .NET 8 so the actual code can execute there;
the committed builder template remains `net472`. Windows builds and executes
the intended `net472` artifact. Linux drives the terminal CLI with a PTY.
Windows uses a test-only control socket that invokes the same
`Manager.execute_command()` parser and command handlers, avoiding unreliable
prompt redraw matching when no POSIX PTY exists. Linux provides descriptor
target enumeration; Windows receives the shared listener, collection, task,
and process checks.

TLS certificate handling, a real authenticated upstream proxy, and Electron's
renderer runtime require separate infrastructure and are not silently counted
as passing. The builder/output portions of those options are covered here.

## Local entry points

```text
python tests/test_builders.py
python tests/test_protocol_python.py
node tests/test_protocol_node.js
python tests/build_generated_clients.py --output-dir .conformance-artifacts --target-framework net8.0
dotnet run --project tests/csharp_contract/Contract.csproj -c Release
python tests/test_runtime_args.py --manifest .conformance-artifacts/manifest.json
python tests/run_e2e.py --manifest .conformance-artifacts/manifest.json --output-dir .conformance-results/e2e
```
