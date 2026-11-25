# RFC 0008: Portable formal-verification contracts

- Status: proposed
- Date: 2026-11-25
- Scope: the first pull request of issue #66

RFC 0007 belongs to another open pull request, so this proposal uses 0008.

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
JSON excluding `content_id` itself. Canonical JSON sorts keys, uses compact
separators, rejects non-finite numbers, and encodes the result as UTF-8.
Changing declared semantics or implementation bytes changes the identity.

Drivers are trusted installed code. A content identity detects changes but
does not establish trust, provide task containment, or authorize execution.
Manifests never select arbitrary Python files, shell snippets, or remote code
to load. Another installed Python package can implement these protocols.
General driver discovery and package-independent dispatch remain follow-up
work.

## Native contracts and evidence boundaries

A source contract identifies its proof assistant or verification language,
exact toolchain, repository or task set, immutable revision, license, and
content digest. Native task metadata preserves theorem, specification,
function, module, repository, and generation-family grouping keys where those
concepts apply. Repository and generation-family lineage remain visible when
tasks share an upstream source. A task count alone does not establish the
number of independent environments.

Source metadata records the task files, dependencies, context, allowed
reference material, partition, trusted axioms, unsafe declarations,
admitted-proof policy, and leakage checks. An artifact reference binds its
URI, SHA-256 digest, media type, size, license, and producing run. Local task
paths must be canonical relative paths within the declared source. The fixture
rejects parent traversal, symlinks, and hard links before reading task files. Credentials,
machine-specific paths, and protected task contents stay outside repository
records.

Four endpoints are distinct contracts: `proof-only`, `code-and-proof`,
`specification-construction`, and `specification-faithfulness`. A verifier
contract binds its native command, toolchain, allowed assumptions, and strict
success semantics. Verifier acceptance of a constructed specification does
not by itself establish specification faithfulness.

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
starting-policy identity and immutable revision, runner or harness identity,
source and task identity, seed, runtime report, resource limits, tool policy,
and output-artifact contract. Provider credentials are process configuration
outside this request and its receipt. The fixture supplies an external command
that reads one `anarres.formal-run-request.v1` request from standard input and
writes a sealed `anarres.formal-run-response.v1` object containing an
`anarres.formal-attempt.v1` record and inline proof artifact to standard output.
It uses no provider, network,
accelerator, or proof assistant.

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
the existing execution fields. The core owns `--dry-run`; callers must place
it before the adapter argument separator `--`. A copy after that separator is
rejected so adapter arguments cannot silently select a different readiness gate.

The same installed package supplies a separate `anarres-formal-fixture`
executable accepting `formal-fixture-v1`. Its descriptor declares
`source-qualification` and `probe-plan`, and omits `policy-probe`. This keeps
the existing `formal` adapter's `vero-checkout-v1` source format and default
`init` behavior intact. [RFC 0003](0003-external-adapter-protocol.md) continues
to govern executable discovery and the runtime handshake.

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

This follows the planning boundary in
[RFC 0004](0004-portable-domain-workflow-plans.md). Plans remain deterministic
and content-addressed. No timestamp, temporary directory name, downstream
outcome, or provider credential participates in fixture plan identity.

The candidate compatibility helper compares language, toolchain, endpoint,
starting policy and revision, target, verifier, unit, measurement contract,
and allowed-assumption contract. Any mismatch rejects the comparison.
Compatibility establishes shared interpretation only. Candidate scoring,
baselines, uncertainty, selection, abstention, and a frozen decision are
outside this pull request.

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

Follow-up work includes general installed-driver dispatch, real external
runner execution with receipt validation, capable trainable-policy support,
measurement and decision records, and independent-source selection. Dafny,
Verus, and Rocq integrations need their own source, verifier, assumptions,
grouping, and conformance tests. They do not inherit Lean qualification.

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
