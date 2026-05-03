# Pixel HR Office MVP

A terminal UI application simulating an AI-staffed HR office. Animated pixel-art agents move around an ASCII office map, routing tasks through a LangGraph multi-agent pipeline — powered by Claude (Haiku/Sonnet) with ChromaDB vector memory and SQLite relational storage.

## Quick Start

### Requirements

- Python 3.10+
- `pip install -r requirements.txt`
- `ANTHROPIC_API_KEY` — optional; app runs in **mock mode** without it

### Run

```bash
python app.py
```

Without an API key the app starts in mock mode with pre-written agent responses — fully functional for demos.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    Textual TUI (app.py)                      │
│                                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ office_map  │  │  AgentSprite │  │    HUD / Log       │  │
│  │ (ASCII art) │  │ (animated)   │  │ tokens · cost · AI │  │
│  └─────────────┘  └──────────────┘  └────────────────────┘  │
└──────────────────────────┬───────────────────────────────────┘
                           │ run_worker(thread=True)
                           ▼
┌──────────────────────────────────────────────────────────────┐
│             LangGraph StateGraph (office_graph.py)           │
│                                                              │
│  Orchestrator ──► Accountant   (cost optimise)               │
│              ──► Librarian     (RAG policy search)           │
│              ──► Recruiter     (team assembly)               │
│              ──► CommsExpert → QA_Critic  (LinkedIn)         │
│              ──► Tester        (test scenarios)              │
│              ──► Analyst       (data / metrics)              │
└──────────┬───────────────────────────────────┬───────────────┘
           │                                   │
           ▼                                   ▼
┌────────────────────┐             ┌────────────────────────┐
│   SQLite (db/)     │             │   ChromaDB (db/)       │
│  agent_skills      │             │   hr_policies          │
│  task_history      │             │   content_history      │
│  scheduled_tasks   │             │   persona_templates    │
│  pending_results   │             └────────────────────────┘
└────────────────────┘
```

### Token flow

Every API call goes through `TokenAccountant`:

1. **Compress** — strip excess whitespace from prompt
2. **Route** — Haiku for cheap tasks (format/translate/classify), Sonnet for complex
3. **Cache** — `cache_control: ephemeral` on system prompts
4. **Retry** — exponential backoff on RateLimitError / 5xx (up to 3 attempts)
5. **Budget** — raises `BudgetExceededError` when `daily_budget_usd` is exceeded

---

## Key Bindings

| Key | Action |
|-----|--------|
| `T` | New task (modal — choose agent + write task) |
| `O` | Optimise tokens (Accountant analyses recent usage) |
| `R` | Recruit team (Recruiter assembles optimal roster) |
| `N` | Night watch (runs all 4 scheduled background tasks) |
| `C` | Switch office context (HR_Office / Software_House / Startup) |
| `F` | Give feedback on last result → triggers `improve_skill` |
| `S` | Show all agent skill levels in the log |
| `H` | Task history modal (export TXT / JSON / CSV) |
| `1`–`4` | Focus agent 1–4 (logs current zone + skill) |
| `Q` | Quit |

---

## Agents

| Agent | Emoji | Home Zone | Speciality |
|-------|-------|-----------|------------|
| Orchestrator | 🤖 | HRBP Desk | Routes tasks to specialists |
| Accountant | 💰 | Vault | Token cost analysis & optimisation |
| Librarian | 📚 | Archive | RAG-powered HR policy research |
| Recruiter | 👥 | HR Hall | Team assembly & agent deployment |
| CommsExpert | 🔗 | HR Hall | LinkedIn content creation |
| QA_Critic | 🔬 | Archive | Content quality review (PASS/FAIL) |
| Tester | 🐞 | Server Room | Test scenario generation (BDD/TC) |
| Analyst | 📊 | Archive | Data analysis & KPI insights |

---

## Office Contexts

Switch with `C` key:

| Context | Icon | Focus |
|---------|------|-------|
| `HR_Office` | 🏢 | Standard HR department (default) |
| `Software_House` | 💻 | Tech company — dev-centric operations |
| `Startup` | 🚀 | Lean startup — generalist agents, fast iteration |

Each context loads a different agent roster with context-specific system prompts.

---

## Configuration

Copy `config.toml` → `config.local.toml` (gitignored) and override:

```toml
[api]
anthropic_api_key = "sk-ant-..."
daily_budget_usd  = 5.0

[app]
default_context = "HR_Office"
demo_interval   = 5.0          # seconds between demo sprite moves

[db]
sqlite_path = "pixel_hr.db"
chroma_path = "./chroma_db"

[limits]
max_tokens_short  = 160
max_tokens_medium = 256
max_tokens_long   = 350
```

Environment variable `ANTHROPIC_API_KEY` takes priority over `config.local.toml`.

---

## Night Watch (Headless)

Run scheduled tasks without the TUI:

```bash
python headless.py --run         # run all 4 nightly tasks once
python headless.py --daemon      # background daemon (schedule library)
python headless.py --list-tasks  # list scheduled tasks from SQLite
python headless.py --time 08:00  # override scheduled run time
```

Results are stored in `pending_results` and shown as a banner on next `app.py` launch.

---

## Self-Improving Loop

Press `F` after any task to give feedback. The app:

1. Sends your feedback + the agent's last output to a Critic (Haiku)
2. Critic returns a one-sentence improvement instruction
3. Instruction is persisted as `system_prompt_override` in SQLite
4. Agent's `skill_level` increments (capped at 1.0)
5. All future tasks for that agent use the improved prompt

---

## Running Tests

```bash
python -m unittest discover tests/
```

91 tests total. Tests that require optional dependencies (`pydantic`, `chromadb`) are skipped gracefully with an install hint.

---

## File Layout

```
myprojects/
├── app.py                    # Textual App entry point
├── headless.py               # Night Watch CLI runner
├── config.toml               # Default configuration
├── requirements.txt
├── engine/
│   ├── agents.py             # TokenAccountant, AgentState, improve_skill
│   ├── config.py             # Config loader (TOML + env vars)
│   ├── contexts.py           # Office context definitions
│   └── office_graph.py       # LangGraph StateGraph (8 nodes)
├── ui/
│   ├── dialogs.py            # Modal screens (task, feedback, context)
│   ├── history_screen.py     # Task history + TXT/JSON/CSV export
│   ├── office_map.py         # ASCII map + zone highlighting
│   ├── speech_bubble.py      # Floating speech bubble widget
│   └── sprites.py            # AgentSprite animated widget
├── db/
│   └── memory.py             # SQLite + ChromaDB helpers
└── tests/
    ├── test_agents.py
    ├── test_config.py
    ├── test_db.py
    └── test_graph_routing.py
```
