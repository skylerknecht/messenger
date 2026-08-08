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

### 5. Report — HTML Artifact

Write the results to an HTML file and publish it with the Artifact tool.
Do NOT load the `artifact-design` skill — use the reference template
at `.claude/skills/grade-clients/report-template.html` instead. Read
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
- File:line references in requirement tables use `<span class="file-ref">`.
  File:line references in the **failures list** MUST be `<a>` anchor links:
  `<a class="file-ref" href="#fail-{lang}-{slug}">filename.ext:LINE</a>`
  that link to the corresponding fail row in the tables above.
- Rows containing any FAIL get class `fail-row` AND a unique
  `id="fail-{lang}-{slug}"` on the `<tr>` (e.g. `fail-py-retry-float`,
  `fail-js-poll-sleep`). The failures list links to these IDs.
- Use `v-pass`, `v-fail`, `v-na` classes exactly as shown in the template.
- Fail cells include a `<div class="fail-detail">` with the note and
  file-ref span.

**Layout (matches template exactly):**
1. **Header** — `.eyebrow` ("Spec Compliance Audit"), `<h1>` title,
   `.subtitle` with two `.pill` spans for spec file and branch.
2. **Grade cards** — `.cards` grid, three `.card` divs. Each has:
   `.card-lang`, `.card-name`, `.card-grade` (letter), `.card-pct`
   (pass/total · pct%), `.card-note` (1–2 sentences), `.severity-dots`
   with `.dot.high`, `.dot.med`, `.dot.low` + counts.
3. **Requirement tables** — `.tables-heading` h2, then for each section:
   `.section-label` div ("01 &ensp; Section Name"), then `<table>` inside
   `.table-wrap`. Columns: Requirement (46%), C# (18%), Node.js (18%),
   Python (18%).
4. **Failures list** — `.failures-heading` h2, then `.failure-item` divs
   each with `.failure-tag`, `.failure-req`, `.failure-note` containing
   a `.file-ref` span.

**Letter grade scale:** A+ (100), A (95–99), A- (90–94), B+ (85–89),
B (80–84), B- (75–79), C+ (70–74), C (below 70).

**Severity:** high = protocol/crash bugs, med = behavioral deviations,
low = cosmetic/minor.

## Building the Rubric

Do NOT use a pre-written checklist. The spec is the checklist. Walk
`docs/client.pseudo` line by line and extract every testable requirement
directly from the spec text. Each requirement must match the spec's exact
wording, types, values, control flow, and ordering — not a summary or
paraphrase. If the spec says `parse_float`, the client must parse a float.
If the spec says `sleep` before `connect`, the client must sleep first.

Grade the implementation against what the spec actually says, not what
seems "close enough." A requirement that is partially implemented or
uses wrong types/values/ordering is a FAIL, not a PASS.
