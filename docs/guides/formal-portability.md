# Qualify and plan a formal source outside the checkout

This tutorial starts with native synthetic task files and follows
`init -> inspect -> qualify -> probe --dry-run` from a temporary directory.
It needs Python 3.11 or newer, `uv`, and the native CLI built from the same
checkout as the adapter. The fixture uses no network, model, accelerator, or
proof assistant. Its results establish software behavior only.

## Install from the checkout

Run these commands in the Anarres checkout containing this change:

```bash
cargo install --path crates/anarres-cli --locked
uv tool install ./data/formal-verification/vero
anarres adapter doctor formal
anarres adapter doctor formal-fixture
```

The package installs the existing `formal` adapter, the
`formal-fixture` adapter, and the separate `formal-fixture-runner` command.
The `formal` adapter keeps its Vero source format and does not declare
`policy-probe`. The fixture declares `source-qualification` and `probe-plan`.
If `uv` reports that its tool directory is missing from `PATH`, run
`uv tool update-shell` and restart the shell before continuing.

## Create native files outside the repository

Create a new temporary working directory and generate the native source:

```bash
fixture_work=$(mktemp -d)
cd "$fixture_work"
anarres formal-fixture create native-fixture > source-identity.json
cat source-identity.json
```

The generator creates `native-fixture/fixture.json` and two development task
files, `development/a.txt` and `development/b.txt`. Each task asks for the
literal proof `true`. The metadata records source lineage, artifact digests,
licenses, grouping keys, and separate development and held-out partitions.
The held-out task has metadata only. Its file and directory are never created.

The command returns the actual content-addressed source revision and license.
Use that revision without replacing it with a mutable label:

```bash
fixture_revision=$(python3 -c \
  'import json; print(json.load(open("source-identity.json"))["revision"])')
anarres init native-fixture \
  --adapter formal-fixture \
  --revision "$fixture_revision" \
  --license Apache-2.0
anarres inspect native-fixture --json
anarres qualify native-fixture --json
```

`init` adds the source manifest. `inspect` reports
`qualification_ready: true`, `probe_plan_ready: true`, and
`probe_ready: false`. `qualify` verifies the native metadata and development
files. Its source-qualification gate becomes qualified while task containment,
policy support, measurement readiness, and downstream evidence remain
separate. Qualification never reads the held-out task.

## Inspect the ordered probe plan

Use a synthetic starting-policy identity and its immutable revision to plan
two seeds for each development task:

```bash
anarres probe native-fixture \
  --policy fixture-policy \
  --policy-revision "$fixture_revision" \
  --output plan.json \
  --dry-run -- --seed 3 --seed 1
```

Here the source revision is also a convenient immutable identifier for the
synthetic fixture policy. A real integration must bind the actual policy
revision. The plan output lives outside `native-fixture`. The adapter rejects
an output path inside its native source or equal to its manifest.

The command prints the full plan and writes the same JSON to `plan.json`.
Its six ordered steps qualify the source, preflight the fixture runtime,
require task containment, require explicit execution, run ordered attempts,
and verify and capture attempts. Only the first two steps execute during
planning. The four planned attempts are `(a, 3)`, `(a, 1)`, `(b, 3)`, and
`(b, 1)`.

Each attempt binds the source and task, source driver, fixture verifier and
runtime, starting policy, runner and harness, seed, limits, tool policy, and
output artifact names. The plan records `provider_calls: 0`,
`held_out_tasks_opened: false`, and `execution_available: false`. Planning
does not invoke `formal-fixture-runner`.

Confirm that rerunning with the same inputs produces identical plan bytes:

```bash
anarres probe native-fixture \
  --policy fixture-policy \
  --policy-revision "$fixture_revision" \
  --output plan-rerun.json \
  --dry-run -- --seed 3 --seed 1
cmp plan.json plan-rerun.json
test ! -e native-fixture/held-out
```

Both final commands exit successfully without output when the plan is
deterministic and the held-out directory remains absent.

## What this establishes

The fixture demonstrates installed source qualification and deterministic
planning without depending on the checkout's current directory or released
Anarres profiles. Its external runner accepts a bound fixture request on
standard input and returns an attempt record and proof artifact on standard
output. It validates only the literal fixture contract. No Lean proof, real
starting policy, source-selection decision, or downstream result is measured
by this tutorial.

Qualification rejects a task file with more than one hard link, so a
hard-linked checkout (for example a `cp -al` copy) is rejected, and its path
checks run before the read rather than on the open file.

The Vero source and runtime path remain available through `anarres formal`.
General driver discovery, real policy execution, and Dafny, Verus, and Rocq
drivers are follow-up work described in
[RFC 0008](../rfcs/0008-portable-formal-verification-contracts.md).
Actual execution needs its own explicit authorization and qualified task-only
containment receipt.

The repository's installed-adapter smoke check builds isolated wheels and
repeats this flow from a temporary directory with `PYTHONPATH` removed. From
the checkout, after building the native release binary, run:

```bash
cargo build --release --locked -p anarres-cli
uv run python tools/smoke_adapter_installation.py --binary target/release/anarres
```
