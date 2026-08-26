---
name: grade-clients
description: >-
  Grade C#, Node.js, and Python client implementations against the golden
  standard spec in docs/client.pseudo. Reads every section of the spec, builds
  a rubric, then reads each client and scores it. Use when the user asks to
  "grade clients", "check clients against the spec", "audit client compliance",
  or any variation of comparing client implementations to the spec.
---

# Client Grading Skill

Grade every Messenger client implementation against `docs/client.pseudo`.

## Inputs

The user may optionally specify:
- A single client to grade (`csharp`, `nodejs`, `python`) â€” default is all three.
- A single section to focus on â€” default is all sections.

## Workflow

### 1. Read the spec

Read `docs/client.pseudo` in full. This is the golden standard â€” every
requirement in it is a grading criterion. Do not invent requirements that
aren't in the spec and do not skip requirements that are.

### 2. Build the rubric

Walk the spec section by section and extract every testable requirement.
Use the section structure below. Each requirement becomes a pass/fail check.

### 3. Read the clients

For each client being graded, read the relevant source files:

- **C#**: `builder/clients/csharp/templates/` â€” `Program.cs`, `MessengerClient.cs`,
  `HTTPMessengerClient.cs`, `WebSocketMessengerClient.cs`, `Message.cs`,
  `RemotePortForwarder.cs`, `Crypto.cs`
- **Node.js**: `builder/clients/nodejs/templates/messenger-client.js`
- **Python**: `builder/clients/python/templates/messenger-client.py`

Also read the builder for each client to check build-time configuration:

- **C#**: `builder/clients/csharp/builder.py`
- **Node.js**: `builder/clients/nodejs/builder.py`
- **Python**: `builder/clients/python/builder.py`

### 4. Grade

For each requirement, check whether the client implements it correctly.
Score as:

- **PASS** â€” implements the requirement correctly
- **FAIL** â€” missing or incorrect implementation
- **N/A** â€” requirement does not apply to this client's platform (e.g.,
  User-Agent on C# WebSocket with net472)

When grading, keep these platform-specific facts in mind:
- C# `TcpClient` is pull-based â€” it does NOT need socket pause/resume. The
  system buffer queues incoming data until `ReadAsync` is called. This is
  correct behavior, not a missing feature.
- C# `ClientWebSocket` on .NET Framework 4.7.2 (net472) cannot set the
  `User-Agent` header â€” it is a restricted header. This is an N/A, not a FAIL.
- Node.js sockets are push-based and MUST be paused on accept and resumed
  on approval.
- Python asyncio sockets are push-based and MUST be paused on accept and
  resumed on approval.

#### Required language-semantics pass

Before marking any concurrency, cleanup, task-lifetime, or socket-lifecycle
row, analyze the implementation in the semantics of that language and runtime.
Do not translate the pseudo client into identical syntax and assume identical
hazards.

For every potentially concurrent operation:

1. Identify the shared state and the operation that is supposed to protect it.
2. Identify the exact interleaving boundary: another OS/thread-pool thread in
   C#, or an `await`, callback, event, or timer turn in Node.js/Python.
3. Trace setup, steady-state, error, peer-close, local-close, replacement, and
   checkout paths.
4. Check the runtime's real collection, task, stream, listener, and socket-close
   contracts. Do not infer them from another language's API names.
5. Mark PASS when the implementation guarantees the spec's invariant by a
   platform-equivalent mechanism, even if a redundant pseudo step is absent.
   Preserve the requirement row, but do not fail code merely for omitting a
   guard where that runtime cannot interleave.

Use this baseline:

| Concern | C# / .NET Framework 4.7.2 | Node.js | Python asyncio |
| --- | --- | --- | --- |
| Execution | Tasks may run simultaneously on multiple threads. Treat shared mutable state as genuinely concurrent. | JavaScript runs to completion on one event-loop thread. Interleaving occurs at callbacks, events, timers, and `await`, not between adjacent synchronous statements. | One event-loop task runs at a time. Interleaving occurs when a coroutine awaits or otherwise yields, not between adjacent synchronous statements. |
| `killed` / membership rechecks | Keep entry checks and rechecks after awaits; another thread may also interleave between adjacent operations, so post-publication validation can be necessary. | Recheck after a callback or `await`. An immediate second check after a synchronous `Map.set()` or synchronous registration is redundant unless user code can run there. | Recheck after `await`. An immediate second check after synchronous dictionary assignment or registration is redundant. A task created with `create_task()` may start later, so its entry check remains useful. |
| Shared maps | Use `ConcurrentDictionary` or locking and identity-safe conditional operations. A check followed by a separate mutation is not atomic. | `Map` operations inside one synchronous turn need no lock. Still use identity comparison when delayed callbacks may remove a replacement entry. | Dictionary operations inside one no-`await` section need no lock. Still use identity comparison when a later coroutine continuation may remove a replacement entry. |
| Iteration | Snapshot mutable collections when another thread can modify them or the loop awaits. | Synchronous `Map` iteration and deletion follow Node/ECMAScript iteration rules; snapshot only when the loop crosses an async boundary or its mutation pattern requires stable membership. | Do not mutate a dictionary while directly iterating it. Use `list(...)`/a snapshot; also snapshot any loop that awaits when stable membership is required. |
| Detached work | No global task registry is required solely to make resource-owning tasks self-clean, but all shared cleanup must remain thread-safe. | Promises are strongly retained by their dependency chain; no registry is needed solely for lifetime. Handle rejection according to the client's process-error policy. | The event loop holds weak references to tasks. Keep a strong-reference set for fire-and-forget tasks and discard each task when done. This is lifetime retention, not a requirement to cancel or await all tasks during close. |

Use precise terminology in the report:

- **Data race / thread race** for simultaneous C# access without adequate
  synchronization.
- **Lifecycle race / interleaving race** for Node.js or Python state becoming
  stale across an async yield.
- **Synchronous run-to-completion section** for Node.js/Python code that cannot
  be interleaved. Do not call it lock-free atomicity unless explaining this
  narrower event-loop meaning.

#### Network and lifetime API checks

Explicitly verify these language-specific behaviors when the related spec rows
exist:

- An empty `SendDataMessage` represents TCP RST. A graceful close is not an
  equivalent implementation. For current runtimes, check for C# abortive close
  (for example zero linger), Node.js `socket.resetAndDestroy()` where supported,
  and Python transport `abort()` rather than `StreamWriter.close()`.
- Closing a listener is not assumed to close its accepted connections. In
  particular, Node.js `server.close()` stops accepting but waits for existing
  connections; cleanup must not depend on the resulting `close` event to close
  those same connections.
- Python `transport.write()` is ordered and buffered, so a second application
  writer queue is not automatically required for serialization. Separately
  assess bounded buffering/backpressure and cleanup after transport failure.
- C# `NetworkStream` still needs one serialized application writer. Do not claim
  the OS makes concurrent `Write` calls safe. Also flag a permanently blocking
  `BlockingCollection.GetConsumingEnumerable()`/`Take()` worker per connection
  as a scalability concern on .NET Framework 4.7.2, even if ordering is correct.
- A resource-owning request task may self-clean on startup failure or stream
  death. Do not require a global shutdown task registry unless the spec requires
  waiting/cancellation; do require every exit path to release its socket,
  listener, and current identity-safe map entry.

Perform the stop audit as four distinct cases; do not collapse them into one
"cleanup" result:

1. **Protocol checkout:** tracked listeners and TCP connections close
   immediately. Slow request tasks may finish their current DNS/connect/bind
   wait, but they must recheck shutdown, close temporary resources, and never
   publish afterward.
2. **Per-bind STOP:** closing one forwarder must also close its accepted
   connections. Reject designs where listener cleanup waits for connections
   that only that same cleanup would close.
3. **Transport reconnect:** identifier, TCP connections, forwarders, and queued
   messages intentionally survive; transport-only tasks and objects do not.
4. **Terminal return:** retry-disabled, retry-exhausted, fatal-decryption, host
   shutdown, and checkout exits must not leave live handles that prevent process
   exit or leak when the client runs in a host process. Distinguish deterministic
   cleanup from "the OS will reclaim it when this standalone process exits."

If terminal-return cleanup is not a testable requirement in the pseudo spec,
report a concrete problem as an unscored operational observation rather than
silently adding it to the compliance denominator.

#### Compliance versus operational impact

Keep the requirement matrix row-based, but analyze findings by root cause:

- A row is FAIL only when the implementation can violate the requirement's
  observable invariant. An omitted guard that is provably redundant under the
  runtime's scheduling semantics is PASS.
- An explicit non-behavioral requirement such as exact status text can still be
  FAIL, but label it **spec-only** and low severity when it has no operational
  effect.
- Do not present an inert deviation as a behavioral bug. For example, failing
  to clear a local variable that is never read again is at most a low/spec-only
  deviation.
- Multiple failed rows caused by one missing primitive remain separate matrix
  rows and findings, but identify the shared root cause in each finding. Count
  it once in the card's severity totals rather than describing derivative rows
  as independent high-severity bugs.
- Inspect the paired server before assigning high severity to duplicate-ID,
  replay, retry, or ordering defenses. Record whether IDs are random or
  peer-controlled, whether downstream messages are retried, and whether the
  transport preserves order. Low probability does not make a required defense
  unnecessary, but it changes operational severity.
- Do not treat arbitrary local TCP read chunk sizes as protocol failures when
  framing accepts any valid chunk size and no peer maximum exists.

### 5. Report â€” HTML Artifact

Write the results to an HTML file and publish it with the Artifact tool.
Do NOT load the `artifact-design` skill â€” use the reference template
at `docs/skills/grade-clients/report-template.html` instead. Read
that file and copy its exact `<style>` block and HTML structure. Only
change the data (grades, requirements, pass/fail results, notes, file
references). Do not redesign, restyle, add JavaScript, add animations,
add ring charts, or add accordions.

**Rules:**
- Copy the CSS verbatim from the template. Do not modify colors, fonts,
  spacing, or class names.
- Keep every section visible on load â€” no accordions, no `display:none`,
  no JavaScript toggling.
- Every requirement gets its own `<tr>`. Do not roll up or summarize.
- Fail cells contain ONLY an `<a class="v-fail" href="#f-{lang}-{slug}">Fail</a>`
  linking to the corresponding finding at the bottom. The containing cell gets
  `id="r-{lang}-{slug}"` so the finding can link back to that exact matrix cell.
  No inline code, no file references, no `<div class="fail-detail">` â€” just
  the hyperlinked pill. All detail lives in the finding.
- Pass cells use `<span class="v-pass">Pass</span>`.
- When a row passes specifically because the runtime provides an equivalent
  guarantee while omitting a literal pseudo step, make that visible as
  `<td id="r-{lang}-{slug}"><a class="v-pass v-lang-pass" href="#p-{lang}-{slug}">Pass*</a></td>`.
  Add a corresponding language-pass note using the structure below. Do not use
  `Pass*` merely because an ordinary implementation happens to use a familiar
  language API; reserve it for conclusions that would differ under another
  language's scheduling or runtime semantics.
- N/A cells use `<span class="v-na">N/A</span>`.
- Each card gets a class for its language: `class="card cs"`, `card js`,
  `card py`. The grade color is driven by the per-client accent.

**Layout (matches template exactly):**
1. **Header** â€” `.eyebrow` ("Spec Compliance Audit"), `<h1>` title,
   `.subtitle` with two `.pill` spans for spec file and branch.
2. **Grade cards** â€” `.cards` grid, three `.card.{cs|js|py}` divs. Each
   has: `.card-lang`, `.card-name`, `.card-grade` (letter, colored by
   accent), `.card-pct` (pass/total Â· pct%), `.card-note` (1â€“2 sentences),
   `.severity-dots` with `.dot.high`, `.dot.med`, `.dot.low` + counts.
3. **Requirement tables** â€” `.tables-heading` h2, then for each section:
   `.section-label` div ("01 &ensp; Section Name"), then `<table>` inside
   `.table-wrap`. Columns: Requirement (46%), C# (18%), Node.js (18%),
   Python (18%).
4. **Findings** â€” `.findings-heading` h2 ("Findings"), then `.finding`
   divs. Each finding has `id="f-{lang}-{slug}"` matching the `href` in
   the table's Fail link. Structure:
   `<div class="finding" id="f-py-retry-float">`
     `<span class="f-client py">Python</span>`
     `<span class="f-text">Full sentence describing the failure.</span>`
     `<a class="f-back" href="#r-py-retry-float">Back to matrix</a>`
   `</div>`
   The `.f-client` span uses class `cs`, `js`, or `py` for per-client
   accent color. The `.f-text` is a complete sentence that includes the
   file:line reference inline and clearly describes what is wrong and why.
   When the user clicks a Fail link, the browser scrolls to the finding
   and `:target` CSS highlights it with a red left border and background.
   The finding's **Back to matrix** link returns to and highlights the exact
   Fail cell. Every Fail link and every backlink must resolve to a unique ID.
5. **Language-equivalent passes** â€” only when at least one `Pass*` exists, add
   `.findings-heading` h2 ("Language-Equivalent Passes"), then
   `.finding.lang-pass` notes. Each note uses `id="p-{lang}-{slug}"`, the same
   client and text spans as a finding, and a backlink to
   `#r-{lang}-{slug}`. Its sentence must name the omitted literal operation,
   the runtime rule that prevents interleaving or supplies cleanup, and why the
   observable invariant still holds. Start the sentence with
   `Pass because of {language/runtime} semantics:` so the reason is explicit.

**Letter grade scale:** A+ (100), A (95â€“99), A- (90â€“94), B+ (85â€“89),
B (80â€“84), B- (75â€“79), C+ (70â€“74), C (below 70).

**Severity:** high = reachable protocol/data-loss/crash bugs, med = reachable
behavioral or scalability deviations, low = cosmetic/minor/spec-only. Severity
dot counts represent distinct root causes, not the number of failed rows.

## Building the Rubric

Do NOT use a pre-written checklist. The spec is the checklist. Walk
`docs/client.pseudo` line by line and extract every testable requirement
directly from the spec text. Each requirement must match the spec's exact
wording, types, values, control flow, and ordering â€” not a summary or
paraphrase. If the spec says `parse_float`, the client must parse a float.
If the spec says `sleep` before `connect`, the client must sleep first.

Grade the implementation against what the spec actually says, not what
seems "close enough." A requirement that is partially implemented or
uses wrong types/values/ordering is a FAIL, not a PASS. The exception is a
platform-equivalent implementation that provably enforces the same observable
invariant under the required language-semantics pass; do not demand a redundant
literal guard or collection primitive from a different concurrency model.

**Requirement labels must be full sentences that describe the actual
requirement in plain English, close to the spec's own wording.** The
reader should understand exactly what is being checked without having to
cross-reference the spec. Do NOT use terse shorthand labels like
"handle_message SendDataMessage: close signal with atomic remove" â€” instead
write "Empty SendDataMessage closes and removes the client using atomic
remove; only the side that successfully removes the entry sends the close
signal." Every requirement row should read like a sentence a human wrote,
not a compressed tag.

**Status messages are grading requirements.** Every `log()` call in the
spec defines the exact message text and prefix (`[+]`, `[*]`, `[!]`).
Grade each one: the client must use the same prefix and substantially
the same wording. Messages that exist in the client but not the spec are
acceptable as long as they use the bracket prefix convention. Messages
that exist in the spec but are missing, use the wrong prefix, or have
materially different wording are FAILs.
