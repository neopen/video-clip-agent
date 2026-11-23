---
name: project
description: PenClip 项目知识——DDD 分层架构、目录结构、领域模型、中枢分发流程和版本路线。理解项目上下文或进行架构决策时使用；具体编码和校验规则分别见 code-standards.md 与 validation.md。
type: project
---

# PenClip 项目技能

## 项目定位

PenClip（video-clip-agent）是基于**智能体协作**的视频混剪系统，核心理念「人机协同」。顶层架构为**星型中枢分发模式**（CentralHub 分发），首个注册的工作流为**线性链路节点模式**（采样 → 解析 → 分析 → 匹配 → 合成）。当前版本 **V0.1（DDD 分层 + 出片闭环）**。

## 分层架构

依赖方向：**外层 → 内层**，内层禁止反向依赖外层。

```
接入层   api/(v1 REST · middleware · websocket · schemas) + cli/
应用层   core/(hub · orchestration · state · event) + agents/ + services/
领域层   domain/(entities · value_objects · repositories)     ← 零依赖，最内层
基础设施  infrastructure/(persistence · cache · messaging)     ← 实现领域层仓储接口
```

| 层 | 目录 | 职责 | V0.1 状态 |
| :-- | :-- | :-- | :-- |
| 领域层 | `domain/` | 实体(Pydantic) + 值对象(dataclass/enum) + 仓储接口 | ✅ 完整实现 |
| 应用层 | `core/hub/` | 中枢分发、能力注册、意图识别、风险评估 | ✅ 完整实现 |
| 应用层 | `core/state/` | 状态管理、状态存储、检查点 | ⚠️ 内存版完整，SQLite 待 V0.2 |
| 应用层 | `core/event/` | 事件总线、事件类型 | ✅ 完整实现 |
| 应用层 | `core/orchestration/` | 工作流编排、图引擎 | ⚠️ `WorkflowOrchestrator`/`GraphFactory` 真实按节点执行；`LangGraphEngine` 仍为直通 stub |
| 智能体 | `agents/` | BaseAgent + 6 个核心 Agent（Planner/Asset/Analyzer/Matcher/Composer/State）+ PluginAgent | ✅ 出片闭环（规划/登记/分析/匹配/合成/进度撤销） |
| 服务层 | `services/` | llm/clip/ffmpeg/scene_detect/vector/file | ⚠️ scene_detect/ffmpeg/file 已桥接遗留 tools+utils；llm/clip/vector 待 V0.2 |
| 基础设施 | `infrastructure/` | postgres/minio/redis/cache/messaging | ❌ 大部分 stub |
| 接入层 | `api/` | REST v1 + 中间件 + WebSocket | ⚠️ `tasks`/`sessions` 真实可用（含确认门续跑）；asset/timeline/export/webhook 返回 501 |

## 当前目录结构

```
src/penclip/
├── domain/                      # 领域层（最内层，零依赖）
│   ├── entities/                #   Pydantic 实体：AssemblyState/VideoAsset/Segment/Slot/TimelineBlueprint
│   ├── value_objects/           #   dataclass+enum：IntentType/RiskLevel/CapabilityDeclaration/ExecutionResult
│   └── repositories/            #   仓储接口：Asset/Project/SessionRepository
├── core/                        # 应用层
│   ├── hub/                     #   CentralHub/CapabilityRegistry/IntentRecognizer/RiskAssessor/ContextManager
│   ├── orchestration/           #   WorkflowOrchestrator(真实按节点执行)/GraphFactory(线性装配)/LangGraphEngine(stub)
│   ├── state/                   #   StateManager/StateStore/MemoryStateStore/SQLiteStateStore/Checkpointer/state_schema
│   └── event/                   #   EventBus/EventType/Event/EventHandlers
├── agents/                      # 智能体层：base/agent_factory + planner(+planner_agent 桥)/asset/analyzer/matcher/composer/state/plugin
├── services/                    # 服务层：scene_detect/ffmpeg/file 已桥接；llm/clip/vector 待 V0.2
├── infrastructure/              # 基础设施：persistence(postgres/minio)/cache(redis)/messaging(redis_queue)
├── api/                         # 接入层
│   ├── v1/                      #   routes/dependencies + task/session（真实）· asset/timeline/export/webhook（501 占位）
│   ├── task_backend.py          #   neotask.TaskPool 任务生命周期，worker 内调中枢 process/confirm/cancel
│   ├── middleware/              #   auth(stub)/logging/rate_limit(stub)/error_handler
│   ├── websocket/               #   connection_manager/message_handler
│   └── schemas/                 #   request/response/event
├── cli/                         # CLI：main/repl/commands/renderer（`penclip-cli`，`pipeline` 一键出片）
├── plugins/                     # 插件系统：plugin_base/loader/manager + sandbox/docker_sandbox(V2.0)
│
├── hub/hub_core.py              # ⚠️ Bridge：转发 core/hub/central_hub
├── graph/hub_graph.py           # ⚠️ Bridge：转发 core/orchestration/graph_engine
├── state/models.py              # ⚠️ Bridge：转发 IntentType + TaskLifecycleStage
│
├── llm/                         # 遗留：多 AI 提供商（openai/qwen/deepseek/ollama/openai_compat）
├── tools/                       # 遗留：6 个视频分析工具（仍在使用）
├── utils/                       # 遗留：ffmpeg/redis/path/log 等 15 个工具函数
├── config/config.py             # 遗留：Settings + DEFAULT_CONFIG
├── app/                         # FastAPI 装配：application/setup_env
└── logger.py                    # 日志系统
```

## 领域模型

### 值对象（dataclass + enum，`domain/value_objects/`）

| 值对象 | 类型 | 说明 |
| :-- | :-- | :-- |
| `IntentType` | str Enum | 30 个意图，6 类：规划/分析/素材/效果/状态/通用 |
| `RiskLevel` | str Enum | `LOW` / `MEDIUM` / `HIGH` |
| `CapabilityDeclaration` | dataclass | 能力声明：name/intents/description/input_schema/output_schema/risk_level/version/agent_id |
| `ExecutionResult` | dataclass | 执行结果：success/data/message/suggestions/status/command_id |

### 实体（Pydantic BaseModel，`domain/entities/`）

| 实体 | 说明 |
| :-- | :-- |
| `AssemblyState` | **全局会话状态核心**：session_id/assets/slots/analysis_results/match_results/global_context/interaction_context/current_phase/history/时间戳 |
| `VideoAsset` | 素材：file_path/duration/width/height/status/metadata |
| `Segment` | 片段：asset_id/start_time/end_time/labels/label_scores/feature_vector |
| `Slot` | 时间线槽位：position/semantic_query/min/max_duration/assigned_segment_id |
| `TimelineBlueprint` | 时间线蓝图：slots/total_duration/output_resolution |
| `GlobalContext` / `InteractionContext` | 全局风格上下文 / 交互上下文（定义在 assembly_state.py） |
| `AnalysisResult` / `MatchResult` / `MatchCandidate` | 分析/匹配结果（定义在 assembly_state.py） |

### IntentType 完整清单

- **规划类**：`PLAN_CREATE`/`PLAN_APPEND`/`PLAN_INSERT`/`PLAN_DELETE`/`PLAN_REORDER`/`PLAN_DUPLICATE`
- **分析类**：`ANALYZE_FULL`/`ANALYZE_INCREMENTAL`/`ANALYZE_PRIORITY`/`ANALYZE_CANCEL`
- **素材类**：`CLIP_TRIM`/`CLIP_REPLACE`/`CLIP_SWAP`/`CLIP_PREVIEW`/`CLIP_REMOVE`
- **效果类**：`EFFECT_ADD_TRANSITION`/`EFFECT_CHANGE_TRANSITION`/`EFFECT_ADD_FILTER`/`EFFECT_REMOVE_FILTER`/`AUDIO_ADJUST_VOLUME`/`AUDIO_ADD_BGM`/`AUDIO_ADJUST_BGM_VOLUME`
- **状态类**：`STATE_QUERY_PROGRESS`/`STATE_QUERY_CAPABILITIES`/`STATE_UNDO`/`STATE_REDO`/`STATE_RENDER`
- **通用**：`EXECUTE`/`UNKNOWN`（未知输入经 `_missing_` 兜底为 `UNKNOWN`）

## 中枢分发流程（CentralHub.process）

```
用户输入
  ① _ensure_session()              会话不存在则兜底创建
  ② IntentRecognizer.recognize()   关键词匹配（长词优先）→ IntentResult
  ③ ContextManager.add_history()   记录交互历史
  ④ RiskAssessor.assess()          评估风险 → needs_confirmation(HIGH)
  ⑤ CapabilityRegistry.find_by_intent()  按意图查表路由
  ⑥ 高风险 → 挂起等待 confirm/cancel；低风险 → _snapshot_for_undo() 写撤销快照
  ⑦ agent.execute(params, context) Agent 自行读写 AssemblyState
  ⑧ 组装 HubResponse               含 success/intent/message/data/suggestions/needs_confirmation
```

- **能力注册**：`CentralHub.register_agent(agent)` 读取 `agent.declare_capabilities()` 写入 `CapabilityRegistry`（线程安全，意图→能力名倒排索引）
- **单例**：`get_hub()` / `get_state_manager()` / `get_event_bus()` / `get_graph()`

## Bridge 层（兼容转发）

顶层 `hub/`、`graph/`、`state/` 是为兼容旧导入路径设立的转发模块，**修改逻辑请改 `core/`、`domain/` 下的真实实现**：

| Bridge 模块 | 真实实现 | 导出符号 |
| :-- | :-- | :-- |
| `penclip.hub.hub_core` | `penclip.core.hub.central_hub` | `get_hub`/`CentralHub`/`HubRequest`/`HubResponse` |
| `penclip.graph.hub_graph` | `penclip.core.orchestration.graph_engine` | `get_graph`/`LangGraphEngine` |
| `penclip.state.models` | `domain/value_objects/intent` + `core/state/state_schema` | `IntentType`/`TaskLifecycleStage` |

> 同类 Bridge 还有 `agents/planner_agent.py` → `agents/planner.py`（`application.py` 启动钩子仍走旧路径导入）。

## V0.1 状态矩阵

### ✅ 已实现（真实逻辑）
- 领域模型：全部实体（Pydantic）+ 值对象（dataclass/enum）完整；撤销/重做快照经 `AssemblyState.restore_from()` 还原类型
- 中枢：`CentralHub` 分发流程（会话兜底、意图注入、执行前撤销快照、确认门）、`CapabilityRegistry`（线程安全）、`IntentRecognizer`（关键词，长词优先）、`RiskAssessor`、`ContextManager`
- 状态：`StateManager` + `MemoryStateStore`（内存）、`EventBus` + `EventType`
- 智能体：6 个 —— `PlannerAgent`（LLM 优先，无 Key 回退关键词切分，写入槽位）、`AssetAgent`、`AnalyzerAgent`（场景切分 + 视觉统计标签）、`MatcherAgent`（标签重叠 + 时长约束打分）、`ComposerAgent`（真实 ffmpeg concat/xfade）、`StateAgent`（进度/撤销/重做）
- 工作流：`WorkflowOrchestrator.run` 按节点顺序真实执行并 fail-fast，`GraphFactory.create_linear_workflow` 装配分析→匹配→合成链路；CLI `pipeline` 一键出片
- API：`api/v1/tasks`（`neotask.TaskPool` 异步执行中枢指令）+ `sessions/{id}/confirm|cancel` 确认续跑、`api/v1/sessions` 会话生命周期
- 遗留层：`llm/`（4 提供商 + 工厂）、`tools/`（6 分析工具）、`utils/`、`config`、`logger`、`app`（FastAPI 装配）

### ❌ Stub（V0.2+ 实现）
- `LangGraphEngine`（invoke/stream 直接返回输入）
- `services/`：`clip_service`/`vector_service`/`llm_service` 未接语义能力；`scene_detect`/`ffmpeg`/`file` 已桥接遗留实现
- `infrastructure/`：`postgres`/`minio`/`redis_cache`/`redis_queue` 明确 stub
- `api/v1/`：`asset`/`timeline`/`export`/`webhook` 端点返回 501（禁止假成功）
- `api/middleware/`：`auth`（JWT/OAuth 待 V1.0）、`rate_limit`（token-bucket 待 V1.0）
- `plugins/sandbox/docker_sandbox`（V2.0）
- `core/state/sqlite_store`（V0.2）、`api/task_backend.recover_pending_tasks`（V0.1 仅计数）

## 关键设计决策

- **星型中枢是主架构**，线性工作流只是注册的第一个能力，不是主架构
- **DDD 分层**：领域层零依赖，`core` 依赖 `domain`，`infrastructure` 实现仓储接口（依赖倒置）
- **能力注册是核心扩展机制**：新增功能继承 `BaseAgent` + `declare_capabilities()`，不修改中枢
- **值对象用 dataclass，实体用 Pydantic**（区分「无行为的小对象」与「需校验/序列化的聚合」）
- **Bridge 层**：`hub/`/`graph/`/`state/` 顶层模块为兼容转发，真实实现下沉到 `core/`/`domain/`
- **意图识别 V0.1 关键词匹配**，V0.2 升级 LLM；**图编排 V0.1 stub**，V0.2 接入 LangGraph
- **遗留层共存**：`llm/`（多 AI 提供商）、`tools/`/`utils/`/`config/`/`logger.py` 仍在使用，逐步迁移到对应服务与基础设施实现

## 技术栈

- 语言：Python 3.9+；包管理：`pyproject.toml`（src-layout）
- AI：LangGraph 1.x + LangChain，OpenAI/Qwen/DeepSeek/Ollama（经 `llm/` 或 `services/llm_service`）
- Web：FastAPI + uvicorn；实时：WebSocket
- 视频：FFmpeg、OpenCV、PyDub；标注：CLIP；分割：PySceneDetect（V0.2）
- 存储：SQLite → PostgreSQL；缓存/队列：Redis；对象存储：MinIO（V0.3）
- 代码质量：ruff、black、mypy、pytest、pre-commit

## 版本演进路线

| 版本 | 代号 | 核心目标 | 当前状态 |
| :-- | :-- | :-- | :-- |
| V0.1 | 星型骨架 | DDD 分层骨架 + 关键词命令解析 | **当前** |
| V0.2 | 语义理解 | LLM 意图解析 + 真实 LangGraph 编排 + SQLite 状态 | 规划中 |
| V0.3 | 可视化协作 | Web UI + 多 Agent 协作 + 能力注册正式化 | 规划中 |
| V1.0 | 生产就绪 | 企业级能力（认证/限流/Postgres/MinIO/K8s） | 远期 |
| V2.0 | 生态开放 | 插件市场 + Docker 沙箱 | 远期 |

## 工作原则

- 能力注册是核心扩展机制，新增功能必须通过 `register_agent`/`register` 接入，不修改中枢
- 数据契约：值对象 dataclass、实体 Pydantic，前后端共享类型定义
- 每个操作必有结构化日志记录（`penclip.logger`）
- 高/中风险操作不可省略用户确认节点（`RiskAssessor.needs_confirmation`）
- 依赖方向严格外层→内层，领域层不得 import 任何应用/基础设施层

## 相关资源

- 设计文档：`docs/视频混剪智能体-项目总结.md`（含原技术架构/版本演进/设计原则的精简版）
- 控制台用法：`docs/视频混剪智能体-控制台使用指南.md`
- 图文快速开始：`docs/视频混剪智能体-快速开始.md`
- AI 开发总览：`docs/AI开发导向-项目总览.md`
- 入口与约定：根目录 `CLAUDE.md` / `AGENTS.md`