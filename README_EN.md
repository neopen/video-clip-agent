# PenClip — AI Video Mix Clipping Agent

An AI video mix clipping system built on a **star-hub dispatch architecture**. It drives video analysis, segment matching, and automatic composition from natural language, delivering a "human-in-the-loop" creative experience through multi-agent collaboration — AI assists rather than replaces the creator.

## Architecture Overview

PenClip follows a **DDD layered architecture** with a **star-hub dispatch pattern** at the top (`CentralHub` handles command parsing → intent recognition → capability routing → agent dispatch). The first registered standard workflow is a **linear chain** (sampling → parsing → analysis → matching → composition).

```
User input → CentralHub → [intent recognition → risk assessment → capability routing] → Agent execution → state update → user feedback
```

Layered structure (dependency direction: outer → inner, inner has zero reverse dependencies):

| Layer | Directory | Responsibility |
| :-- | :-- | :-- |
| Domain | `domain/` | Entities (Pydantic) + value objects (dataclass/enum) + repository interfaces |
| Application | `core/` | Hub dispatch / orchestration / state / event bus |
| Agents | `agents/` | `BaseAgent` + Planner/Asset/Analyzer/Matcher/Composer/State |
| Services | `services/` | Scene splitting / FFmpeg / file parsing are live; LLM and CLIP vector search land in V0.2 |
| Infrastructure | `infrastructure/` | PostgreSQL/MinIO/Redis repositories and caches (in-memory fakes in V0.1) |
| Interface | `api/` + `cli/` | REST v1 / middleware / WebSocket / CLI |

**Current version**: V0.1 (composition loop closed) — register assets → scene analysis → slot planning → tag matching → concat composition runs end to end over both the console and REST; `LangGraph` orchestration, `infrastructure/` and semantic vector matching remain V0.2 stubs. See [Roadmap](#roadmap).

## Core Features

- **Interactive console (REPL)**: real-time human-in-the-loop — clarification dialogue, progressive refinement, and confirmation gates for high-risk operations
- **Star-hub dispatch**: command parsing → intent recognition (30 intents) → risk assessment → capability routing
- **Capability registration**: extend functionality by subclassing `BaseAgent` and declaring capabilities — no hub code changes required
- **Multiple AI providers**: OpenAI / Qwen / DeepSeek / Ollama (local models)
- **Video processing**: adaptive scene splitting + visual-statistics tagging → tag-based matching → FFmpeg concat composition; speech-recognition / emotion / object-detection tools exist but are not yet wired into agents
- **Structured logging**: leveled logs + JSON format + file rotation

## Quick Start

### Requirements

- Python 3.9+
- FFmpeg (on system PATH, or auto-detected by the project)

### Installation

```bash
git clone https://github.com/neopen/video-clip-agent.git
cd video-clip-agent

# Create a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate.bat
# Linux / macOS
source .venv/bin/activate

# Install dependencies (the project ships pyproject.toml only — there is no requirements.txt)
pip install -e .
```

> For development, install everything at once: `pip install -e ".[dev]"`

### Configure an AI Provider

Copy `.env.example` to `.env` and fill in your provider of choice:

```ini
# Provider: openai | qwen | deepseek | ollama
AI_PROVIDER=qwen

# Qwen (DashScope compatible mode)
QWEN_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxx
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus
```

Environment variables per provider:

| Provider | Environment variables |
| :-- | :-- |
| OpenAI | `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` |
| Qwen | `QWEN_API_KEY` / `QWEN_BASE_URL` / `QWEN_MODEL` |
| DeepSeek | `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` |
| Ollama | `OLLAMA_BASE_URL` / `OLLAMA_MODEL` |

Configuration uses a **dual channel**: `config.json` (local user overrides) + `.env` (environment variables, higher priority).

### Start the Server

```bash
python main.py            # default http://localhost:8000
python main.py --port 8080
python main.py --host 0.0.0.0 --port 8000   # production (multi-process needs Redis)
```

Once started, the interactive API docs are at http://localhost:8000/docs.

### Start the Interactive Console (primary usage)

PenClip uses the **interactive console** as its primary interface (REST async is only a fallback):

```bash
# Interactive console (requires: pip install -e .)
penclip-cli                       # auto-generated session
penclip-cli --session my-vlog     # specify a session ID

# Or via module (development)
python -m penclip.cli.main
```

The console supports three interaction modes (one-shot commands / clarification dialogue / progressive refinement) plus confirmation gates for high-risk operations:

```
penclip> E:\videos\travel_01.mp4
[OK] 已添加素材: travel_01.mp4          # asset registered

penclip> 做一个旅行 Vlog，风景放开头，美食放中间
确认根据此需求创建新的时间线规划？
Confirm? [y/N] y
[OK] 创建时间线：3 个片段槽位，共 3    # timeline planned

penclip> 分析素材
[OK] 已分析 3 个素材，共 12 个片段      # scene detection + tagging

penclip> 匹配片段
[OK] 已匹配 3/3 个槽位                  # slots filled

penclip> 合成
确认开始最终渲染？渲染开始后中途取消可能导致不完整输出。
Confirm? [y/N] y
[OK] 已合成 3 个片段 → data\output\composed_output.mp4

penclip> 撤销
[OK] 已撤销：匹配片段

penclip> pipeline        # one-shot analyze → match → compose (render gate kept)
```

> Messages are emitted in Chinese; the console currently accepts Chinese and English keywords. See the [console usage guide](docs/视频混剪智能体-控制台使用指南.md) (Chinese) for a full transcript.

## API Reference

### Available Endpoints

System (`index_api.py`):

| Method | Path | Description |
| :-- | :-- | :-- |
| GET | `/` | Service info |
| GET | `/health` | Health check |

Domain routes (`api/v1/`, prefix `/api/v1`):

| Method | Path | Description |
| :-- | :-- | :-- |
| POST | `/api/v1/sessions` | Create a session (optional custom `session_id`) |
| GET | `/api/v1/sessions/{session_id}` | Session overview: phase / assets / slots / matched_slots / undo_depth |
| DELETE | `/api/v1/sessions/{session_id}` | Delete a session |
| POST | `/api/v1/tasks` | Submit a natural-language instruction (async, returns task_id) |
| GET | `/api/v1/tasks/{task_id}` | Get task status |
| GET | `/api/v1/tasks/{task_id}/result` | Get task result (incl. `needs_confirmation`, `suggestions`) |
| DELETE | `/api/v1/tasks/{task_id}` | Cancel a task |
| POST | `/api/v1/tasks/sessions/{session_id}/confirm` | Release a gated high-risk instruction and resume it |
| POST | `/api/v1/tasks/sessions/{session_id}/cancel` | Abandon a gated instruction (session state untouched) |
| * | `/api/v1/{assets,timelines,exports,webhooks}/…` | V0.1 placeholders returning `501` — use `/api/v1/tasks` instead |

### Usage Example

```bash
# Health check
curl http://localhost:8000/health

# Create a session, then submit an instruction (async)
SESSION=$(curl -s -X POST http://localhost:8000/api/v1/sessions | jq -r .session_id)
curl -s -X POST http://localhost:8000/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d "{\"user_input\": \"做个混剪：红色开头，绿色中间，蓝色结尾\", \"session_id\": \"$SESSION\"}"
# → {"task_id": "...", "session_id": "...", "status": "pending"}

# Poll the result; high-risk instructions stop at the confirmation gate
curl -s http://localhost:8000/api/v1/tasks/{task_id}/result
# → {"needs_confirmation": true, "confirmation_message": "..."}

# Confirm to resume (returns a new task_id to poll)
curl -s -X POST http://localhost:8000/api/v1/tasks/sessions/$SESSION/confirm
```

> Interactive API docs: http://localhost:8000/docs. The REST async API is a **fallback**; for the primary interaction experience use the [interactive console](docs/视频混剪智能体-控制台使用指南.md).

## Directory Structure

See [`.claude/skills/project.md`](.claude/skills/project.md) for the full structure; brief overview:

```
src/penclip/
├── domain/          # Domain layer: entities / value_objects / repositories (zero deps)
├── core/            # Application layer: hub / orchestration / state / event
├── agents/          # Agents: BaseAgent + Planner/Asset/Analyzer/Matcher/Composer/State
├── services/        # Services: scene_detect / ffmpeg / file bridged; llm / clip / vector pending
├── infrastructure/  # Infrastructure: persistence / cache / messaging
├── api/             # Interface: v1 / task_backend(neotask) / middleware / websocket / schemas
├── cli/             # CLI (penclip-cli console)
├── plugins/         # Plugin system + Docker sandbox
├── hub/ graph/ state/   # ⚠️ Bridge compatibility layer (points to core/, domain/)
├── llm/             # Legacy: multi AI provider clients
├── tools/           # Legacy: 6 video analysis tools
└── utils/ config/ logger.py   # Legacy: utilities / config / logging
```

## Tech Stack

- **Language**: Python 3.9+
- **Web**: FastAPI + uvicorn (async, auto OpenAPI docs)
- **AI**: OpenAI / Qwen / DeepSeek / Ollama; LangGraph 1.x + Checkpoint are declared dependencies, but V0.1 orchestration is still a pass-through stub
- **Video**: FFmpeg, OpenCV (custom adaptive scene splitting), PyDub; SpeechRecognition is available but not yet wired into agents
- **Data**: NumPy, Pandas, Scikit-learn
- **Queue/Cache**: Redis (multi-process mode)
- **Code quality**: ruff, black, mypy, pytest, pre-commit

## Roadmap

| Version | Codename | Core goal | Status |
| :-- | :-- | :-- | :-- |
| V0.1 | Composition loop | DDD layers + keyword hub dispatch + end-to-end rendering over console **and** REST | **Current** |
| V0.2 | Semantic understanding | LLM intent parsing + real LangGraph orchestration + SQLite state | Planned |
| V0.3 | Visual collaboration | Web UI + multi-agent collaboration + formalized capability registration | Planned |
| V1.0 | Production-ready | Enterprise capabilities (auth/rate-limit/Postgres/MinIO/K8s) | Future |
| V2.0 | Open ecosystem | Plugin marketplace + Docker sandbox | Future |

## Development

```bash
# Code formatting
black src/ tests/

# Lint check and auto-fix
ruff check src/ tests/
ruff check --fix src/ tests/

# Type checking
mypy src/penclip

# Run tests
pytest

# Git hooks (pre-commit checks)
pre-commit install
```

## Documentation

| Document | Description |
| :-- | :-- |
| [Console usage guide](docs/视频混剪智能体-控制台使用指南.md) | Full interactive console (REPL) usage (Chinese) |
| [Quick start](docs/视频混剪智能体-快速开始.md) | Illustrated from-zero-to-running guide (Chinese) |
| [Project summary](docs/视频混剪智能体-项目总结.md) | Design philosophy and core contracts — condenses the original architecture / roadmap / principles / overview docs (Chinese) |
| [AI development overview](docs/AI开发导向-项目总览.md) | Project overview from an AI developer's perspective (Chinese) |
| [Project skills](.claude/skills/SKILL.md) | Claude Code skills index (Chinese) |

## License

[MIT](LICENSE)
