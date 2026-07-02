# Config Optimization Orchestration Plan

Standalone plan for an **extensible control plane** (main server + web UI) and a **pool of benchmark subsystems** (1..N workers) that find the **best config candidates** for a genomic window `w = chr{n}:{x}-{y}`.

**Implementation home:** [`Main/`](../Main/) — **Effortless** control plane (FastAPI + React).

**Current scope (shipped):** history-driven **base candidate finder**, **round_history** DB, **worker registry UI**, and **read-only Minos platform round polling** (window + countdown). **Not shipped yet:** optimization runs that complete, job dispatch to workers, trial streaming, export, policies UI.

---

## Implementation status (Effortless — as of current code)

| Area | Status | Notes |
|------|--------|-------|
| **Candidate finder** | Done | `POST /api/v1/candidates/find` + UI cards with conf tooltip |
| **History store** | Done | SQLite `round_history`; import from Minos `round_history.json` |
| **Platform round** | Done | Poll Minos API; hero UI + WebSocket push; drives default `w` |
| **Worker registry** | Partial | UI register (name, health URL, main API); no worker agent process |
| **Optimization runs** | Skeleton | `POST /runs` creates run + pending jobs; no dispatch, no winner |
| **Jobs / trials** | Skeleton | DB models + read APIs; trials empty unless manually filled |
| **Policies** | Stub | In-memory GATK default only; not persisted |
| **Export / Results UI** | Not started | No `/runs/{id}/export`, no ranked-results page |
| **Auth** | Not started | Local dev only |

**Working today:** platform round → find K base configs from history → browse history → register workers (metadata + health probe).

**Not working yet:** start optimization → workers run search → ranked candidates → export / save winner from UI.

See [`Main/README.md`](../Main/README.md) (Effortless) for run commands and env vars.

---

## 1. Terminology

| Symbol | Name | Definition |
|--------|------|------------|
| `w` | **chromosome / window** | Genomic region string: `chr{n}:{x}-{y}` |
| `n` | **chromosome id** | `1`–`22`, `X`, `Y`, `M` |
| `x`, `y` | **coordinates** | Start and end base positions |
| `conf` | **tool config** | Quality hyperparameters for a variant caller (GATK `gatk_options`) |
| `s` | **score** | Local benchmark score in `[0, 1]` (hap.py + AdvancedScorer) |
| `tool` | **caller** | `gatk`, `deepvariant`, or `bcftools` (phase 1: `gatk`) |

**History record:**

```
H = (w, conf, s, meta)
```

**Subsystem (worker):** any registered machine that runs a `tool` optimizer plugin.

**Deliverable (per round — planned):**

```
C = [ (conf₁, s₁), (conf₂, s₂), … ]   # ranked best config candidates
```

**Deliverable (today — candidate finder only):**

```
B = [ (conf₁, s₁), … ]   # K base configs from history (no worker search yet)
```

---

## 2. Goals

### Shipped (Effortless v0.1)

1. Given a window `w`, select **K base configs** from history (`K` configurable, default `2`).
2. Persist and browse `(w, conf, s)` in SQLite; bootstrap from past Minos tuning JSON.
3. Show **active platform round** (region, phase, countdown) to align `w` with live rounds.
4. **Register workers** via web UI (health + main API URLs).

### Planned (full orchestration)

1. Dispatch parallel optimization jobs to **N registered workers**.
2. Return **ranked best config candidates** `C` (winner + runners-up + trial leaders).
3. Write-back every new `(w, conf, s)` from local benchmarks to history.
4. **Control the entire system from a web console** — runs, jobs, policies, exports.

**Primary output (full system — not yet returned by runs):**

| Output | Description |
|--------|-------------|
| `winner_conf` | Single best config across all workers/trials |
| `ranked_candidates` | Top-M configs with scores (default M=5) |
| `per_job_results` | Best conf per worker/candidate branch |
| `trial_log` | Full search trace for analysis |

**Design principles:**

| Principle | Meaning |
|-----------|---------|
| **Standalone optimization** | No dependency on live miner submission or chain for benchmark search |
| **Read-only platform hook** | Optional poll of Minos round status for `w` only (no auto-submit) |
| **Extensible workers** | Add/remove VMs via web UI registration |
| **Extensible tools** | GATK first; more callers via plugins |
| **Extensible search** | Grid, random, Optuna — per policy |
| **Observable** | Full visibility in web UI + API |

**Non-goals:**

- Automatic config push to `neurons/miner.py` or live subnet submission.
- Full RL training pipeline.
- Public multi-tenant SaaS (single-operator first).

---

## 3. High-Level Architecture

### 3.1 Current (Effortless — implemented)

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    EFFORTLESS CONTROL PLANE (Main Server)                       │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐  ┌────────────┐  │
│  │  Web UI     │  │  REST API    │  │  SQLite (main.db)│  │ Platform   │  │
│  │  ConsolePage│◄─┤  FastAPI     │◄─┤  round_history   │  │ poller     │  │
│  │  (React)    │  │  + WS        │  │  workers, runs   │  │ (read-only)│  │
│  └─────────────┘  └──────┬───────┘  └─────────────────┘  └─────┬──────┘  │
│                          │                                      │         │
│              ┌───────────┴──────────────────┐                   │         │
│              │  Candidate finder engine      │                   │         │
│              │  • parse w → (n,x,y)          │                   ▼         │
│              │  • tool + chromosome filter     │         api.theminos.ai    │
│              │  • coordinate similarity        │         round-status       │
│              │  • top-K by historical score    │                          │
│              └───────────────────────────────┘                          │
│              ┌───────────────────────────────┐                          │
│              │  Orchestrator (skeleton)       │  ← creates runs/jobs only  │
│              └───────────────────────────────┘                          │
└──────────────────────────────────────────────────────────────────────────┘

Workers: registry only (no agent process connected yet)
```

**Stack (current):** FastAPI + SQLite (`aiosqlite`) + React (Vite). No Redis. WebSocket pushes **platform round** updates only.

### 3.2 Target (full orchestration — planned)

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         CONTROL PLANE (Main Server)                       │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────┐  ┌─────────────────┐  │
│  │  Web UI     │  │  REST API    │  │  Job Queue │  │  History DB     │  │
│  │  (React)    │◄─┤  (FastAPI)   │◄─┤  Redis /   │  │  PostgreSQL     │  │
│  └─────────────┘  └──────┬───────┘  │  in-proc   │  └─────────────────┘  │
│                          │           └─────┬──────┘                       │
│              ┌───────────┴─────────────────┴───────────┐                  │
│              │  Orchestrator                            │                  │
│              │  • history lookup + K base candidates      │                  │
│              │  • fan-out jobs to worker pool             │                  │
│              │  • rank all trials → ranked_candidates C   │                  │
│              │  • write-back (w, conf, s) to history      │                  │
│              └───────────┬─────────────────────────────────┘                  │
└──────────────────────────┼──────────────────────────────────────────────────┘
                           ▼
                    Worker 1 … Worker N  (optimizer plugins)
                           ▼
              ranked config candidates C → export JSON / gatk.conf / CSV
```

---

## 4. Components

### 4.1 Control Plane (Main Server)

| Module | Responsibility | Status |
|--------|----------------|--------|
| **API** | REST + WebSocket | Partial — see §8 |
| **Candidate finder** | History query + coordinate similarity + top-K by score | **Done** |
| **Selector** | Parse `w`, coordinate similarity | **Done** (`app/selector.py`) |
| **History store** | `(w, conf, s)` CRUD + JSON import | **Done** |
| **Platform poller** | Cache Minos round status for UI | **Done** |
| **Registry** | Worker registration, heartbeat API | Partial — register + probe health URL |
| **Orchestrator** | Select bases → schedule jobs → rank results | Skeleton — bases only at run create |
| **Scheduler** | Assign jobs to healthy workers | Not started |
| **Policy engine** | `K`, `M`, search budget, tool, timeouts | In-memory stub |
| **Exporter** | Download ranked candidates | Not started |

### 4.2 Web Console

#### Current UI (`Main/frontend` — Effortless console, single `ConsolePage`)

| Section | Purpose | API |
|---------|---------|-----|
| **Round** (`#round`) | Active platform window, phase countdown, schedule & metadata | `GET /platform/round`, WS |
| **Candidates** (`#candidates`) | Find K base configs; editable `w`; worker list | `POST /candidates/find`, `GET /workers` |
| **History** (`#history`) | Browse `(w, conf, s)`; Sync JSON import | `GET /history`, `POST /history/import` |
| **Top bar** | Add worker modal (name, health URL, main API) | `POST /workers/register` |

Nav: Round | Candidates | History.

#### Planned pages (not built)

| Page | Purpose |
|------|---------|
| **Dashboard** | Active run, job progress, current best score |
| **New Run** | Submit `w`, BAM path, tool, `K`, `max_workers`, deadline |
| **Results** | Ranked config candidates — compare, diff, export |
| **Jobs** | Per-worker jobs, trials, logs |
| **Policies** | `K`, `M`, param bounds, search method, similarity weights |
| **Settings** | Benchmark asset paths, auth, notifications |

#### Candidate finder UI (shipped)

- Window defaults from **platform round** `region`; **Edit** toggles manual override.
- **Find N candidates** → result **cards**: chromosome, score %, source window, **Conf** tooltip (flattened params).
- History sidebar filters by chromosome after a find.

#### Results page (planned — core deliverable)

```
┌─────────────────────────────────────────────────────────────────┐
│  w: chr20:10000000-15000000          Status: DONE               │
├──────┬──────────┬─────────────────────────────────┬─────────────┤
│ Rank │ Score    │ Key params                      │ Source      │
├──────┼──────────┼─────────────────────────────────┼─────────────┤
│  1   │ 0.831    │ pcr=NONE, conf=27.5, bq=10      │ worker-2    │
│  2   │ 0.824    │ pcr=NONE, conf=30.0, bq=12      │ worker-1    │
└──────┴──────────┴─────────────────────────────────┴─────────────┘
│  [Export winner]  [Export top-5 JSON]  [Copy gatk.conf]          │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 Worker Registry

Workers are registered via **Add worker** in the top bar.

**Table: `workers` (SQLite — implemented)**

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | |
| `name` | TEXT | unique, e.g. `optimizer-1` |
| `health_url` | TEXT | probed on register (`GET`, must be < 400) |
| `base_url` | TEXT | main worker API (push model — not used yet) |
| `status` | ENUM | `online` \| `offline` \| `draining` \| `disabled` |
| `capabilities` | JSON | tools, search methods, `max_parallel` |
| `tags` | JSON array | placement hints |
| `last_heartbeat` | TIMESTAMPTZ | set by `POST /workers/{id}/heartbeat` |
| `version` | TEXT | optional, from heartbeat |

**Registration (current):** UI → `POST /api/v1/workers/register` → returns one-time `registration_token` (not persisted server-side yet).

**Registration (planned):** VM runs `python -m optimizer.worker --register <url> --token <token>` and sends heartbeats.

### 4.4 Optimizer Plugins (planned)

```python
class OptimizerPlugin(Protocol):
    tool: str
    def get_param_schema(self) -> dict: ...
    def get_important_params(self) -> list[str]: ...
    def run_trial(self, w, conf, assets) -> TrialResult: ...
    def search(self, w, base_conf, policy) -> OptimizeResult: ...
```

| Plugin | Phase |
|--------|-------|
| `gatk` | 1 — `templates/gatk.py` + param schema |
| `deepvariant` | 2 |
| `bcftools` | 3 |

### 4.5 History Database

**Table: `round_history` (implemented)**

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | |
| `chromosome` | TEXT | `chr20` |
| `start` / `end` | BIGINT | `x`, `y` |
| `window` | TEXT | `chr{n}:{x}-{y}` |
| `tool` | TEXT | |
| `conf` | JSON | |
| `score` | FLOAT | local `s` |
| `source_key` | TEXT | dedup key for JSON import |
| `run_id` | TEXT | optional FK to optimization run |
| `worker_id` | UUID | optional FK |
| `created_at` | TIMESTAMPTZ | |

**Import:** `MAIN_HISTORY_JSON_PATHS` — Minos tuning `round_history.json` files; auto-import on first startup if table empty.

**Tables: `optimization_runs`, `optimization_jobs` (schema only — runs do not complete)**

Same shape as original plan; `winner_conf`, `ranked_candidates`, and job `trials` remain empty until orchestration is built.

---

## 5. Candidate Selection Algorithm

**Implemented** in `Main/backend/app/engine/candidate_finder.py` and exposed as `POST /api/v1/candidates/find`.

Policy `k_candidates` (default `K=2`). `min_similarity` default `0.2`.

### 5.1 Parse window

Validate region format via `templates/tool_params.validate_region` (`app/selector.py`).

### 5.2 Filter by tool + chromosome

Load up to 500 rows from `round_history` where `tool` matches and `chromosome` equals parsed `n`.

### 5.3 Coordinate similarity

Compute similarity between query window and each history row (`coordinate_similarity` in selector). Keep rows with `similarity >= min_similarity`.

**Fallback:** if none pass, take top **15** history rows on that chromosome by similarity (still ranked by score among the pool).

### 5.4 Select K base configs (implemented)

Among the similar pool, sort by historical **score descending**, take top **K**.

If history is empty, return a single **default conf** (`app/defaults.py` — GATK stock options).

### 5.5–5.6 Fan-out and final ranking (planned)

Not implemented. Planned: diversity pick (`param_distance > τ`), worker fan-out, merge trials → `ranked_candidates`.

---

## 6. Important Parameters (GATK — phase 1)

| Parameter | Range | Step |
|-----------|-------|------|
| `pcr_indel_model` | `{NONE, CONSERVATIVE}` | enum |
| `standard_min_confidence_threshold_for_calling` | 20 – 40 | 2.5 |
| `min_base_quality_score` | 8 – 18 | 2 |
| `min_mapping_quality_score` | 15 – 30 | 5 |

Default when no history: see `Main/backend/app/defaults.py`.

---

## 7. Worker — Local Benchmark Flow (planned)

```
1. Pull job from control plane
2. Load plugin (gatk)
3. Resolve assets for w from local benchmark store
4. search(base_conf, policy) → trials[]
5. Stream trial events; POST complete with best_conf + all trials
```

Benchmark asset table and proxy metrics unchanged from original plan — required before workers can run.

---

## 8. API Contracts

Prefix: `/api/v1` (`MAIN_API_PREFIX`).

### 8.1 Implemented

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness |
| `POST` | `/candidates/find` | **K base configs** from history (no run created) |
| `GET` | `/history` | List history (`?chromosome=`, `?limit=`) |
| `GET` | `/history/count` | Row count |
| `POST` | `/history` | Insert scored row |
| `POST` | `/history/import` | Bulk import from JSON paths |
| `POST` | `/history/from-run/{run_id}` | Save run winner (when winner exists) |
| `GET` | `/platform/round` | Cached platform round |
| `POST` | `/platform/round/refresh` | Force poll |
| `GET` | `/workers` | List workers |
| `POST` | `/workers/register` | Register worker + health probe |
| `PATCH` | `/workers/{id}` | Update status |
| `POST` | `/workers/{id}/heartbeat` | Mark online |
| `POST` | `/runs` | Create run + base candidates + pending jobs (skeleton) |
| `GET` | `/runs`, `/runs/{id}` | Run detail |
| `POST` | `/runs/{id}/cancel` | Cancel |
| `GET` | `/jobs`, `/jobs/{id}/trials` | Job list / trials |
| `GET/PUT` | `/policies/{tool}` | In-memory policy stub |
| `WS` | `/ws` | Platform round push (not trial events) |

**`POST /api/v1/candidates/find` (primary UI flow today)**

```json
{
  "window": "chr20:10000000-15000000",
  "tool": "gatk",
  "k_candidates": 2,
  "min_similarity": 0.2
}
```

Response includes `candidates[]` with `base_conf`, `history_score`, `similarity`, `source_window`, and flags `used_default`, `coordinate_matched`, etc.

**`POST /api/v1/workers/register`**

```json
{
  "name": "optimizer-1",
  "health_url": "http://192.168.1.10:8080/health",
  "base_url": "http://192.168.1.10:8080"
}
```

### 8.2 Planned (not implemented)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/runs/{id}/export` | JSON / conf / CSV export |
| Worker push/pull | `{base_url}/optimize` or `/workers/{id}/jobs/next` | Job execution |

Full run request/response shapes remain as in original plan for when orchestration is completed.

---

## 9. End-to-End Workflow

### Today (candidate finder)

1. Backend starts → import history JSON if DB empty → start platform poller.
2. UI shows active round region + countdown.
3. User finds **K base configs** for `w` (round default or edited).
4. User browses history; optionally registers workers (metadata only).

### Target (full optimization)

1. User starts run for `w` with `K`, `max_workers`, asset paths.
2. Orchestrator selects bases → scheduler dispatches jobs to online workers.
3. Workers run search → trials stream over WS.
4. Orchestrator ranks trials → `ranked_candidates`, `winner_conf`.
5. User exports or saves winner to history.

---

## 10. Repository Layout

```
minos_subnet/
├── Main/                           # ← Effortless control plane (source tree)
│   ├── backend/
│   │   ├── app/main.py
│   │   ├── app/engine/candidate_finder.py
│   │   ├── app/services/
│   │   │   ├── candidate_finder.py
│   │   │   ├── history_store.py
│   │   │   ├── history_import.py
│   │   │   └── platform_round.py
│   │   ├── app/orchestrator.py     # skeleton
│   │   └── app/api/                # candidates, history, workers, runs, …
│   └── frontend/
│       └── src/pages/ConsolePage.tsx
├── docs/config-optimization-plan.md
├── templates/gatk.py               # shared library
├── templates/tool_params.py        # region validation
└── utils/scoring.py, platform_client.py
```

Reuses repo templates/utils as **libraries** — no neuron changes.

---

## 11. Implementation Phases

### Phase 0 — Control plane skeleton

- [x] DB models: `workers`, `round_history`, `optimization_runs`, `optimization_jobs`
- [x] `selector.py` — parse window + coordinate similarity
- [x] Candidate finder engine + `POST /candidates/find`
- [x] History CRUD + JSON import
- [x] `POST /runs`, `GET /runs/{id}` (skeleton — no completion)
- [ ] Basic auth

### Phase 1 — Single worker + GATK plugin

- [ ] `OptimizerPlugin` + `gatk` plugin
- [ ] Worker agent process (register token, heartbeat loop, job loop)
- [ ] Grid search + local hap.py benchmark
- [ ] Trial streaming to control plane

### Phase 2 — Web console MVP

- [x] Single console: round + **candidate finder** + history + workers
- [x] Platform round hero + WebSocket
- [x] Conf tooltip on candidate cards
- [x] Add worker modal + workers panel
- [ ] Dashboard + New Run + **Results** (ranked candidates table)
- [ ] Export JSON / conf / CSV
- [ ] Save winner to history (UI; API exists)
- [ ] WebSocket live trials

### Phase 2b — Platform round (extra, shipped)

- [x] Minos round-status poller (demo + live modes)
- [x] Default `w` from platform `region`

### Phase 3 — Multi-worker + policies

- [ ] Scheduler: dispatch K jobs to N online workers
- [ ] Policies UI + DB persistence
- [ ] Config diff viewer on Results page
- [ ] Persist registration tokens; worker placement rules

### Phase 4 — Extensibility (ongoing)

- [ ] More plugins (`deepvariant`, `bcftools`)
- [ ] Optuna search
- [ ] Worker tags + placement rules
- [ ] Alerts on run complete
- [ ] PostgreSQL / Redis (optional scale-up)

---

## 12. Environment (Effortless)

| Variable | Default | Purpose |
|----------|---------|---------|
| `MAIN_DATABASE_URL` | `sqlite+aiosqlite:///./main.db` | SQLite path |
| `MAIN_CORS_ORIGINS` | `http://localhost:5173` | Vite dev |
| `MAIN_PLATFORM_ENABLED` | `true` | Background poller |
| `MAIN_PLATFORM_DEMO_MODE` | `true` | Demo round-status endpoint |
| `MAIN_PLATFORM_POLL_SECONDS` | `10` | Poll interval |
| `MAIN_HISTORY_JSON_PATHS` | gatk + newgatk tuning JSON | Bootstrap history |

Copy `Main/backend/.env.example` → `.env`.

---

## 13. Extensibility

| Extend | How |
|--------|-----|
| More VMs | **Add worker** in UI (today: registry only) |
| More tools | New `optimizer/plugins/<tool>.py` (planned) |
| More search methods | `search.py` + Policies dropdown (planned) |
| More ranking logic | `orchestrator.py` merge/rank; expose `top_m` in UI |
| More benchmark data | Import history or `POST /history` |

---

## 14. Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Sparse history for some `n` | Default conf + similarity fallback pool (top 15) |
| Worker offline mid-run | Replicate jobs; `min_workers` policy (planned) |
| Platform poll failure | UI shows error; manual **Edit** on window |
| Exposed web console | Auth, HTTPS, private network (planned) |

---

## 15. Success Metrics

| Metric | Target | Today |
|--------|--------|-------|
| Find K bases for `w` | < 1s on imported history | **Met** (local SQLite) |
| Worker register → listed in UI | < 1 min | **Met** (health probe) |
| Run wall-clock (K=2, 12 trials each) | Within timeout | **N/A** — runs not executed |
| Ranked candidates after run | Always `top_m` or all trials | **N/A** |

---

## 16. Open Decisions

1. **Push vs pull jobs** — pull if workers are behind NAT.
2. **Registration token storage** — validate on worker agent connect.
3. **Benchmark store layout** — flat files vs manifest DB per `w`.
4. **Platform integration depth** — today read-only round; keep submission out of scope?

---

## 17. Summary

**Effortless** is the standalone **config candidate finder** control plane: history-informed base selection and a web console are **live**; parallel worker search, ranked output, and export are **planned** on the same DB/API skeleton. Optional **read-only Minos platform polling** supplies the active round window for the UI — no miner or validator coupling for optimization.