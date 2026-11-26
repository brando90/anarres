# RFC 0008: Portable formal-verification contracts

- Status: proposed
- Date: 2026-11-25
- Scope: the first pull request of issue #66

## Context

The formal adapter qualifies the pinned Vero source and a model-free Lean
runtime. Its released development evidence binds specific sources, policies,
execution code, and verifiers. Reusing those commands for another source needs
explicit interfaces that preserve these identities and each verifier's failure
semantics.

This proposal establishes those interfaces, an additive Vero integration, and
a deterministic fixture. Lean is the only real proof assistant integrated in
this pull request. The [source qualification](../../experiments/cyber/formal-verification/source-qualification/README.md)
keeps all five audited sources in reserve, with Vero leading. The fixture
exercises software portability and supplies no evidence for selecting a
scientific source. Dafny, Verus, and Rocq drivers remain follow-ups.

## Proposed decision

Keep reusable interfaces in the installed `anarres_formal_adapter` package.
The Rust core continues to own source-manifest validation, adapter discovery,
shared aggregation, identity, comparison, and freeze records. Installed Python
drivers retain source processing, proof-assistant interaction, and execution.

The interfaces in
[`contracts.py`](../../data/formal-verification/vero/src/anarres_formal_adapter/contracts.py)
are structural Python protocols:

| Interface | Operations | Responsibility |
| --- | --- | --- |
| `SourceDriver` | `descriptor()`, `qualify(source)` | Identify and qualify native source data |
| `VerifierDriver` | `descriptor()`, `preflight(**inputs)` | Identify verifier semantics and qualify its runtime |
| `ProverRunner` | `descriptor()`, `run(request)` | Consume a bound attempt request and return a structured attempt |

Their descriptor schemas are versioned independently as
`anarres.formal-source-driver.v1`, `anarres.formal-verifier-driver.v1`, and
`anarres.formal-prover-runner.v1`. Each descriptor records its name, version,
declared semantics, and SHA-256 digests of its installed implementation files,
including `contracts.py`. Its `content_id` is the SHA-256 digest of canonical
JSON excluding `content_id` itself. Changing declared semantics or
implementation bytes changes the identity.

Canonical JSON is the output of Python's `json.dumps` with `sort_keys=True`,
`separators=(",", ":")`, `ensure_ascii=True`, and `allow_nan=False`. Object
keys are sorted by code point, and no whitespace separates tokens. Every
non-ASCII character is written as a lowercase `\uXXXX` escape (a UTF-16
surrogate pair outside the Basic Multilingual Plane), so the encoded bytes are
ASCII. Quotation marks, backslashes, and `\b`, `\f`, `\n`, `\r`, and `\t` use
their short JSON escapes, other control characters use `\u00XX`, and `/` is
not escaped. Integers have no fraction or exponent. Floats use Python's `repr`
format, the shortest decimal string that round-trips to the same binary64
value, such as `0.1`, `1e-07`, and `1e+16`. NaN and infinity are rejected. For
example, the object `{"ratio": 0.1, "name": "é", "count": 3}` encodes to the
bytes `{"count":3,"name":"\u00e9","ratio":0.1}` with SHA-256
`cb4388342572d2ff789acd0763d43b173b05ba7d2a402e1850adaa737d39fa25`. Another
implementation must reproduce these bytes to reproduce a `content_id`. The
contract tests pin this vector.

Drivers are trusted installed code. A content identity detects changes but
does not establish trust, provide task containment, or authorize execution.
Manifests never select arbitrary Python files, shell snippets, or remote code
to load. Another installed Python package can implement these protocols.
General driver discovery and package-independent dispatch remain follow-up
work.

## Native contracts and evidence boundaries

In this RFC, an *endpoint* is the task contract type that a source offers and
a verifier checks: `proof-only`, `code-and-proof`,
`specification-construction`, or `specification-faithfulness`. The four
endpoints are distinct contracts. An endpoint differs from a *target* in the
shared vocabulary of the [writing standard](../standards/writing.md). A target
is the held-out capability used to assess downstream utility. An endpoint
only fixes what an attempt must produce and what the verifier accepts.
Verifier acceptance of a constructed specification does not by itself
establish specification faithfulness.

*Trusted assumptions* are the axioms and other declarations a verifier accepts
without proof. *Unsafe features* are language features that bypass the
verifier. This RFC uses these two terms for those concepts. The fixture
records them in its `trusted_axioms` and `unsafe_features` fields, and the
Vero verifier descriptor uses a `trusted_assumptions` field.

The records differ between the two drivers in this pull request. The fixture
source record identifies its language, toolchain, repository, task set,
license, and endpoint, and its content digest is the manifest revision. It
records the task files, dependencies, context, allowed reference material, and
partition of each task. It records empty `trusted_axioms` and
`unsafe_features` lists and an admitted-proof policy of `forbidden`. The
fixture verifier descriptor records the same three values, its toolchain,
native command, endpoints, outcomes, and strict-success rule. Each task preserves
theorem, specification, function, module, repository, and generation-family
grouping keys. Repository and generation-family lineage remain visible when
tasks share an upstream source. A task count alone does not establish the
number of independent environments.

The Vero source descriptor records the language, the Lean toolchain string,
the full released source pin (repository, commit, license, and expected
counts, including a count of 81 trusted axioms), its endpoints, and the
native mode for each endpoint. The Vero verifier descriptor records the
language, endpoints, strict-success rule, a reference to the runtime
contract's verifier command, and its trusted assumptions as free text. It has no toolchain field. It binds
the Lean version only through the digest of `source-pin.json` in its
`implementation` record. Neither Vero descriptor records admitted proofs or
unsafe features, and neither Vero driver performs leakage checks.

An artifact reference binds its URI, SHA-256 digest, media type, size,
license, and producing run. Local task paths must be canonical relative paths
within the declared source. Before reading `fixture.json` or a task file, the
fixture rejects parent traversal, symlinks, hard links, and file types other
than regular files, such as FIFOs. Credentials, machine-specific paths,
and protected task contents stay outside repository records.

Keep six evidence states separate:

| State | Evidence required |
| --- | --- |
| Source qualification | Pinned source identity, licenses, task metadata, and source checks |
| Runtime qualification | Exact runtime, native verifier, build, and preflight checks |
| Task containment | Qualified restriction to the allowed task files, tools, and resources |
| Policy support | Strict success under the identified starting policy and endpoint |
| Measurement readiness | The study's support, coverage, repetition, and validity requirements |
| Downstream evidence | Outcomes under the separately governed training and evaluation contract |

A successful source qualification advances only its own state. A runtime
preflight does not issue a task-containment receipt. Policy support and
measurement readiness do not establish downstream utility.

## External prover-runner protocol

The runner boundary accepts a content-addressed JSON request binding the
starting-policy identity and immutable revision, runner descriptor, harness
identity (the runner's name and `content_id`), source and task identity, seed,
runtime report, resource limits, tool policy, and output-artifact contract.
Provider credentials are process configuration outside this request and its
receipt. The fixture supplies an external command that reads one
`anarres.formal-run-request.v1` request from standard input and writes a
sealed `anarres.formal-run-response.v1` object containing an
`anarres.formal-attempt.v1` record and inline proof artifact to standard
output. It uses no provider, network, accelerator, or proof assistant.

The attempt record retains the request identity, task identity, seed, output
artifacts, and separate success and failure indicators. Its outcomes are
`strict-success`, `strict-proof-failure`, `parser-failure`, `build-failure`,
`verifier-failure`, `timeout`, `unsupported`, and `infrastructure-failure`.
An invalid execution receives its own outcome and cannot become a strict proof
failure or a scientific reward of zero. The fixture records zero model tokens
and an unmeasured wall time. It does not invent elapsed time to make reruns
deterministic.

Actual policy execution requires explicit authorization and a qualified
task-only containment receipt bound to the exact source, verifier, runner,
and runtime. The first pull request provides only the deterministic fixture
runner. Real external policy execution, containment-receipt validation for
that execution, and provider integration remain disabled.

## Portable planning path

Extend the capability boundary in [RFC 0006](0006-native-environment-sources.md)
with `probe-plan`. The generic `probe --dry-run` command requires this
capability. Executing a policy still requires `policy-probe`. A planning
capability grants no execution capability.

Source inspection adds `can_plan_probe` and `probe_plan_ready` while retaining
the existing execution fields. The core owns `--dry-run`, and callers must
place it before the adapter argument separator `--`. A copy after that
separator is rejected so adapter arguments cannot silently select a different
readiness gate.

`--dry-run` makes planning opt-in. This differs from the convention in
[RFC 0004](0004-portable-domain-workflow-plans.md), where `run-task --execute`
is the explicit execution step, and from the molecular adapter, whose
`probe-source` plans by default and executes only with an adapter-owned
`--execute` flag. In this pull request nothing executes. The fixture requires
`--dry-run` and declares no `policy-probe`, and the `formal` adapter declares
neither `probe-plan` nor `policy-probe`. Whether the core must require its own
execution flag before any future `policy-probe` dispatch is deferred to the
execution pull request. That pull request must not treat the absence of
`--dry-run` as authorization to execute.

The same installed package supplies a separate `anarres-formal-fixture`
executable accepting `formal-fixture-v1`. Its descriptor declares
`source-qualification` and `probe-plan`, and omits `policy-probe`. This keeps
the existing `formal` adapter's `vero-checkout-v1` source format and default
`init` behavior intact. [RFC 0003](0003-external-adapter-protocol.md) continues
to govern executable discovery and the runtime handshake. RFC 0006 permits
`source-qualification` only after a real native source passes conformance
tests. The fixture's declaration for its synthetic source is an exception
limited to the fixture adapter, which exists to test software conformance.

The fixture creation helper writes native `fixture.json` metadata and two
small development tasks. Held-out metadata has no corresponding task file.
After installation, a temporary directory outside the repository can run
`init -> inspect -> qualify -> probe --dry-run`. Source qualification reads
only development-task files. Planning lists all attempts in task order and
then seed order, with the bindings needed by the fixture runner. It never
invokes the runner or opens a held-out task. The complete ordered plan is
printed for inspection before any execution is possible.

The [outside-checkout tutorial](../guides/formal-portability.md) gives the exact
installation and native-source commands.

Like the plans in RFC 0004, fixture plans are deterministic and
content-addressed. No timestamp, temporary directory name, downstream
outcome, or provider credential participates in fixture plan identity.

The candidate compatibility helper compares language, toolchain, endpoint,
starting policy and revision, target, verifier, unit, measurement contract,
and trusted assumptions (the `assumptions` field). Any mismatch rejects the
comparison. Compatibility establishes shared interpretation only. Candidate
scoring, baselines, uncertainty, selection, abstention, and a frozen decision
are outside this pull request.

## Vero migration and released evidence

[`vero_drivers.py`](../../data/formal-verification/vero/src/anarres_formal_adapter/vero_drivers.py)
wraps the existing source qualification and runtime preflight. The source
driver preserves the released source pin, license exceptions, Lean toolchain,
and mapping from `proof-only` and `code-and-proof` to Vero's native `proof`
and `codeproof` modes. The verifier driver preserves the existing native
runtime checks. Existing source and runtime report payloads retain their
semantics and serialization. The `formal` descriptor continues to omit
`policy-probe`.

Released records, manifests, protocols, and execution code remain unchanged.
The manifest regression pins the two manifest digests from main at `d168e2a`
and checks the raw bytes of all 98 repeated-measurement entries and all 12
public-evidence entries. Changing both an evidence file and its manifest still
fails this regression. The existing negative Leanstral development evidence
and later GPT-5.6 Sol repeated measurement retain their own scientific
boundaries.

## Remaining gaps

The released Vero execution path cannot be rewritten through these interfaces
in place. `policy-probe-protocol.codex-sol-v2.json` binds the following files
under `data/formal-verification/vero/` by SHA-256:

- `run_codex_sol_probe.py`
- `run_codex_sol_queue_item.py`
- `aggregate_codex_sol_measurements.py`
- `aggregate_probe_measurements.py`
- `build_probe_queue.py`
- `validate_codex_sol_probe_protocol.py`
- `validate_task_boundary_receipt.py`

The released
`results/task-boundary-qualification.codex-sol-v5/task-boundary-receipt.json`
also binds `serve_vibe_sandbox.py`, `run_containment_tests.py`,
`materialize_probe_task.py`, and `AnarresAxiomCheck.lean`, as well as the
probe script. Routing those files differently changes a frozen execution
identity and would require a separately versioned route, protocol, and
qualification receipt. The existing commands remain available with their
native scientific meaning.

The Vero interfaces expose legacy qualification semantics. They do not add a
new task-level axiom audit, leakage audit, native verifier implementation, or
portable runner for Vero. This pull request does not execute a fresh Vero
checkout, Lean build, or model probe. The fixture's runtime and task boundaries
demonstrate the software contract only.

The Vero descriptors do not yet bind the verifier toolchain by hash. They
have no structured records of admitted proofs or unsafe features, and their
trusted assumptions are free text rather than a structured reference such as a
digest of the trusted-axiom list. No driver performs leakage checks. These
records are follow-up work, and this pull request does not claim them for
Vero.

Follow-up work includes general installed-driver dispatch, real external
runner execution with receipt validation, capable trainable-policy support,
measurement and decision records, and independent-source selection. Dafny,
Verus, and Rocq integrations need their own source, verifier, trusted
assumptions, grouping, and conformance tests. They do not inherit Lean
qualification.

## Validation

Tests must exercise the outside-checkout fixture path, deterministic reruns,
request and artifact tampering, path escape, incompatible candidates, and
separate attempt outcomes. Dry-run tests must make runner execution and
held-out task access fail if attempted. Existing Vero source/runtime tests
check routing through the wrappers while preserving report behavior. The
released-manifest regression checks every listed file and rejects coordinated
manifest rewriting. These CPU-only checks require no model or proof assistant.

The required repository gates are `make check` and `make study-check`.
Successful fixture checks establish implementation behavior. Fresh native
runtime checks and prospective scientific evidence require their own later
execution records.
