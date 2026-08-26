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
- A single client to grade (`csharp`, `nodejs`, `python`) — default is all three.
- A single section to focus on — default is all sections.

## Workflow

### 1. Read the spec

Read `docs/client.pseudo` in full. This is the golden standard — every
requirement in it is a grading criterion. Do not invent requirements that
aren't in the spec and do not skip requirements that are.

### 2. Build the rubric

Walk the spec section by section and extract every testable requirement.
Use the section structure below. Each requirement becomes a pass/fail check.

### 3. Read the clients

For each client being graded, read the relevant source files:

- **C#**: `builder/clients/csharp/templates/` — `Program.cs`, `MessengerClient.cs`,
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

- **PASS** — implements the requirement correctly
- **FAIL** — missing or incorrect implementation
- **N/A** — requirement does not apply to this client's platform (e.g.,
  User-Agent on C# WebSocket with net472)

When grading, keep these platform-specific facts in mind:
- C# `TcpClient` is pull-based — it does NOT need socket pause/resume. The
  system buffer queues incoming data until `ReadAsync` is called. This is
  correct behavior, not a missing feature.
- C# `ClientWebSocket` on .NET Framework 4.7.2 (net472) cannot set the
  `User-Agent` header — it is a restricted header. This is an N/A, not a FAIL.
- Node.js sockets are push-based and MUST be paused on accept and resumed
  on approval.
- Python asyncio sockets are push-based and MUST be paused on accept and
  resumed on approval.

#### Language-equivalent implementations

Do not false-fail an implementation that achieves the spec's invariant through
a platform-equivalent mechanism. Analyze concurrency, cleanup, and lifecycle
rows in the semantics of the target language and runtime — not by translating
the pseudo client into identical syntax and assuming identical hazards. When a
runtime guarantee (e.g., Node.js synchronous run-to-completion, Python's
single-threaded event loop) makes a literal pseudo step provably redundant,
score the row as Pass* and explain the equivalence in a language-pass note.
The spec is the authority — do not add requirements beyond it, and do not
require a specific close API (graceful or abortive) where the spec says only
"close without blocking dispatch."

#### Server behavior constraints

The server is the only peer. Do not invent requirements for message sequences
the server cannot produce. Key facts:

- `client_id` and `bind_id` are 10-char cryptographically random alphanumeric
  strings (62^10 keyspace). The server never reuses an ID. Do not require
  duplicate-ID handling, replacement guards, or overwrite protection for
  `InitiateTCPClientReq` or `InitiateBINDReq` — collisions cannot happen.
- The server sends exactly six message types to clients: CheckInMessage (0x04),
  InitiateTCPClientReq (0x01), InitiateTCPClientRep (0x02), SendDataMessage
  (0x03), InitiateBINDReq (0x05), CheckOutMessage (0x07). It never sends
  InitiateBINDRep (0x06) — that is client-to-server only.
- CheckInMessage is only sent on the first check-in when the client had no ID.
- CheckOutMessage is a standalone kill signal; no further messages follow.
- A second InitiateBINDReq with the same bind_id is always a STOP (empty
  listening_host, zeroed ports). The server never sends a start-bind for an
  ID that is already active.

If the spec contains a defensive guard against a scenario the server cannot
produce, grade the guard's presence or absence as N/A, not PASS or FAIL.

### 5. Report — HTML Artifact

Write the results to an HTML file and publish it with the Artifact tool.
Do NOT load the `artifact-design` skill — use the reference template
at `docs/skills/grade-clients/report-template.html` instead. Read
that file and copy its exact `<style>` block and HTML structure. Only
change the data (grades, requirements, pass/fail results, notes, file
references). Do not redesign, restyle, add JavaScript, add animations,
add ring charts, or add accordions.

**Rules:**
- Copy the CSS verbatim from the template. Do not modify colors, fonts,
  spacing, or class names.
- Keep every section visible on load — no accordions, no `display:none`,
  no JavaScript toggling.
- Every requirement gets its own `<tr>`. Do not roll up or summarize.
- Fail cells contain ONLY an `<a class="v-fail" href="#f-{lang}-{slug}">Fail</a>`
  linking to the corresponding finding at the bottom. The containing cell gets
  `id="r-{lang}-{slug}"` so the finding can link back to that exact matrix cell.
  No inline code, no file references, no `<div class="fail-detail">` — just
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
1. **Header** — `.eyebrow` ("Spec Compliance Audit"), `<h1>` title,
   `.subtitle` with two `.pill` spans for spec file and branch.
2. **Grade cards** — `.cards` grid, three `.card.{cs|js|py}` divs. Each
   has: `.card-lang`, `.card-name`, `.card-grade` (letter, colored by
   accent), `.card-pct` (pass/total · pct%), `.card-note` (1–2 sentences),
   `.severity-dots` with `.dot.high`, `.dot.med`, `.dot.low` + counts.
3. **Requirement tables** — `.tables-heading` h2, then for each section:
   `.section-label` div ("01 &ensp; Section Name"), then `<table>` inside
   `.table-wrap`. Columns: Requirement (46%), C# (18%), Node.js (18%),
   Python (18%).
4. **Findings** — `.findings-heading` h2 ("Findings"), then findings
   grouped by severity. Each severity group starts with a
   `.severity-heading` h3 (`"High"`, `"Medium"`, `"Low"`, or `"Info"`).
   Within each group, `.finding` divs are ordered by client (C#, Node.js,
   Python). Each finding has `id="f-{lang}-{slug}"` matching the `href` in
   the table's Fail link. Structure:
   `<div class="finding" id="f-py-retry-float">`
     `<span class="f-severity high">High</span>`
     `<span class="f-client py">Python</span>`
     `<span class="f-text">Full sentence describing the failure.</span>`
     `<a class="f-back" href="#r-py-retry-float">Back to matrix</a>`
   `</div>`
   The `.f-severity` span uses class `high`, `med`, `low`, or `info`.
   The `.f-client` span uses class `cs`, `js`, or `py` for per-client
   accent color. The `.f-text` is a complete sentence that includes the
   file:line reference inline and clearly describes what is wrong and why.
   When the user clicks a Fail link, the browser scrolls to the finding
   and `:target` CSS highlights it with a red left border and background.
   The finding's **Back to matrix** link returns to and highlights the exact
   Fail cell. Every Fail link and every backlink must resolve to a unique ID.
   Omit any severity group that has no findings.
5. **Language-equivalent passes** — only when at least one `Pass*` exists, add
   `.findings-heading` h2 ("Language-Equivalent Passes"), then
   `.finding.lang-pass` notes. Each note uses `id="p-{lang}-{slug}"`, the same
   client and text spans as a finding, and a backlink to
   `#r-{lang}-{slug}`. Its sentence must name the omitted literal operation,
   the runtime rule that prevents interleaving or supplies cleanup, and why the
   observable invariant still holds. Start the sentence with
   `Pass because of {language/runtime} semantics:` so the reason is explicit.

**Letter grade scale:** A+ (100), A (95–99), A- (90–94), B+ (85–89),
B (80–84), B- (75–79), C+ (70–74), C (below 70).

**Severity:** high = reachable protocol/data-loss/crash bugs, med = reachable
behavioral or scalability deviations, low = cosmetic/minor/spec-only. Severity
dot counts represent distinct root causes, not the number of failed rows.

## Building the Rubric

Do NOT use a pre-written checklist. The spec is the checklist. Walk
`docs/client.pseudo` line by line and extract every testable requirement
directly from the spec text. Each requirement must match the spec's exact
wording, types, values, control flow, and ordering — not a summary or
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
"handle_message SendDataMessage: close signal with atomic remove" — instead
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
