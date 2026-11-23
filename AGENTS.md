# PenClip — 视频混剪智能体

基于**星型中枢分发架构**的 AI 视频混剪系统：自然语言驱动视频分析、片段匹配与自动合成。核心理念「人机协同」—— AI 辅助而非替代创作者。

## 当前状态
- 版本：**V0.1（DDD 分层 + 出片闭环）**，开发分支 `dev`
- 顶层架构：星型中枢分发（`CentralHub`）+ 线性链路工作流（`WorkflowOrchestrator.run` 真实执行，`GraphFactory.create_linear_workflow` 装配）
- 闭环：素材登记 → 场景分析（自适应阈值 + 视觉统计标签）→ 槽位规划 → 标签匹配 → concat 合成；验收见 `tests/integration/test_video_pipeline.py`
- REST 走法：`POST /api/v1/sessions` → `POST /api/v1/tasks`（自然语言指令，异步任务）→ 高风险指令用 `POST /api/v1/tasks/sessions/{id}/confirm` 续跑
- 意图识别：V0.1 关键词匹配（`IntentRecognizer`，**长词优先**），V0.2 才升级 LLM 语义理解
- 中枢副作用：`process()` 会兜底创建会话、把识别到的 `intent` 注入 params/context、在执行变更前写入撤销快照（只读意图跳过）
- 图编排：`LangGraphEngine` V0.1 仅 stub，V0.2 真正接入 LangGraph

## 分层架构（依赖方向：外层 → 内层，内层禁止反向依赖）
```
domain/          领域层：实体(Pydantic) + 值对象(dataclass/enum) + 仓储接口 —— 零依赖
core/            应用层：hub 分发 / orchestration / state / event —— 依赖 domain
agents/          智能体：BaseAgent + Planner/Asset/Analyzer/Matcher/Composer/State —— 依赖 domain+core
services/        服务层：scene_detect/ffmpeg/file 已桥接遗留 tools+utils；llm/clip/vector 仍为 V0.2 stub
infrastructure/  基础设施：postgres/minio/redis/cache/messaging —— 实现仓储接口，多为 stub
api/             接入层：v1 REST / middleware / websocket / schemas
cli/             CLI 入口
plugins/         插件系统 + Docker 沙箱（V2.0）
```
遗留层（仍在使用，逐步迁移）：`llm/`（多 AI 提供商）、`tools/`（6 个视频分析工具）、`utils/`（ffmpeg/redis/path/log 等）、`config/config.py`、`logger.py`

## Bridge 层（向后兼容转发，勿在此改逻辑）
顶层 `hub/`、`graph/`、`state/` 是兼容转发模块，真实实现在 `core/`、`domain/`：
- `penclip.hub.hub_core` → `penclip.core.hub.central_hub`（`get_hub`/`CentralHub`/`HubRequest`/`HubResponse`）
- `penclip.graph.hub_graph` → `penclip.core.orchestration.graph_engine`（`get_graph`/`LangGraphEngine`）
- `penclip.state.models` → `IntentType`(domain) + `TaskLifecycleStage`(core.state)

## 关键入口
```python
from penclip.hub.hub_core import get_hub           # 中枢单例
from penclip.agents import register_core_agents     # 一次性注册 6 个智能体（REST 与 CLI 共用）
from penclip.graph.hub_graph import get_graph       # 图引擎（stub）
from penclip.state.models import IntentType, TaskLifecycleStage
from penclip.domain.value_objects.intent import IntentType  # 真实定义处
```
启动：`python main.py`（→ `penclip.app:app` FastAPI，默认 http://localhost:8000，`/docs` 交互文档）
控制台：`penclip-cli`（→ `penclip.cli.main:main`，交互式 REPL；`help` 看流程，`pipeline` 一键出片）
测试：`pytest`（`tests/unit` 纯逻辑、`tests/api` REST、`tests/integration` 端到端出片，后者需本机 ffmpeg）

## 核心契约（开发必读）
- `IntentType`（str Enum）：30 个意图，6 类 —— 规划/分析/素材/效果/状态/通用
- `CapabilityDeclaration`（dataclass）：`name` + `intents` + `input_schema`/`output_schema` + `risk_level` + `version`
- `BaseAgent`（ABC）：`declare_capabilities()` + `execute(params, context)`，经 `CentralHub.register_agent()` 接入
- `ExecutionResult`（dataclass）：`success`/`data`/`message`/`suggestions`/`status`
- `HubResponse`（dataclass）：中枢对外响应，含 `suggestions`、`needs_confirmation`、`needs_clarification`
- `AssemblyState`（Pydantic）：全局会话状态（assets/slots/analysis_results/match_results/global_context/...）

## 开发约定
- 所有 import 统一 `penclip.*` 前缀；`core/` 禁止反向依赖 `agents/`（中枢用 dict 作为 context 传给 Agent）
- 值对象用 `dataclass`+`enum`；实体与 API 模型用 Pydantic `BaseModel`
- 工具函数返回 `Dict` 带 `success` 字段、不抛异常；API 层用 `HTTPException`
- 用 `penclip.logger` 的 `debug/info/warning/error`，禁止 `print()`
- 每个工具/Agent 必须有 `DEFAULT_CONFIG`；能力注册是核心扩展机制，新增能力不修改中枢代码
- Agent 自己读写 `AssemblyState`（`get_session` 返回副本，改完必须 `update_session`）；撤销快照由中枢统一写入，只读意图需登记到 `central_hub._NON_MUTATING_INTENTS`
- 未实现的意图（转场/滤镜/音量等）返回 `status="unsupported"` 的失败结果，禁止假成功

## 详细文档
- 项目知识：`.claude/skills/project.md`（架构/目录/领域模型/V0.1 状态）
- 智能体开发：`.claude/skills/agent-development.md`
- 代码规范：`.claude/skills/code-standards.md`
- 代码校验：`.claude/skills/validation.md`
- 设计文档：`docs/视频混剪智能体-项目总结.md`（四文档精简，**先读**）、`docs/视频混剪智能体-控制台使用指南.md`（REPL 逐字示例）、`docs/视频混剪智能体-快速开始.md`、`docs/AI开发导向-项目总览.md`