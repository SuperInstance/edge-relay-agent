# edge-relay-agent

A standalone, zero-dependency Python toolkit that models **asymmetric
information flow** between a *cloud* (high-capacity, full-context) and an
*edge* (resource-constrained, real-time) environment. It is built around four
pieces: a `ResearchRelay` that registers cloud sources / edge nodes, compresses
cloud→edge payloads to fit bandwidth limits, expands edge→cloud findings with
metadata, and routes prioritized messages; four "tender" carriers
(`ResearchTender`, `DataTender`, `PriorityTender`, `ContextTender`) that handle
query compression, event batching/dedup, urgency translation, and differential
context sync; a `DiscoveryService` with an in-memory service registry and
heartbeat-based health monitor; and a `BandwidthBudget` that allocates
bytes/second across message types with overflow queuing and priority-based
preemption. Everything is driven through an 8-subcommand CLI that persists
state to a JSON file.

The core engines are complete and covered by **79 passing tests**. The
network-facing pieces (a listening `serve` loop, real peer auto-discovery over
the wire) are intentionally **not** implemented — this is an in-process engine
and CLI, not a deployed network service. See [Honesty assessment](#honesty-assessment)
for the full real-vs-stub breakdown.

> This repo is part of a "fleet" of research agents and follows the fleet's
> Git-Agent / I2I conventions (see `CHARTER.md`). It is self-contained and can
> be used on its own.

## Honesty legend

Throughout this README (and matching the fleet convention):

| Marker | Meaning |
|--------|---------|
| ✅ | Implemented and tested. |
| ⚠️ | Partial / caveat — works but with a known limitation. |
| 🔮 | Described or planned but not present in the code today. |

## Requirements

- **Python 3.10+** (CI runs against 3.10, 3.11, 3.12).
- **No third-party runtime dependencies.** Every module uses only the Python
  standard library (`argparse`, `json`, `hashlib`, `zlib`, `socket`, `enum`,
  `dataclasses`, `time`, ...).
- `pytest` is only needed to run the test suite.

No `pip install` step is required to use the agent — clone and run `cli.py`
directly.

## Quick start

All state (registered sources/nodes, discovery registry, bandwidth budget) is
kept in a single `state.json`, located by default at
`~/.local/state/edge-relay-agent/state.json` (respects `XDG_STATE_HOME`). Point
every command at the same `--state-dir` if you want to share state, or omit it
to use the default.

```bash
# 1. Initialize the agent (creates state.json). Verified to run. ✅
python3 cli.py onboard --agent-id relay-edge-01 --port 8090 \
  --bandwidth 4096 --extra-capabilities cuda,monitoring

# 2. Check status. Verified to run. ✅
python3 cli.py status

# 3. Register an edge node, then route a cloud→edge message to it. Verified. ✅
python3 cli.py register-edge jetson-orin --capabilities cuda,sensors \
  --constraints vram=8192,watts=15
python3 cli.py route "Benchmark the matmul kernel" \
  --from oracle1 --to jetson-orin --direction c2e --priority high

# 4. Inspect the bandwidth budget and available compression strategies. ✅
python3 cli.py bandwidth --verbose
```

A real `route` invocation returns a routing plan like:

```json
{
  "message_id": "msg-1783719724453",
  "direction": "cloud_to_edge",
  "source": "oracle1",
  "destination": "jetson-orin",
  "route": ["direct_to_edge"],
  "actions": ["deliver_to_jetson-orin"]
}
```

> The examples above were each executed during documentation and confirmed to
> run against a temporary state directory.

## CLI reference

```
usage: edge-relay-agent [-h] [--state-dir STATE_DIR]
                        {serve,register-cloud,register-edge,route,discover,bandwidth,onboard,status}
                        ...

Edge Relay Agent — standalone research relay for cloud-edge communication
```

| Subcommand | What it does | Status |
|------------|--------------|--------|
| `onboard` | First-time setup; writes `state.json` (agent id, capabilities, port, bandwidth). | ✅ |
| `status` | Prints agent status from saved state (sources, nodes, routed count, discovery summary). | ✅ |
| `register-cloud` | Register a cloud source by name + capabilities. | ⚠️ see note |
| `register-edge` | Register an edge node with capabilities and `key=value` constraints. | ✅ |
| `route` | Route a message between a `--from` source and `--to` target; prints the routing plan. | ✅ |
| `discover` | Show the discovery registry (or `--health` / `--capabilities` views). | ⚠️ in-memory only |
| `bandwidth` | Show bandwidth budget snapshot (`-v` adds compression-strategy info). | ✅ |
| `serve` | Foreground "server" loop printing periodic heartbeats. | ⚠️ no socket |

Key flags worth knowing:

- `--state-dir DIR` (global) — override the state directory for any command.
- `route --direction {c2e,e2c,e2e,internal}` — message direction; aliases like
  `cloud-to-edge` are also accepted.
- `route --priority {critical,high,medium,low,info}` — maps to the relay's
  `MessagePriority` enum.
- `register-edge --constraints vram=8192,watts=15.5,name=foo` — values are
  parsed as int, then float, then string.
- `onboard --force` — overwrite an existing `state.json`.
- `EDGE_RELAY_DEBUG=1` — print a full traceback when a command errors.

## Architecture

The codebase is ~2.6k lines across four stdlib-only modules plus the CLI. Each
module is self-contained and round-trip serializable (`to_dict()` /
`from_dict()`).

### `relay.py` — core relay engine ✅

The central module. Defines the data model and the routing/compression logic.

- `MessageDirection` / `MessagePriority` enums.
- `CloudEdgeAsymmetry` — encodes the design thesis that cloud and edge cannot
  fully approximate each other; logs `divergence`s between cloud assumptions
  and edge reality (severity-gated into `assumption_failures`).
- Data classes: `CloudSource`, `EdgeNode`, `ResearchQuery`, `EdgeFinding`,
  `RelayMessage` — each with `to_dict`/`from_dict`.
- `ResearchRelay` — the engine: registers sources/nodes, submits queries and
  findings, `compress_for_edge()` (strips `_`-prefixed and metadata fields,
  caps lists, truncates to a byte budget), `expand_from_edge()` (enriches
  findings with cloud counts/timestamps), `prioritize_queries()`,
  `batch_findings()`, and `route_message()` (direct-to-edge / broadcast /
  peer-to-peer / internal, with a `destination_not_found` path).

### `tender_types.py` — specialized message carriers ✅

Four "tender" classes that carry cloud↔edge information, each owning one
concern:

- `ResearchTender` — `compress_query()` (sentence-level truncation to a byte
  limit), research-session lifecycle (`start_session` / `add_session_finding` /
  `complete_session`).
- `DataTender` — event accumulator with MD5-based **deduplication**, priority
  ordering (`trust` > `capability` > `model` > `general`), and byte+count
  bounded `batch()` / `flush_and_batch()`.
- `PriorityTender` — bidirectional cloud↔edge urgency translation with
  configurable mappings and a **deferral-escalation** rule (defer 3× →
  auto-escalate to `queued`).
- `ContextTender` — per-node context versioning with differential updates
  (only changed keys returned) and version-conflict detection. ⚠️ `sync_diff()`
  cannot reconstruct intermediate diffs across a version gap; it returns a full
  re-sync instead (documented inline at `tender_types.py`).

### `discovery.py` — service registry & health ✅ / ⚠️

- `AgentRecord` (with a stable sha256 `fingerprint`) and `AgentState` lifecycle
  (`unknown`/`active`/`idle`/`degraded`/`offline`).
- `ServiceRegistry` — in-memory registry with capability and hostname **indices**
  for O(1)-ish lookup (`find_by_capability`, `find_by_hostname`).
- `HeartbeatMonitor` — derives state from time-since-last-heartbeat (30s →
  degraded, 90s → offline) and fires `on_state_change` callbacks.
- `CapabilityAdvertiser` — builds the local agent's advertisement payload.
- `DiscoveryService` — composes the above into the high-level API used by the
  CLI.

⚠️ Despite the module docstring ("Auto-discover other agents on the network"),
there is **no networking code** — no socket bind/listen, no multicast/mDNS.
Peers are added manually via `discover_agent()` / the `discover-agent` path.
Treat it as a local registry of records you tell it about, not live network
discovery. 🔮 Real network discovery would be a future addition.

### `bandwidth.py` — bandwidth budgeting & compression ✅

- `CompressionStrategy` enum (`none`, `zlib`, `truncate`, `strip_metadata`,
  `hybrid`) and `CompressionEngine` (with cumulative stats and a
  `best_strategy()` that tries all strategies and picks the smallest fitting
  output).
- `BandwidthMessage` + `PriorityQueue` — bounded queue that **evicts the
  lowest-priority** message when full; `dequeue`/`dequeue_batch` return highest
  priority first.
- `BandwidthBudget` — the allocator: per-tender-type fractions of `total_bps`,
  **adaptive boost** for active research sessions, three-way outcomes per
  message (`delivered` / `queued` / `dropped`), `process_overflow()` retry,
  and `preempt()` to drop low-priority backlog under load.

### `cli.py` — command surface ✅

Thin orchestration over the four modules. Lazy-imports each engine inside its
handler to keep startup fast, loads/saves `state.json` around every mutating
command, and pretty-prints JSON results. Subcommands are wired in
`build_parser()`; `main()` wraps handlers and honors `EDGE_RELAY_DEBUG`.

## Honesty assessment

**Genuinely complete and tested (✅):** compression & truncation, event
batching/dedup, priority translation + escalation, context versioning &
conflict detection, bandwidth allocation/queue/preempt, the priority queue,
service-registry indices, heartbeat state derivation, and full
`to_dict`/`from_dict` round-trips for every model.

**Working but with real limitations (⚠️):**

- **`serve` opens no socket.** `cmd_serve()` (`cli.py:117`) states inline that
  a real network server loop is not implemented; it instead runs a foreground
  loop printing a heartbeat summary every 10 s. The relay engine itself is
  in-process — `route_message()` produces a routing *plan* (route + actions)
  rather than performing network delivery.
- **`register-cloud` does not persist `url`.** The `url` positional argument is
  required and echoed in the command's JSON output, but `CloudSource` has no
  URL field, so the URL is absent from `state.json`. Use `--name` as the stable
  identifier.
- **`discovery` is not networked** (see module note above) — manual peer
  registration only.
- **`ContextTender.sync_diff` returns full re-syncs** across version gaps
  (intentional; documented in code).

**No stubs found:** a search for `TODO`, `FIXME`, `NotImplementedError`,
`stub`, or `placeholder` across the Python sources returned nothing — the
caveats above are scope/feature limits, not unfinished code paths.

## Testing

```bash
python3 -m pytest tests/ -v
```

The suite (`tests/test_edge_relay_agent.py`, stdlib `unittest`-based, runnable
via `pytest`) covers all four modules plus CLI parsing and a full
cloud→edge→cloud integration round trip. **79/79 pass.** CI
(`.github/workflows/ci.yml`) runs the same command against Python 3.10, 3.11,
and 3.12.

## State & configuration

- State file: `~/.local/state/edge-relay-agent/state.json` (override per
  command with `--state-dir`, or globally via `XDG_STATE_HOME`).
- The file holds `relay`, `discovery`, and `bandwidth` sub-objects plus
  `onboarded_at` / `version`. Each CLI command loads, mutates, and rewrites it.
- There are no environment-variable secrets, no network credentials, and no
  hardcoded keys anywhere in the codebase.

## License

MIT — see `LICENSE`.
