# Reflective Reviewer — Implementation

This doc describes the concrete implementation of the slow loop described in
`docs/10-reflective-agent-loop.md`. Read that doc first.

## What lives here

```
audio/heuristic_schema.py        Single source of truth for schema bounds + atomic writer + history log helpers.
audio/profile_scorer.py          Telemetry → fitness score. Appends `score` events to history.
audio/reflective_reviewer.py     Picks/mutates/writes profiles. Three subcommands.
audio/profiles/                  Seed population: balanced, sparse, dense, corrective, wake, rest.
audio/run_reflective_reviewer.sh Thin launcher used by cron and humans.
audio/runtime/                   Bridge writes here. Reviewer writes here. Never committed.
  ├── swn_camera_soundscape_status.json   Bridge → reviewer (read-only for reviewer).
  ├── heuristic_profile.json              Reviewer → bridge (advisory; bridge clamps).
  └── profile_history.jsonl               Append-only: writes, scores, decisions, validation warnings.
tests/test_reflective_reviewer.py
```

## Architecture

```
fast loop (bridge)              unchanged. realtime. deterministic. clamped.
        ↓
status JSON @ 60Hz              existing.
        ↓
arc log (profile_history.jsonl) append-only. writes, scores, decisions.
        ↓
cron tick                       wakes reviewer in one of two modes.
        ↓
reviewer
  • decide          deterministic: classify window, pick seed family, mutate, write.
  • agent-brief     emit JSON brief on stdout; an agent picks and writes via apply-profile.
  • apply-profile   write an agent-authored profile after schema clamp.
        ↓
heuristic_profile.json          advisory. bridge re-clamps on read.
        ↓
scorer (next cron tick)         samples the next telemetry window, scores it, appends fitness.
```

The reviewer never opens audio, CV, serial, or the camera. It only reads telemetry JSON and writes advisory profile JSON. The bridge clamps everything on read; the reviewer also clamps on write. Both layers being defensive is intentional.

## Two layers of evolution

### Layer 1: bandit / genetic-ish (automatic)

`decide` classifies the recent window into one of the seed families (sparse / dense / wake / corrective / rest / balanced), then gaussian-jitters the seed's numeric params within schema bounds before writing. Over time the `score` events in history form a fitness signal that an extended reviewer can use to bias parent selection.

This layer is safe to run from a cron with no agent. It will never produce an out-of-bounds profile and will never repeat the same exact profile twice.

### Layer 2: agent-driven aesthetic arc (Lisbon-flavor)

`agent-brief` emits a structured JSON brief: room state, recent history, fitness by family, last profile, last score, available seed families, and the schema bounds. A cron job hands this brief to me (the agent). I read it, decide what the room needs aesthetically — hold / mutate / surprise / rest — and emit a profile JSON that gets written via `apply-profile`.

This layer holds the **arc memory** across the install. Same schema, same clamps, but the choice of family and the choice of "now is the time for a surprise" comes from a composer, not a classifier.

## Fitness function (v1)

Implemented in `profile_scorer.score_window`. Single float in roughly `[-1.0, +1.0]`:

```
+ breath      variance in CV response over the window (system is alive)
+ listening   correlation between person movement and CV/lights response
- dead        people present, CV response variance near zero
- overshoot   strobe/brightness pinned at ceiling for a meaningful fraction
- stuck       same mode_bias persisting past `stuck_seconds`
```

Negative score → reviewer should consider mutating or swapping. Positive → hold or mutate gently.

This is debatable on purpose. The function is the place to put aesthetic priors as the install runs.

## Usage

```bash
# One-shot deterministic decision (cron-friendly):
audio/run_reflective_reviewer.sh decide

# Emit a brief for the agent path:
audio/run_reflective_reviewer.sh agent-brief > /tmp/brief.json

# Write a profile that an agent constructed:
audio/run_reflective_reviewer.sh apply-profile --from-file /tmp/new_profile.json

# Score the current window without writing anything:
audio/run_reflective_reviewer.sh score --print-only
```

## Cron suggestions

| Tick | Job | Why |
|---|---|---|
| every 7–10 min | agent path: `agent-brief` → me → `apply-profile` | aesthetic arc with surprise |
| between agent ticks | `decide` (deterministic) | safety net if agent fails |
| every 5 min | `profile_scorer.py` | adds fitness to history |

The deterministic path is the floor. The agent path is the ceiling. If the agent goes silent or returns malformed JSON, the deterministic path continues to keep the room alive.

## Safety guarantees

- Atomic writes (`*.tmp` then `rename`).
- `expires_at` stamp on every profile; the bridge ignores stale profiles.
- `schema_bounds` clamped on write **and** on read.
- Every write logged to `profile_history.jsonl` with reason.
- A human kill switch remains: delete `heuristic_profile.json`, fall back to bridge defaults.

## Known limits / future work

- The scorer samples the live status file via polling. It does not require any bridge changes today. If we want per-frame fidelity later, add a 1–4Hz append-only `status_history.jsonl` writer to the bridge.
- Layer-1 mutation currently has no per-family fitness bias yet — it jitters the seed of whichever family the classifier picked. The data needed to enable bandit selection is already in history (`recent_fitness_by_family`).
- No reward shaping for "deliberate rest after a busy stretch" yet; the agent path covers this for now.
- No anti-repetition penalty across consecutive `apply-profile` writes; the agent prompt asks for it explicitly.
