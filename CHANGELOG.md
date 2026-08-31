# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Spec

#### Changed

- Removed `drain(socket)` from `write_loop` — max write is 4096 bytes, well within any kernel send buffer.

### Server

#### Fixed

- `SocksTcpClient.handle_initiate_tcp_client_rep` now writes the SOCKS reply through `send_data`, so a write failure triggers downstream close notification instead of leaking the remote TCP connection.
- `HTTPMessenger.status` now shows "disconnected" when no check-in received in the last 5 seconds — previously displayed the stale delta from the previous pair of check-ins, showing a healthy status for dead messengers.
- HTTP reconnect detection in `checkin_http` now calls `check_in()` before testing `check_in_delta` — previously read the delta from the prior cycle, firing the reconnect message one poll late.
- `@require_messenger` now blocks commands on checked-out messengers — previously allowed new forwarders and scanners on dead sessions.
- Scanner port parser validates 1–65535 range — out-of-range ports are skipped with a warning instead of silently accepted.
- `_handle_send_data` now checks scanner scan entries before warning about unknown client IDs — scanner-originated open ports that send banners no longer produce spurious warnings.

#### Changed

- Centralized unexpected error logging into `Logger.log_exception` and `UpdateCLI.log_unexpected_error` — all generic `except Exception` handlers now write tracebacks to `exceptions.log` and display a CLI warning.
- `Logger._append` warns to stderr on write failure instead of silently swallowing the exception.
- Added `jinja2` to `requirements.txt`.
- `TcpClient.send_data` accepts a `cleanup` flag — when set, calls `_cleanup()` after a successful write. Used by the SOCKS handler to write the error reply and close in one call.
- Removed all `await writer.drain()` calls from `TcpClient` and `SocksTcpClient` — max write size is 4096 bytes, always fits in the kernel send buffer.

### Clients

#### Fixed

- **Node.js**: Removed `async` from `dispatchMessage` and its caller in the receive loop — `await` on the synchronous function created microtask yields that allowed inter-frame message interleaving, violating wire order.
- **Node.js**: HTTP `connect()` and `start()` now let `DecryptionError` propagate instead of wrapping it in a generic `Error` — a wrong encryption key previously caused infinite retry loops instead of stopping.
- **C# HTTP**: `ConnectAsync` now uses `DeserializeMessages` (plural) with a `Count > 0` guard instead of `DeserializeMessage` (singular) — a truncated response previously threw `NullReferenceException`.
- **C# WebSocket**: `ConnectAsync` checks `responseMessages.Count > 0` before accessing `responseMessages[0]` — an empty response previously threw `ArgumentOutOfRangeException`.
- **Python**: `RemotePortForwarder.start()` catches `socket.gaierror` separately with `return 4` — DNS failures previously fell through to the success path because the handler was missing a `return` statement.
- **C#**: `RemotePortForwarder.StartAsync` maps `SocketError.HostNotFound` to reason 4 — DNS resolution failures previously fell through to reason 1 (general failure).

#### Changed

- **Node.js**: Removed `--messenger-id` from README options table and documentation.

### Tests

#### Added

- Client conformance test suite — builders, protocol contracts (Python/Node.js/C#), runtime args, E2E CLI, and TCP stream oracle.
- GitHub Actions workflow (`tests.yml`) with HTML report, badge JSON output, and percentage summary. Manual dispatch only.

## [0.9.2] - 2026-08-27

### Spec

#### Changed

- WebSocket and HTTP send loops now use an instance-level `_pending` buffer that persists across reconnects — messages are drained from the queue into `_pending`, sent as a batch, and only cleared after confirmed delivery.
- `connect()` now calls `close_transport()` before opening a new connection, eliminating the need for separate cleanup calls in the reconnect loop.
- Removed `_requeue_first`/`enqueue_front` pattern entirely — messages never leave `_pending` until confirmed sent.
- HTTP clients now drain all available messages instead of capping at 5 per poll.

### Clients

#### Changed

- Python, C#, and Node.js WebSocket clients rewritten to use `_pending` buffer pattern for send loops.
- Python, C#, and Node.js HTTP clients now drain all queued messages per poll cycle.
- Python WebSocket client creates a fresh `aiohttp.ClientSession` on each `connect()` and closes both the websocket and session in `close_transport()`, fixing an unclosed connection leak on reconnect.
- Removed `_requeue_first`, `RequeueFirst`, and `reset_transport` from all clients.
- **Node.js**: Removed `--messenger-id` builder option -- Python and C# clients don't have it.
- **Node.js**: Removed redundant `this.identifier = ''` from `HTTPClient` constructor -- already set by `super()` in `Client`.

#### Fixed

- **C#**: `HandleInitiateTCPClientReqAsync` now iterates all resolved addresses (IPv4-first) with a shared 5-second deadline instead of connecting to only the first address.
- **C#**: Timeout exceptions in the TCP connect loop now escape the inner `catch (SocketException)` via an exception filter, preventing a `NullReferenceException` on the already-disposed socket.
- **C#**: Timed-out `ConnectAsync` tasks are now observed to prevent `UnobservedTaskException` on .NET Framework 4.7.2.
- **C#**: `BuildInitiateTCPClientRep` conditionally serializes `remote_addr`/`remote_port` only when `remoteAddr` is non-empty, matching server-side behavior.
- **C#**: `RemotePortForwarder.StartAsync` uses `Dns.GetHostAddressesAsync` instead of sync `Dns.GetHostAddresses`, and prefers IPv4 addresses for listen binding.
- **C#**: `ParseArgs` bounds-checks flag values -- a trailing `--server-url` with no value now prints an error instead of crashing with `IndexOutOfRangeException`.
- **Python**: `build_initiate_tcp_client_rep` conditionally serializes `remote_addr`/`remote_port` only when `remote_addr` is non-empty, matching server-side behavior.
- **Python**: `alphanumeric_identifier` uses `secrets.choice` instead of `random.randint` -- `random` is not cryptographically secure.

### Server

#### Fixed

- `_handle_send_data` now logs a warning for unknown `client_id` instead of silently dropping.
- `process_upstream_messages` wraps each message dispatch in try/except so a single handler failure no longer drops remaining messages in the batch.
- `checkin_ws` in the HTTP/WS server now wrapped in try/except with a clean websocket close on failure, matching `checkin_http` behavior.
- `sent_bytes` now counted after successful send instead of at queue time, fixing overcounting on WS send failures.
- Removed unused `InitiateBINDReq` import.
- Fixed `ssl_cert_cert` typo in `http_ws_server.py`.

#### Changed

- `Scanner.start_time` initialized to `time.time()` in `__init__` instead of `None`, preventing a potential `TypeError` in `formatted_runtime`.
- Scanner uses `asyncio.Semaphore` instead of custom `AdmissionController`.
- Scanner summary table now shows `State` column (running/stopped/completed) with color coding.
- `checked_out` lifecycle flag on `Messenger` base class guards downstream sends, upstream processing, forwarder accepts, and scanner workers.
- `TcpClient._cleanup` callsite pattern: `_cleanup()` returns bool, callsite sends peer close signal via `send_message_downstream` -- eliminates the `notify_peer` parameter and synchronous queue put.
- `cancel_send_task()` extracted from `set_websocket()` for reuse in WS handler cleanup.
- WebSocket handler `finally` block uses ownership-aware sender cleanup.
- Replaced non-ASCII characters (em dashes, arrows) with ASCII equivalents across all source files and client templates.
- `_split_config` parser replaces `str.split(':')` for forwarder configuration, supporting bracketed IPv6 addresses (e.g., `[::1]:8080:[::1]:80`).
- Removed `is_valid_domain` and `is_valid_ip` validators -- the forwarder passes the listening host directly to `asyncio.start_server` and the destination to the client, letting the OS validate.
- `SocksProxy.NAME` renamed from "Socks Proxy" to "SOCKS Server".
- Forwarder status messages now use `_endpoint_str()` and the forwarder's `NAME` constant.
- `portscan` concurrency capped at 1000 unless `--force-concurrency` is passed.
## [0.9.1] - 2026-08-25

### Spec

#### Changed

- Renamed `send_downstream_message` to `send_upstream_message` and `downstream_queue` to `upstream_queue` across all transport classes — messages TO the server are upstream from the client's perspective.
- WebSocket send loop catch block now specifies `upstream_queue.enqueue_front(message)` — a failed send must go back to the front of the queue, not the back, to preserve message ordering.

#### Fixed

- HTTP polling loop now uses a persistent pending buffer — messages are drained into `pending` only when empty, and `pending` is cleared only after a successful POST. Previously, messages dequeued before a failed POST were lost permanently.
- `killed = true` moved to the top of CheckOut handler — previously set last, allowing new handlers to spawn during teardown.
- `handle_tcp_connect` and `handle_bind` guarded with `if killed: return` for threaded implementations — prevents orphan connections/listeners after CheckOut.
- `stream()` finally block skips sending the upstream close signal when `killed` is set — transport is already torn down.

### Server

#### Fixed

- `Forwarder.on_close` callback now returns a boolean indicating whether removal succeeded, preventing duplicate close signals when both sides race to clean up the same TCP client.
- `TcpClient._cleanup` returns `False` when `on_close` reports the client was already removed; callers skip the redundant upstream close signal.
- `TcpClient.send_data` now sends an upstream close signal on write failure — previously `_cleanup()` was called but no close signal was sent, leaving the server-side entry orphaned.
- `SocksProxy.__init__` uses `super().__init__()` instead of manually duplicating parent constructor logic.
- `RemotePortForwarder.close_all_clients` no longer resets `self.clients = []` — removal is handled by the `on_close` callback, and resetting the list races with in-flight cleanup.
- `RemotePortForwarder.handle_initiate_tcp_client_req` now sends `InitiateTCPClientRep` and calls `client.initiate_tcp_client()` only after confirming success (reason=0) — previously the stream was started before the reply was sent.
- `RemotePortForwarder` catches `asyncio.TimeoutError` alongside `socket.timeout` for connect timeouts.
- `generator.py` uses `secrets` module instead of `random` for all identifier generation — `random` is not cryptographically secure.
- `messengers.py` byte counters (`sent_bytes`, `received_bytes`) moved from `check_in()` to `__init__` — previously reset to zero on every check-in, losing cumulative transfer stats.
- `http_ws_server.py` WebSocket reconnect now drains queued messages atomically and processes the remaining batch — previously re-enqueued messages one at a time, risking reordering.
- `logger.py` log file paths are now `@property` methods computing the date at call time — previously computed once at `__init__`, so logs after midnight wrote to yesterday's file.
- `message.py` validates `payload_len >= 0` before reading payload bytes — a `message_length` less than 8 previously caused an underflow.
- `manager.py` error message for invalid logging types corrected from "Valid types: 1-4" to "Valid types: 1-7".
- `manager.py` display calls changed from `'status'` to `'information'` for non-error informational messages.
- `manager.py` `user_input.split(' ')` changed to `user_input.split()` to handle multiple spaces and leading/trailing whitespace.
- `manager.py` bare `except:` clauses narrowed to `except (ValueError, TypeError):` in concurrency/port parsing.
- `SocksTcpClient.negotiate_transport` sends a proper SOCKS5 error reply (command not supported, 0x07) when the command is not CONNECT — previously returned `False` with no reply.
- `SocksTcpClient.negotiate_address` sends a proper SOCKS5 error reply (address type not supported, 0x08) on unsupported address types — previously returned `False` with no reply.
- `WebSocketMessenger._send_loop` now re-enqueues a failed message at the front of the queue via drain-and-refill — previously the message was lost on send failure, and `CancelledError` (a `BaseException`) bypassed the `except Exception` handler entirely.
- `http_ws_server.py` constructor parameter renamed from `ssl` to `ssl_cert` to avoid shadowing the `ssl` module import — `ssl.create_default_context()` would fail at runtime when an SSL cert was configured.
- `sent_bytes` tracking centralized in `send_message_downstream` using serialized message size — previously scattered across `tcp_clients.py` with a hardcoded `+= 20` for headers that undercounted actual wire bytes.
- `received_bytes` tracking centralized in the engine (`checkin_http` and `send_messages_upstream`) using raw `len(data)` — previously scattered across `tcp_clients.py` and counted deserialized payload length instead of wire bytes.

### Client

#### Changed

- All clients: renamed `send_downstream_message` to `send_upstream_message` and `downstream_queue`/`downstream_messages` to `upstream_queue`/`upstream_messages`.

#### Fixed

- **All clients**: HTTP polling loop now uses a persistent pending buffer (`_pending` field) — messages are drained from the queue only when pending is empty, and pending is cleared only after a successful POST. Failed requests retry the same messages on reconnect instead of losing them.
- **All clients**: `killed` flag set first in CheckOut handler, before teardown — prevents new TCP client handlers from spawning during cleanup.
- **C#**: `HandleInitiateTCPClientReqAsync` and `HandleBindAsync` guarded with `Killed` checks — prevents orphan connections/listeners when `Task.Run` dispatches handlers concurrently with CheckOut teardown.
- **All clients**: stream/socket-close finally blocks skip sending the upstream empty `SendDataMessage` close signal when `killed` is set — the transport is already torn down.
- **C#**: concurrent `WriteAsync` calls on `NetworkStream` serialized through per-client `BlockingCollection<byte[]>` writer threads — concurrent writes from `Task.Run` handlers corrupted the forwarded TCP byte stream.
- **C#**: WebSocket send loop replaced `SemaphoreSlim` + `ConcurrentQueue` with `BlockingCollection` — the semaphore accumulated excess permits on batch drains, causing spurious wake-ups and empty sends.
- **C#**: `static Random` replaced with `RNGCryptoServiceProvider` for identifier generation — `Random` is not thread-safe and corrupts under concurrent `Task.Run` access, returning 0 indefinitely.
- **C#**: `HttpResponseMessage` wrapped in `using` block — previously leaked the response on non-200 status, exhausting the 2-connection-per-host pool after two consecutive server errors.
- **Node.js**: WebSocket `connect()` now closes the previous `ws` instance before creating a new one — previously leaked the old socket on reconnect.
- **Python**: added missing `import sys` — `non_main_thread` builds crashed at startup.
- **Python and C#**: WebSocket send loop now re-enqueues a failed message at the front of the queue via drain-and-refill, catching both `Exception` (break) and `BaseException`/`OperationCanceledException` (raise) — previously a mid-flight failure lost the dequeued message or reordered it behind newer messages.

## [0.9.0] - 2026-08-12

### Server

#### Added

- `display` command replacing `debug` — per-module toggle for debug output and status types (warnings, successes, infos, errors) across three modules: handlers, messengers, forwarders.
- All display calls carry a `display_module` parameter so per-module filtering works for both debug and status messages.
- Table output for `display` status using the existing `create_table()` system.
- Global type toggles: `display debug` toggles debug for all modules, `display warnings` toggles warnings globally.
- Comma-separated type support: `display handlers debug,warnings` toggles multiple types in one command.

#### Changed

- `debug` command removed; replaced by `display`.
- Debug is a single on/off toggle per module — no more numeric levels.
- Status types (warnings, errors, successes, infos) toggle on each invocation instead of requiring explicit on/off arguments.
- Handler warnings are off by default.

## [0.8.1] - 2026-08-12

### Server

#### Fixed

- False "reconnected" messages for WebSocket messengers that never actually disconnected. Reconnect detection moved from the data path (`get_upstream_messages`) to the handler layer.
- `rename` now rejects names that collide with existing command names.

#### Changed

- HTTP messenger status now shows the actual polling interval (delta between the last two check-ins) instead of time since the last check-in.
- Reconnect detection and check-in bookkeeping consolidated into `Messenger.check_in()`.
- WebSocket reconnect fires immediately; HTTP reconnect fires after 60 seconds of absence.
- Upstream message queue stores message objects instead of pre-serialized bytes; WebSocket reconnect drains queued messages through `send_message_upstream` individually with error handling.
- `set_websocket()` simplified to only set the websocket reference (sync, no side effects).
- `send_messages()` no longer calls `get_upstream_messages()`; HTTP handler calls it directly.

## [0.8.0] - 2026-08-11

### Spec

#### Added

- `CheckOutMessage` (0x07) — server-to-client kill signal. Empty payload, not encrypted. The client tears down all RPF listeners and TCP clients, then returns from `main()` without reconnecting. No `exit()`/`abort` — a graceful unwind like decryption failure.
- `killed` flag on the client base class, checked after `start()` returns and inside the reconnect loop.
- Receive loops check for `CheckOutMessage` before spawning handlers — handled inline so the loop breaks immediately.

### Server

#### Added

- `kill` command — sends a `CheckOutMessage` to a messenger. Supports targeting by ID/name or defaults to the current messenger when interacting. Does not remove the messenger from the list.
- `CheckOutMessage` (type 7) added to logging type map.
- `rename` now accepts a single argument when interacting with a messenger, renaming the current messenger.

#### Changed

- Status messages: "Sent kill signal" → "Queued kill signal", "Sent bind request" → "Queued bind request" to reflect that messages are queued, not delivered.
- RPF "is gone" message unified to "is no longer bound" at status level.
- Removed redundant "has stopped forwarding" message from remote port forward stop — the "removed from forwarders" and "is no longer bound" messages are sufficient.

### Client

#### Added

- All clients: `CheckOutMessage` (0x07) handler that stops all RPF listeners, closes all TCP clients, sets a `killed` flag, and lets `start()` return naturally. The reconnect loop checks `killed` and exits instead of retrying.

#### Changed

- All clients: receive loops now check for `CheckOutMessage` before spawning handlers, handling it inline so the loop exits immediately.

#### Fixed

- C# client: reconnection failed with "CancellationTokenSource has been disposed" after a dropped connection. The CTS is now nulled after disposal.

## [0.7.2] - 2026-08-10
### Spec

#### Changed

- Reworked the remote-port-forward lifecycle in `docs/client.pseudo`:
  - **Empty listening host is a sentinel.** A `BindReq` with `listening_host=""` means **stop** this bind; a `BindRep` with `listening_host=""` means the RPF is **gone** (failed / crashed / torn down). Replaces the old "duplicate bind_id toggles shutdown" and `0.0.0.0:0` conventions.
  - **Empty destination = orphan.** A forwarder the server learns about (via a re-advertised `BindRep`) but has no destination for is stored with an empty destination; it never routes until the operator re-runs `remote` to set the destination.
  - `InitiateTCPClientReq` now carries the originating **listening host:port** so the server maps a forwarded connection to the exact RPF instead of guessing by destination.
  - Clients emit an empty-host `BindRep` on any listener death; the server removes the forwarder and tears down its connections.

### Server

#### Changed

- Remote-port-forward control plane reworked to the model above (empty-host stop/gone, orphan adopt, conflict-replace, connection teardown on remove). Routing forwarded connections now matches on the listening endpoint carried in `InitiateTCPClientReq`.
- `remote` command adopts an orphan RPF (sets destination, no re-bind) instead of sending a duplicate bind request; rejects a `remote` on a listening endpoint that already has a configured forward.
- `stop` on an unconfirmed RPF (no `BindRep` received yet) removes it locally and closes its connections without signaling the client; a confirmed RPF sends the empty-host stop signal.
- An orphan RPF denies forwarded connections with reason 2 until the operator configures a destination.
- `forwarders` table shows `(unconfigured)` for an orphan RPF's destination.
- Applied single-threaded-asyncio discipline to `messenger.forwarders` mutations (atomic claim-then-await, snapshot-before-iterate) instead of locking.
- Removed timestamps from CLI status messages — the bracket-prefix icon is now the only decoration.
- Context-aware logging display: `logging` output shows which message types are being recorded by name (e.g. `CheckInMessage, SendDataMessage`) or `no messages` when none are enabled.
- `BindRep` with `reason != 0` now logs at error severity instead of warning.
- Missing `User-Agent` on a messenger defaults to `•••` instead of `Unknown`.

#### Fixed

- ANSI corruption when async output interleaved with the prompt — replaced `patch_stdout` with `\x1b[2K` erase-line plus prompt invalidation.
- `logging` command displayed `(no messages)` as a suffix instead of inline `and no messages to:`.

### Client

#### Changed

- Clients re-advertise all active RPFs on every reconnect (a real-host `BindRep` per forwarder at the top of `start`), so a restarted server re-learns them as orphans that the operator can re-adopt.
- `handle_bind` recognizes the empty-host stop signal (tear down listener + connections, reply empty-host `BindRep`), is idempotent on duplicate bind requests, and replies with an empty-host `BindRep` on bind failure.
- RPF listener crash-emit: if the accept loop exits (crash or intentional stop) the client emits an empty-host `BindRep` and removes the forwarder from its list; a `_gone` guard prevents double-reporting.
- `InitiateTCPClientReq` now appends the RPF's listening host:port so the server can route by exact endpoint.
- Retry loop now logs the attempt number (`[*] Attempting to reconnect (1/5)…`) with `consecutive_failures` incremented before the attempt, not after a failure.
- `connect()` and `start()` are wrapped in separate try blocks so a transport-connect failure is distinguished from a session-start failure.

#### Fixed

- C# and Node.js: removed a duplicate `consecutiveFailures++` in the catch block that double-counted failures after the increment was moved before the try block.
- Python: `namedtuple` `defaults` parameter replaced with a pattern compatible with Python 3.6.

## [0.7.1] - 2026-08-08

### Spec

#### Changed

- Established the single-writer send rule for WebSocket clients: a WebSocket is one ordered byte stream, so exactly one task may write to it — all sends flow through a single signal-driven send loop (a library that serializes internally, like Node's `ws`, satisfies this). Supersedes the earlier note that stateful clients may send immediately from any task
- Decryption failure is now the one sanctioned exception to "never stop": a client that cannot decrypt server traffic (almost always a wrong encryption key) logs a distinctive error and returns from `main()` instead of reconnecting in a loop that can never succeed

### Client

#### Fixed

- All clients: handle an `InitiateTCPClientRep` that omits the optional `remote_addr`/`remote_port` fields. The server leaves them off every remote-port-forward reply and denial, so the client's unconditional read overran the buffer (`Not enough bytes to read a 32-bit value`) and tore down the whole tunnel on any remote-forward hit
- C# and Node.js: added a 5-second TCP connect timeout so connections to unresponsive hosts fail promptly instead of hanging on the OS default
- C#: HTTP client now applies a 10-second connect and 15-second poll request timeout instead of the 100-second `HttpClient` default
- C#: CLI string overrides use truthiness so an empty value falls back to the embedded default (`--server-url ""`, `--user-agent ""`, `--proxy ""`)
- C#: removed the duplicate `[+] Connected to` log emitted from inside the HTTP/WebSocket connect (main logs it once)
- Node.js and Python: standardized the reconnection-failure log to `[!] Reconnection failed: {error}`
- Python: guard against `message_length < 8` during deserialization to prevent payload-length underflow on malformed frames
- Python: HTTP poll requests now use a 15-second timeout (connect stays at 10 seconds)

#### Changed

- All clients: an AES decryption failure now logs `[!] Decryption failed — the encryption key is likely incorrect …` and stops the client, instead of silently retrying forever. A wrong key connects fine on the plaintext check-in and only surfaces on the first encrypted message, so the old behavior looked like a hang
- C# and Python WebSocket clients serialize all sends through a single signal-driven send loop (`SemaphoreSlim` in C#, `asyncio.Queue` in Python) instead of sending immediately from concurrent handler tasks. Concurrent sends were aborting the C# `ClientWebSocket` (`… has been transitioned into the 'Aborted' state`) under remote-port-forward load and risked corrupting aiohttp frames; the loop wakes on enqueue (no polling latency) and coalesces queued messages into one frame. Node.js already serializes inside `ws` and is unchanged

### Server

#### Added

- The remote port forwarder now logs when it *sends* a bind request or teardown to a client (`Sent bind request to Messenger …` / `Sent bind shutdown request …`), matching the existing `bound` / `confirmed bind shutdown` reply messages so both sides of the exchange are visible

## [0.7.0] - 2026-08-08

### Spec

#### Changed

- Renamed `InitiateForwarderClientReq` / `InitiateForwarderClientRep` to `InitiateTCPClientReq` / `InitiateTCPClientRep`; field `forwarder_client_id` renamed to `client_id` across all message types
- `InitiateTCPClientRep` now carries optional `remote_addr` and `remote_port` fields
- `REMOTE_PORT_FORWARDS` constant and `--remote-port-forwards` CLI flag removed — remote port forwards are now initiated server-side via BIND messages
- Clients must never call `exit()` or terminate the process; all errors are logged and handled gracefully
- Default scheme order changed from `["ws", "http", "wss", "https"]` to `["ws", "wss", "http", "https"]`
- `active_binds` dictionary replaced with `remote_port_forwarders` list; RPF stores its own `identifier` from the server-assigned `bind_id`

#### Added

- `InitiateBINDReq` (0x05) and `InitiateBINDRep` (0x06) message types for server-initiated remote port forwards
- `RemotePortForwarder.stop()`, `close_all_clients()`, and `identifier` field
- BINDRep shutdown signal: `0.0.0.0:0` with reason=0 confirms shutdown vs actual host:port for successful bind
- DNS resolution for RPF listening host
- 10-character alphanumeric identifiers (not GUIDs/UUIDs)
- Status messages with bracket prefix convention (`[+]`, `[*]`, `[!]`)

### Server

#### Changed

- Renamed `ForwarderClient` → `TcpClient`, `LocalForwarderClient` → `LocalTcpClient`, `RemoteForwarderClient` → `RemoteTcpClient`, `SocksForwarderClient` → `SocksTcpClient`
- Renamed `forwarder_clients.py` → `tcp_clients.py`
- Renamed `InitiateForwarderClientReq` / `InitiateForwarderClientRep` → `InitiateTCPClientReq` / `InitiateTCPClientRep`; field `forwarder_client_id` → `client_id`
- `RemotePortForwarder.parse_config` now expects 4-part format `listening_host:listening_port:destination_host:destination_port`
- `RemotePortForwarder.start()` sends `InitiateBINDReq` to the client instead of binding locally
- `RemotePortForwarder.stop()` sends `InitiateBINDReq` to tear down the client-side listener, RSTs all local TCP clients
- Debug labels renamed from `Forwarder Clients` to `TCP Clients`

#### Added

- `InitiateBINDReq` (0x05) and `InitiateBINDRep` (0x06) message types with full parse/build/serialize support
- `remote` command sends `InitiateBINDReq` to the client; `stop` sends a second to tear down
- `InitiateBINDRep` handler distinguishes bind success (`host:port`, reason=0), shutdown confirmation (`0.0.0.0:0`, reason=0), and failure (reason!=0)
- `logging` command updated to include types 5 (`InitiateBINDReq`) and 6 (`InitiateBINDRep`)
- `remote_addr` and `remote_port` fields in `InitiateTCPClientRep`

## [0.6.0] - 2026-08-06

#### Added
- `rename` command to assign friendly names to messengers, forwarders, and scanners.
  Names are displayed everywhere in place of the random identifier, with fallback
  to identifier when no name is set. Uniqueness enforced; only letters, numbers,
  hyphens, and underscores allowed.
- Messenger detail view via `messengers <id>` (supports multiple: `messengers dc01 dc02`).
  Shows transport, status, IPs, first seen, last seen (UTC), sent/received bytes,
  user-agent, and expanded forwarder/scanner listings with type and config.
- `first_seen` timestamp on messengers for the detail view.
- Tab completion resolves names for `interact`, `stop`, and direct-interact shortcuts.
- All `interact`, `stop`, `forwarders`, `scans`, and direct-interact shortcuts accept
  either identifier or name.

#### Changed
- Messenger table column renamed from "Identifier" to "Name".
- Forwarder table column renamed from "Identifier" to "Name".
- IPs column moved from verbose-only to always shown in messenger table.
- "Forwarders" column replaced with "Forwarders / Scanners" combining both; scanners
  shown in yellow.
- `messengers --verbose` removed; replaced by `messengers <id>` detail view.
- `scans --verbose` replaced with `scans --show-closed` to toggle closed/pending results.

## [0.5.0] - 2026-08-05

#### Added
- `logging` command to toggle which message types are recorded to disk.
  Logging is disabled by default. `logging 1,2,3,4` enables all types.
  `logging 0` disables all. `logging` with no args shows current status.
- Log commands and protocol messages to per-day JSONL files in `~/.messenger/logs/`.
- `messenger.conf` config file auto-created with all defaults on first run.
  Config values serve as argparse defaults; CLI args override.
- `--config` / `-c` CLI flag to set a custom messenger directory (default: `~/.messenger`).
- `--quiet` / `"quiet": true` suppresses banner and all startup messages.
- Reserved `-o`/`--output` flag for writing command output to files.
- Startup messages show created directories/files and always display
  messenger directory, config file, and logging directory paths.
- Passive bind address collector on messengers: new interface IPs discovered
  from `InitiateForwarderClientRep` bind addresses are added to the messenger's
  IP set and announced with a status message.
- Verbose messenger table column renamed from "External IP" to "IPs", showing
  all discovered addresses.

#### Changed
- Rewrite `debug` command to toggle output by type instead of threshold level.
  `debug 1,4` enables handler messages and handler data independently.
  `debug 0` disables all. `debug` with no args shows current status.
- Fix banner `SyntaxWarning` by using raw f-string.

## [0.4.5] - 2026-08-04

### Client

#### Fixed

**Node.js**
- Added no-op error handler after successful connect — post-connect TCP errors (`ECONNRESET`) crashed the process because `removeListener` left the socket with no error handler

**C#**
- Initialized HTTP client `_messengerId` to empty string — was `null`, causing `ArgumentNullException` on first connect
- Removed `SetRequestHeader("User-Agent")` from WebSocket client — restricted header on .NET Framework 4.7.2

#### Changed

**C#**
- Reduced HTTP poll interval from 1000ms to 100ms to match Python and Node.js clients
- Flattened builder template directory — output no longer nests `MessengerClient/MessengerClient/`

## [0.4.4] - 2026-08-01

### Client

#### Fixed

**Python**
- Fixed close signal ownership in `stream()` — bare `del` crashed with `KeyError` when server already removed the entry; replaced with `pop()` ownership guard that only sends the close signal if removal succeeded
- RPF accepted sockets are now paused until server approval — prevents data arriving before `InitiateForwarderClientRep` confirms the connection

**Node.js**
- Fixed `ReferenceError` crash in `RemotePortForwarder.start()` — the Promise constructor only had a `resolve` parameter, so `reject(e)` on bind failure was undefined
- Forward connect now maps OS errors to SOCKS5 reason codes (`ENETUNREACH`→3, `EHOSTUNREACH`/`ENOTFOUND`→4, `ECONNREFUSED`→5, `ETIMEDOUT`→6, `EAFNOSUPPORT`→8) — previously all errors returned reason 1
- Empty `--remote-port-forwards` (meaning "no RPFs") now correctly overrides hardcoded defaults — previously the `length > 0` check fell through to baked-in values

**C#**
- `Crypto.Hash` now uses `Encoding.UTF8` instead of `Encoding.ASCII` — non-ASCII encryption keys produced a different hash than Python and Node.js clients
- `DeserializeMessages` loop condition changed from `> 0` to `>= 8` — partial trailing headers (1–7 bytes) no longer throw an exception
- `CheckInMessage` now sends the existing messenger ID on reconnect instead of always sending an empty string — clients no longer lose their identity after every reconnection
- `InitiateForwarderClientRep` handler now checks for null forwarder client, validates reason code, and only starts streaming on approval — previously denied connections were streamed, and missing entries caused a crash
- Empty `--remote-port-forwards` now correctly overrides hardcoded defaults

#### Changed

**C#**
- Converted to SDK-style csproj with `Microsoft.NETFramework.ReferenceAssemblies` NuGet package — enables `dotnet build` on any platform without Visual Studio or Mono
- Removed `.sln` and `Properties/AssemblyInfo.cs` (auto-generated by SDK)
- All clients now support CLI argument parsing that overrides hardcoded builder values

#### Added

- `docs/client.pseudo` — golden standard pseudo-code client specification that all language implementations derive from

## [0.4.3] - 2026-08-01

### Client

#### Fixed

**All clients**
- Removed legacy `/socketio/` route prefix from connection URLs — Engine.IO framing was removed server-side in v0.4.1 and the suffix was vestigial
- Fixed race condition in `RemotePortForwarder` where `InitiateForwarderClientReq` was sent before registering the local socket in `ForwarderClients` — if the server replied before registration completed, `StreamAsync` would silently drop the tunnel
- Close signal echo prevention — when the server sends an empty `SendDataMessage` to tear down a tunnel, the client no longer echoes it back; dictionary removal is used as the ownership guard so only one side sends the close

**Python**
- Removed `.replace('ws', 'http')` scheme swap that worked around an aiohttp proxy bug — `wss://` proxying works natively since aiohttp 3.8 and the swap broke direct `ws://` connections
- `stream()` now closes the writer on exit — previously the local socket was left open after the remote side disconnected
- Replaced bare `socket.timeout` catch with `asyncio.TimeoutError` — the wrong exception type meant timeouts propagated as unhandled crashes
- Guarded `traceback.format_exc()` access to prevent `AttributeError` in exception handlers
- Fixed connection leak where a partial failure during forwarder setup left the socket open with no cleanup path
- Added `WSClient.close()` method — WebSocket client had no way to perform a graceful close handshake
- Added `await writer.drain()` after `writer.write()` for proper TCP backpressure

**Node.js**
- Fixed `e.stack` crash by adding optional chaining — stack traces on non-Error objects threw a secondary `TypeError`
- Fixed infinite drain loop in `SendMessagesAsync` — the sync loop spun without yielding when the WebSocket was in a closing state; added a `readyState === OPEN` guard
- Added try/catch around the WebSocket message handler so a single malformed frame doesn't kill the receive loop
- Fixed `message.type` → `message.kind` property access — every message was mis-routed because the wrong property name was read
- Added negative `payload_len` validation in the message parser to prevent underflow on malformed length headers
- Fixed post-connect error handler leak — the temporary `onError` handler was never removed after a successful connection, accumulating listeners across reconnects
- Created `http.Agent` once in the constructor instead of per-request — each poll cycle allocated a new agent, leaking sockets under load
- `RemotePortForwarder.start()` now rejects on bind error instead of resolving — callers had no way to detect that the listener failed to start
- Fixed implicit global `WebSocket = require('ws')` — missing `var` declaration leaked into global scope

**C#**
- `ConnectAsync` is now awaited in `TryHttp`/`TryWs` — the fire-and-forget `_ = ConnectAsync()` silently dropped all connection errors and started remote port forwards before the transport was established
- Fixed socket leak in `HandleInitiateForwarderClientReqAsync` — if `Socket.ConnectAsync` threw, the socket was never disposed; ownership now transfers to `TcpClient` on success, with a `finally` block disposing on failure
- WebSocket check-in now handles fragmented messages — the initial `ReceiveAsync` assumed the server's response fit in a single frame; a `do/while (!EndOfMessage)` loop accumulates fragments
- `CancellationTokenSource` is now cancelled and disposed before creating a new one on reconnect — previously each reconnection leaked the old CTS and its send loop continued running against a dead socket
- HTTP polling errors now throw back to `ConnectAsync`'s retry loop instead of breaking — a single failed poll permanently killed the HTTP client with no reconnection attempt
- `Crypto.Encrypt(ArraySegment<byte>)` now respects `Offset` and `Count` instead of encrypting the entire backing array — partial-buffer encryption produced corrupt ciphertext
- Added `messageLength < 8` guard in `MessageParser.DeserializeMessage` to prevent underflow when computing payload length
- Empty `SendDataMessage` (close signal) now properly closes and removes the `TcpClient` from `ForwarderClients`
- `SendDownstreamMessageAsync` no longer marked `async` — the method only enqueues to a `ConcurrentQueue` and the compiler warning masked real issues; dead catch block in HTTP variant also removed

#### Changed

**All clients**
- Retry logic now uses configurable `RETRY_DURATION` and `RETRY_ATTEMPTS` set at build time instead of hardcoded intervals

**Python**
- Builder prints a proxy warning when `--proxy` is set — aiohttp sends `ws://` in absolute-form instead of using CONNECT, which most HTTP proxies reject

**Node.js**
- Added `--electron` builder flag for proxy-aware Electron builds that use native `fetch` and `WebSocket` instead of the `ws` and `http` npm packages

**C#**
- `USER_AGENT` is now set on `HttpClient.DefaultRequestHeaders` and `ClientWebSocket.Options` — previously defined as a constant but never sent in any request

#### Added

**C#**
- `builder.py` with Jinja2 template rendering matching the Python and Node.js builder pattern — `messenger-builder csharp` auto-discovers the new builder with `--server-url`, `--encryption-key`, `--user-agent`, `--proxy`, `--remote-port-forwards`, and retry options
- Source files converted to Jinja2 templates under `templates/MessengerClient/`; builder outputs a complete .NET Framework 4.7.2 project directory ready for `msbuild`
- README rewritten to match the Python and Node.js client documentation format — Overview, Primary Capabilities, Client-Specific Capabilities, Quick Start with compilation steps, Usage, and Client Options with detailed subsections

**Node.js**
- README updated to document `--electron` and `--messenger-id` builder options, add Client-Specific Capabilities section, and correct HTTP transport support

#### Fixed

**All clients**
- README Quick Start examples no longer reference the removed `/socketio/?EIO=4&transport=` route
- README Client Options tables now show `localhost:8080` as the default server URL, matching the actual builder default

**Node.js**
- README no longer says "Python Messenger Client" in the Usage section
- README `--name` default and example corrected from `.py` to `.js`

### Server

#### Fixed

- Client Support Matrix: C# row linked to `messenger-client-python` instead of `messenger-client-csharp`
- Client Support Matrix: C# and Node.js builders now marked as Supported
- Client Support Matrix: Node.js protocols updated from WebSockets to HTTP & WebSockets

## [0.4.2] - 2026-07-31

### Client

#### Fixed

**Python**
- Fixed identifier generator so digits 0–9 are included in random identifiers — `alphanumeric_identifier` was indexing with `len(alphabet)` instead of `len(alphanumeric)`
- Streamers are now killed when the client receives an empty `SendDataMessage` — previously a server-initiated close left the local socket and its read loop running

#### Changed

**Python**
- Removed old standalone client files; template is the single source of truth

### Server

#### Fixed

- Forwarder client writers are now properly cleaned up on all close paths — `send_data(b'')`, failed SOCKS negotiation, denied connection replies, and `LocalForwarderClient.initiate_forwarder_client` exceptions all route through `_cleanup()`
- `RemotePortForwarder` now has a `stop()` method — previously stopping a remote forwarder only removed it from the list, leaking open connections and stream tasks
- Manager `stop` dispatcher now calls `stop()` on all forwarder types, not just `LocalPortForwarder`
- Connection-denied handling moved into forwarder clients — `SocksForwarderClient` now sends the proper SOCKS5 error reply before closing instead of aborting the transport with no reply
- `alphanumeric_identifier` now correctly indexes the full alphanumeric list — digits 0–9 were never selected due to using `len(alphabet)` instead of `len(alphanumeric)`
- `_parse_port_ranges` validates input instead of crashing on malformed entries like `80-http` or `1-2-3`
- `_parse_ip_ranges` rewritten to handle hyphenated hostnames using `rpartition`
- `interact` no longer prints a false "Could not find Messenger" error on a successful match
- Scanner `handle_initiate_forwarder_client_rep` only releases the semaphore and updates results for its own scan identifiers, not every reply
- Scanner now sends a close signal for successful scan connections so remote forwarder clients get cleaned up
- Scanner `stop()` now sets `end_time` so runtime doesn't count indefinitely
- Reconnect detection in `messengers.py` now fires correctly — `last_check_in` is checked before being updated
- SOCKS negotiation uses `readexactly` instead of `read` to prevent partial reads on slow or fragmented connections
- `writer.write()` calls are now followed by `await writer.drain()` for proper backpressure
- WebSocket handler validates the first received message is `BINARY` before accessing `msg.data`, preventing crashes on CLOSE/ERROR frames
- WebSocket reconnection rejects messengers that aren't `WebSocketMessenger` instead of crashing with `AttributeError`
- `SocksProxy.handle_client` appends the client before calling `initiate_forwarder_client` so failed negotiations still get cleaned up
- SOCKS reply write is wrapped in try/except to handle clients that disconnect during the handshake
- Encryption key generation now uses the `secrets` module instead of `random`
- `LocalPortForwarder.stop()` no longer crashes when `start()` failed and `self.server` is `None`
- `WebSocketMessenger.send_message_upstream` catches `send_bytes` failures and falls back to queuing the message
- Bind error handling now uses `errno.EADDRINUSE` and `errno.EADDRNOTAVAIL` instead of hardcoded Linux values 98/99
- Redundant `request.read()` in `redirect_handler` removed — body was read for debug logging then re-read in `http_post_handler`
- Engine, forwarder clients, and WebSocket server wrap critical paths in try/except so a single malformed message doesn't kill the session
- Malformed or undecryptable message frames now stop parsing instead of propagating an exception
- `get_messenger_id` returns `None` instead of asserting on non-CheckIn messages
- HTTP and WebSocket handlers guard against empty or unidentifiable check-ins instead of crashing
- Fixed `MANIFEST.in` typo

#### Changed

- `_cleanup()` accepts an `abort` parameter for forced teardown vs graceful close
- `scanner.handle_initiate_forwarder_client_rep` is now async
- Cleaned up redundant `__init__` assignments in `Scanner`

## [0.4.1] - 2026-07-26

### Server

#### Fixed

- HTTP and WebSocket transports no longer require the `/socketio/` route prefix — clients can connect directly to `/?EIO=4&transport=…`

## [0.4.0] - 2026-07-26

### Client

#### Added

**Python**
- `builder.py` — Jinja2 template renderer with `--server-url`, `--encryption-key`, `--user-agent`, `--proxy`, `--remote-port-forwards`, and retry options; output is a single `.py` file
- Default User-Agent header (Firefox 128 on macOS) embedded at build time
- Reconnection status message printed when re-establishing a dropped connection
- Dependency check for `aiohttp` with a clear error message if missing

#### Fixed

**Python**
- Fixed `candidateURL` not being accessible after initial connection attempt — transport fallback failed silently on the second scheme
- Fixed client selection logic — transports containing `http` or `ws` in the scheme were matched ambiguously
- Changed transport attempt order and added explicit "no suitable clients identified" fallback

#### Changed

**Python**
- Removed hardcoded obfuscation; obfuscation is now opt-in via the builder
- Server URL defaults to `localhost:8080` when not specified
- Restructured client as a Jinja2 template under `templates/` — builder renders configuration into the output file

**Node.js**
- Initial Node.js client with WebSocket and HTTP transports, AES-CBC encryption, remote port forwards, and automatic WS/HTTP fallback
- `builder.py` with the same option set as Python plus Webpack configuration
- HTTP polling uses `http`/`https` modules instead of `fetch` for broader Node.js compatibility
- Reconnection logic for both WebSocket and HTTP transports with configurable retry
- Electron support via `--electron` builder flag (basic Electron wrapper with `main.js` and `renderer.html`)
- Self-signed certificate acceptance for development and internal deployments

**C#**
- Added WebSocket reconnection procedure with configurable retry — previously the client exited on first disconnect

### Server

#### Added

- New standalone `messenger-builder` executable with per-language subcommands (auto-discovered from `builder/clients/*/builder.py`) and an `update-clients` subcommand that runs `git submodule sync/update/foreach`
- `builder/` package for build tooling; `builder.clients.*` submodules for Python, C#, and Node.js clients
- `pycryptodome` and `jinja2` added to `requirements.txt` / `setup.py` `install_requires`
- `MAINFEST.in` to package `builder/clients` resources
- New docs: `docs/communication.md` (rewritten protocol spec), `docs/chaining-messengers.md`, `docs/local-port-forwards-and-socks.md`, `docs/remote-port-forwards.md`, `docs/testing.md`
- `messenger/text.py` module exposing shared `color_text` / `bold_text` helpers
- Status message when `interact` cannot find a matching messenger ID
- Handler-level debug messages moved to the generic `redirect_handler` so both HTTP and WS transports emit them

#### Changed

- `messenger/aes.py` replaced its ~260-line pure-Python AES implementation with a thin wrapper around `pycryptodome`'s `Crypto.Cipher.AES`
- Client submodules moved from `messenger/clients/` to `builder/clients/` (paths updated in `.gitmodules`)
- `build` command removed from the interactive CLI; client building is now handled exclusively by `messenger-builder`
- `setup.py` now installs both `messenger-cli` and `messenger-builder` scripts and packages `builder/**` client resources
- HTTP `web.Application` no longer sets `client_max_size=2GB`; aiohttp's default cap now applies
- `LocalPortForwarder.handle_client` now closes the writer when the remote replies with a non-zero reason (previously silently dropped in the client)
- `LocalForwarderClient` and `SocksForwarderClient` no longer check `rep != 0` themselves — the parent forwarder handles denial and always starts the stream on success
- `SocksForwarderClient` renamed its constructor arg `cleanup` to `on_close` to match siblings
- `LocalForwarderClient.send_data` now calls `writer.close()` on EOF instead of `writer.write_eof()`
- `receive_data()` on forwarder clients renamed to `stream()`
- `messengers.py`: various status-message tweaks and copy edits
- README rewritten with new hyperlinks and doc layout
- `docs/getting-started.md` and `docs/communications.md` removed; content moved to the new docs
- `docs/operational-usage.md` renamed to `docs/ntlmrelay2self-with-messenger.md`

#### Fixed

- Remote port forward start message printed the forwarder identifier instead of the owning messenger identifier
- Remote-forwarder denials now send an `InitiateForwarderClientRep` back to the client instead of silently dropping
- Local port forwarder bug where denied client connections leaked; writer is now closed and awaited
- `set_websocket` was returning/using an empty list of queued messages on reconnect
- Duplicate ports in the port list (top-ports resource dedup)
- Typo fix: `Captured unexpect error` → `Captured unexpected error`
- Assorted README typos and hyperlinks

#### Removed

- Interactive `build` command from `messenger-cli` (superseded by `messenger-builder`)
- `messenger/clients/` package (moved to `builder/clients/`)
- `UpdateCLI.color_text` and `UpdateCLI.bold_text` static methods (relocated to `messenger/text.py`)
- Pure-Python AES fallback in `messenger/aes.py`

## [0.3.6] - 2025-10-21

### Server

#### Fixed

- WebSocket reconnection used a nonexistent `update_cli.messages` attribute and never actually flushed queued messages; `set_websocket` now drains via `get_upstream_messages()` and sends the properly serialized batch

#### Changed

- HTTP messenger status is now rendered as `Xms delay` / `Xs delay` / `Xm delay` / `Xh delay` instead of `Last Seen X seconds/minutes/hours ago`
- WebSocket messenger status lowercased to `connected` / `disconnected`
- Removed the HTTP messenger's `expiration()` background task (disconnection/reconnection is now inferred purely from `last_check_in` in the status property)

## [0.3.5] - 2025-10-21

### Server

#### Added

- Unhandled exceptions in the CLI loop are now appended to `~/.messenger/exceptions.log` with a timestamp and traceback
- When `debug_level != 0`, the full traceback is also printed to the console
- CLI directs the user to file a GitHub issue on unexpected errors
- New `messenger/forwarder_clients.py` module — forwarder-client classes (`ForwarderClient`, `LocalForwarderClient`, `RemoteForwarderClient`, `SocksForwarderClient`) split out of `forwarders.py`
- Server queues upstream messages for a messenger even when it is not marked alive (removed the `if not messenger.alive` guard in `local` and other command paths)

#### Changed

- Large refactor of `messenger/forwarders.py` (~300 lines removed) around the new `forwarder_clients` split
- Messenger table column renamed from `Alive` (Yes/No) to `Status` (uses each messenger's `status` property)
- Various messenger status-message copy tweaks

## [0.3.4] - 2025-08-08

### Server

#### Fixed

- `execute_command` counted required parameters wrong when a flag was passed before positional arguments — positional args were being counted as keyword args; now consumed flags are excluded from the required-param count

## [0.3.3] - 2025-08-08

### Server

#### Fixed

- `RemoteForwarderClient.initiate_forwarder_client` never scheduled `receive_data()`, so remote port forwards accepted connections but never streamed data

## [0.3.2] - 2025-08-08

### Client

#### Changed

**Python**
- Builder variable names cleaned up; attribute obfuscation removed from the default build
- Updated client to use the existing messenger identifier on reconnection instead of requesting a new one — reconnections are now seamless from the server's perspective
- Retry attempt and duration parameters exposed in builder; client calls updated to use them
- Added handling for non-zero `InitiateForwarderClientRep` — connection denials from the server now produce a meaningful error instead of silently hanging
- Invalid server responses caught instead of crashing

**C#**
- Submodule pointer bumped (async fixes, queue-based message batching, scan support)

### Server

#### Added

- `--update-submodules` flag on `messenger-cli` that runs `git submodule sync/update/foreach` before starting the CLI
- `include_package_data=True` and `package_data={'messenger': ['resources/*']}` in `setup.py` so `top_ports.txt` ships with `pip`/`pipx` installs
- `build python` now degrades gracefully when the Python client submodule is not present, pointing the user at `--update-submodules`

#### Changed

- Scanner listing/detail branches swapped — `scans` (no identifier) now shows the summary table, `scans <identifier>` shows per-port results; closed and pending results hidden unless `--verbose`
- Help/example text for `local`, `remote`, and `socks` clarified
- Node.js client hyperlink added to the README

#### Fixed

- `top-ports` resource was not accessible after install because `package_data` was not configured

## [0.3.1] - 2025-08-01

### Server

#### Fixed

- Race condition where a `LocalForwarderClient` could try to write data upstream before the remote peer had confirmed the connection

## [0.3.0] - 2025-08-01

### Client

#### Added

**Python**
- Reconnection procedure — client automatically reconnects on transport failure with configurable timeout
- Outbound HTTP/HTTPS proxy support (`--proxy` flag in the builder)
- Error message when `aiohttp` is not installed
- Status update messages printed on reconnection

**C#**
- HTTP transport support alongside the existing WebSocket transport
- Automatic WS/HTTP failover — client tries one transport and falls back to the other on failure
- AES-CBC encryption matching the Python client's protocol
- Outbound proxy support
- Async message queuing with downstream message batching
- Migrated from .NET Core to .NET Framework 4.7.2 for broader Windows compatibility
- Static compilation via dnMerge for single-binary deployment

#### Fixed

**Python**
- Fixed `atype == 0` return in SOCKS5 handling — zero address type caused the server to reject the connection
- Fixed performance issues caused by synchronous waits in the async event loop
- Fixed async function not being awaited in the message handler
- Fixed relative path resolution for the builder template

**C#**
- Fixed async patterns across the client — `await` calls were missing on several code paths, causing fire-and-forget behavior
- Fixed message queuing — downstream messages are now batched in a `ConcurrentQueue` instead of sent individually

### Server

#### Added

- `portscan` command (in-CLI TCP port scanner) with a new `messenger/scanner.py` module, `--concurrency` control, and configurable worker count
- `scans` command listing active/completed scanners with progress tracking (`Runtime`, `Attempts`, `Progress`, `Open`, `Closed`)
- `stop` command extended to also stop in-progress scanners in addition to forwarders
- `debug` command with numeric debug levels (0–6): handler messages, messenger messages, forwarder-client messages, and raw data at each layer
- `build` command in the CLI (`build python` initially wired up via `messenger.clients.python.builder`); C# and Node.js accepted as arguments but marked "not implemented"
- Flag/keyword-argument support in `execute_command` — commands can now be invoked with `--name value` / `--flag` in addition to positional args
- `messenger/scanner.py`, `messenger/resources/top_ports.txt` (8344 ports), `docs/getting-started.md`, `docs/operational-usage.md`
- Git submodules for bundled clients: `messenger/clients/python` and `messenger/clients/csharp`

#### Changed

- Renamed the `messenger-server` entry-point script to `messenger-cli`; `messenger-client` script removed
- `setup.py` now ships only `messenger-cli` (client is a submodule now)
- Reworked reconnection procedure for messengers
- Various status-message / help-menu / error-message rewording across the manager
- WebSocket handler in `http_ws_server.py` updated for how it processes new messengers
- Detailed scan results table with runtime/attempts/progress columns

#### Fixed

- Scanner was iterating dict keys instead of values
- Scanner workers were pegging the CPU
- Invalid concurrency numbers now produce a clear error instead of crashing

## [0.2.5] - 2025-04-10

### Server

#### Fixed

- Messengers could not reconnect — when `get_upstream_messages()` was called on a messenger with `alive == False`, `alive` is now flipped to True and a "reconnected" status is emitted

#### Changed

- Default server bind address changed from `127.0.0.1` to `0.0.0.0`, default port from `1337` to `8080`
- Added short-form flags (`-a`, `-p`, `-s`, `-e`) to `messenger-server` arguments
- Status message rewording: identifiers now wrapped in backticks; "is now available" → "is now connected"

## [0.2.4] - 2025-03-23

### Client

#### Changed

**Python**
- Client rewritten around the new `Engine` module — shared message handling logic between client and server
- Added graceful shutdown handling
- Additional error handling for non-URL server inputs and transport failures

**C#**
- Client updated for v0.2.4 protocol (Engine-based message handling)

### Server

#### Added

- New `messenger/engine.py` module abstracting shared client/server message handling; both client and server rewritten around it
- New `messenger/http_ws_server.py` splitting the HTTP+WebSocket transport out of `server.py`
- `interact` command — select a target messenger once, then run per-messenger commands without re-specifying the ID; `back` to return
- Verbose flag (`--verbose`) on listing commands with proxy support in the client
- `--encryption-key` CLI flag on the server
- Sent/received byte counters on messengers, formatted in the messengers table
- Bold-text helper (`UpdateCLI.bold_text`) — encryption key is bolded in banner output
- "No messengers/forwarders to display" status messages for empty tables

#### Changed

- `messenger/server.py` deleted; transport code now lives in `http_ws_server.py`
- `messenger-client` and `messenger-server` scripts substantially rewritten to use the new engine
- Increased max request size for HTTP and WebSocket messengers (`client_max_size` bumped to 2GB)
- Reordered `External IP` and `User-Agent` columns in verbose messenger output
- Help menu descriptions rewritten across commands

#### Fixed

- WebSocket messengers were never being marked dead — now correctly transition when the socket closes
- Sent/received byte counts were off; expanded floating-point precision and corrected byte formatting
- Format-string compatibility for older Python versions
- "No messengers connected" message printed even when messengers were present
- Attempts logic in the messenger client

## [0.2.3] - 2024-11-11

### Client

#### Added

**Python**
- Outbound proxy support — HTTP(S) proxy can be specified and is applied to both HTTP and WebSocket transports

### Server

#### Added

- AES-CBC encryption for HTTP and WebSocket transports — new `messenger/aes.py` (pure-Python AES fallback with optional `pycryptodome` fast path) and `messenger/generator.py` (encryption key generation and key hashing)
- Reconnection ability for HTTP messengers (server-side identifier reuse)

#### Changed

- Messenger identifier scheme reworked (uses short hashed IDs instead of full UUIDs)
- README substantially expanded

## [0.2.2] - 2024-11-10

### Server

#### Added

- ANSI terminal colors in CLI output (`UpdateCLI.color_text`, colored status icons)

#### Changed

- Renamed "Local Forwarders" to "Local Port Forwarders" (nomenclature update in commands and messages)
- Command docstrings expanded/clarified across the manager
- Formatting and unused-import cleanup across `manager.py`, `forwarders.py`, `messengers.py`

#### Fixed

- Sending to a messenger that was no longer alive now short-circuits
- Sending data from forwarder clients that no longer exist now short-circuits

## [0.2.1] - 2024-11-06

### Client

#### Fixed

**Python**
- `WebSocketClient` was not starting due to a missing call in the client script

### Server

#### Changed

- Dependencies updated in both `requirements.txt` and `setup.py`

## [0.2.0] - 2024-11-06

### Client

#### Added

**Python**
- Remote port forward support — client-side `RemoteForwarder` with TCP listener and data streaming
- Custom User-Agent header (Firefox 128 on macOS) to blend with normal browser traffic
- Structured message protocol support (`MessageBuilder` / `MessageParser`) matching the new server wire format

**C#**
- Initial C# client with WebSocket transport and SOCKS5 tunneling
- Downstream message queue for batched sends

### Server

#### Added

- Remote port forwards — new `RemoteForwarder` class in `forwarders.py`
- Local port forwards (`LocalForwarderClient`, `ForwarderClient` base class) reworked from the earlier SOCKS-only model
- `Manager` class (`messenger/manager.py`) replacing `MessengerCLI`, with a command dispatch table (`exit`, `forwarders`, `messengers`, `local`, `remote`, `stop`, `help`) and prompt-toolkit-based interactive prompt with tab completion
- Structured message protocol: new `messenger/message.py` (`MessageBuilder` / `MessageParser`) with typed message frames (Initiate Forwarder Client Req/Rep, Send Data, Check In)
- `messenger/messengers.py` with `HTTPMessenger` / `WebSocketMessenger` abstractions
- `docs/communications.md` documenting the wire protocol
- Server strips the `Server` HTTP response header to reduce fingerprinting

#### Changed

- Communications specification rewritten around length-prefixed typed messages
- `messenger/cli.py` deleted; replaced by `messenger/manager.py`
- `messenger/socks.py` deleted; SOCKS behavior moved into `forwarders.py`
- `messenger-server` script now instantiates `Manager` instead of `MessengerServer` + `MessengerCLI`
- Removed the `--buffer_size` argument on `messenger-server`
- README extensively updated

## [0.1.2] - 2024-05-23

### Server

#### Added

- `-q` / `--quiet` flag on `messenger-server` to suppress the banner
- SOCKS5 version check — a friendly "SOCKSN is not supported" message is emitted for non-v5 clients
- Server response strips the `Server` header via `on_response_prepare` (reduced fingerprinting)

#### Changed

- `setup.py`: dropped `console_scripts`; now installs `messenger-server` and `messenger-client` as top-level scripts
- `messenger/__init__.py` slimmed down to just `__version__` and `BANNER`
- `examples/client.py` promoted to top-level `messenger-client` script

#### Fixed

- README typos and inaccuracies

## [0.1.1] - 2024-05-22

### Server

#### Changed

- `MessengerCLI` now checks `socks_server.is_stopped()` instead of the `socks_server.socks_server` attribute
- `MessengerCLI` dropped unused `atexit` / `os` / `readline` imports
- README installation section added (pipx quick-start)

## [0.1.0] - 2024-05-19

Initial tagged release.

### Client

#### Added

**Python**
- Example client (`examples/client.py`) with WebSocket and HTTP transports served over `/socketio/?EIO=4&transport=…`
- Automatic fallback from WebSocket to HTTP when WS fails

### Server

#### Added

- Client–server SOCKS5 tunneling framework (Python) with both WebSocket and HTTP transports served by a single `aiohttp` app
- `MessengerServer` (`messenger/server.py`) with dynamic per-transport `SocksServer` instances and configurable SOCKS5 port range
- SOCKS5 negotiator (`messenger/socks.py`) — auth negotiation, CONNECT request handling, address-type support, streaming to/from remote hosts
- Interactive CLI (`messenger/cli.py`) with `socks` and `exit` commands and a formatted `SOCKS SERVERS` table
- `argparse` entry point exposing `--address`, `--port`, `--ssl CERT KEY`, `--buffer_size`
- Banner, verbose logging via `messenger/output.py`, JSON deserialization helper (`messenger/convert.py`)
- Client and SOCKS-server cleanup on disconnect; auto-stop of the SOCKS server when the WS connection closes
- BSD-3-Clause `LICENSE`, `README.md`, `requirements.txt`, `setup.py`

#### Fixed

- Closed ports no longer prevent further clients from being processed
- `is_stopped` returned the wrong result on the `SocksServer`
- HTTP client was sending too much data at a time
- Non-URL server URLs handled via `urllib.parse.urlparse`
- Older-Python compatibility: tuple subscript syntax removed
