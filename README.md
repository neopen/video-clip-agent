# PenClip — 视频混剪智能体

基于**星型中枢分发架构**的 AI 视频混剪系统。以自然语言驱动视频分析、片段匹配与自动合成，通过多智能体协作实现「人机协同」的创作体验—— AI 辅助而非替代创作者。

## 架构概览

PenClip 采用 **DDD 分层架构**，顶层为**星型中枢分发模式**（`CentralHub` 负责命令解析 → 意图识别 → 能力路由 → 智能体调度），首个注册的标准工作流为**线性链路节点模式**（采样 → 解析 → 分析 → 匹配 → 合成）。

```
用户输入 → CentralHub → [意图识别 → 风险评估 → 能力路由] → Agent 执行 → 状态更新 → 用户反馈
```

分层结构（依赖方向：外层 → 内层，内层零反向依赖）：

| 层 | 目录 | 职责 |
| :-- | :-- | :-- |
| 领域层 | `domain/` | 实体（Pydantic）+ 值对象（dataclass/enum）+ 仓储接口 |
| 应用层 | `core/` | 中枢分发 / 编排 / 状态管理 / 事件总线 |
| 智能体 | `agents/` | `BaseAgent` + Planner/Asset/Analyzer/Matcher/Composer/State |
| 服务层 | `services/` | 场景分割 / FFmpeg / 文件解析已接通；LLM / CLIP 向量检索待 V0.2 |
| 基础设施 | `infrastructure/` | PostgreSQL/MinIO/Redis 等仓储与缓存（V0.1 为内存/假实现） |
| 接入层 | `api/` + `cli/` | REST v1 / 中间件 / WebSocket / CLI |

**当前版本**：V0.1（出片闭环）—— 素材登记 → 场景分析 → 槽位规划 → 标签匹配 → concat 合成已端到端跑通（控制台与 REST 双通道）；`LangGraph` 编排、`infrastructure/`、语义向量匹配仍为 V0.2 占位 stub。详见 [版本路线](#版本路线)。

## 核心特性

- **交互式控制台（REPL）**：实时人机协同——澄清式对话、渐进式细化、高风险操作确认中断
- **星型中枢分发**：命令解析 → 意图识别（30 个意图枚举）→ 风险评估 → 能力路由
- **能力注册机制**：新增功能继承 `BaseAgent` 并声明能力，无需修改中枢代码
- **多 AI 提供商**：OpenAI / 通义千问 Qwen / DeepSeek / Ollama（本地模型）
- **视频处理**：场景切分（自适应阈值）+ 视觉统计标签 → 标签匹配 → FFmpeg concat 合成；语音识别 / 情绪分析 / 物体检测工具已就位，待接入智能体
- **结构化日志**：分级日志 + JSON 格式 + 文件轮转

## 快速开始

### 环境要求

- Python 3.9+
- FFmpeg（需配置到系统 PATH，或由项目内置检测）

### 安装

```bash
git clone https://github.com/neopen/video-clip-agent.git
cd video-clip-agent

# 创建虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate.bat
# Linux / macOS
source .venv/bin/activate

# 安装依赖（本项目只有 pyproject.toml，没有 requirements.txt）
pip install -e .
```

> 开发环境可一次装齐开发依赖：`pip install -e ".[dev]"`

### 配置 AI 提供商

复制 `.env.example` 为 `.env`，选择并填写对应的提供商配置：

```ini
# 提供商: openai | qwen | deepseek | ollama
AI_PROVIDER=qwen

# 通义千问（DashScope 兼容模式）
QWEN_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxx
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus
```

各提供商对应的环境变量：

| 提供商 | 环境变量 |
| :-- | :-- |
| OpenAI | `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` |
| Qwen | `QWEN_API_KEY` / `QWEN_BASE_URL` / `QWEN_MODEL` |
| DeepSeek | `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` |
| Ollama | `OLLAMA_BASE_URL` / `OLLAMA_MODEL` |

配置采用**双通道**：`config.json`（用户本地覆盖）+ `.env`（环境变量，优先级更高）。

### 启动服务

```bash
python main.py            # 默认 http://localhost:8000
python main.py --port 8080
python main.py --host 0.0.0.0 --port 8000   # 生产（多进程需 Redis）
```

服务启动后，交互式 API 文档位于 http://localhost:8000/docs。

### 启动交互控制台（主要使用方式）

PenClip 以**控制台实时交互**为主要使用方式（REST 异步仅为备用）：

```bash
# 交互式控制台（需先 pip install -e .）
penclip-cli                       # 自动生成会话
penclip-cli --session my-vlog     # 指定会话 ID

# 或模块方式（开发环境）
python -m penclip.cli.main
```

控制台支持三种交互模式（一次性指令 / 澄清式对话 / 渐进式细化）与高风险操作确认中断。示例：

```
penclip> E:\videos\travel_01.mp4
[OK] 已添加素材: travel_01.mp4

penclip> 做一个旅行 Vlog，风景放开头，美食放中间
确认根据此需求创建新的时间线规划？
确认执行? [y/N] y
[OK] 创建时间线：3 个片段槽位，共 3 个
  建议：下一步：分析素材 → 匹配片段 → 合成（也可用 pipeline 一次跑完）

penclip> 分析素材
[OK] 已分析 3 个素材，共 12 个片段

penclip> 匹配片段
[OK] 已匹配 3/3 个槽位

penclip> 合成
确认开始最终渲染？渲染开始后中途取消可能导致不完整输出。
确认执行? [y/N] y
[OK] 已合成 3 个片段 → data\output\composed_output.mp4

penclip> 撤销
[OK] 已撤销：匹配片段

penclip> pipeline        # 一键跑完 分析 → 匹配 → 合成（仍保留确认门）
```

> 完整用法见 [控制台使用指南](docs/视频混剪智能体-控制台使用指南.md)。

## API 接口

### 已上线端点

系统（`index_api.py`）：

| 方法 | 路径 | 说明 |
| :-- | :-- | :-- |
| GET | `/` | 服务信息 |
| GET | `/health` | 健康检查 |

领域路由（`api/v1/`，前缀 `/api/v1`）：

| 方法 | 路径 | 说明 |
| :-- | :-- | :-- |
| POST | `/api/v1/sessions` | 创建会话（可自带 `session_id`） |
| GET | `/api/v1/sessions/{session_id}` | 会话概览：phase / assets / slots / matched_slots / undo_depth |
| DELETE | `/api/v1/sessions/{session_id}` | 删除会话 |
| POST | `/api/v1/tasks` | 提交自然语言指令（异步，返回 task_id） |
| GET | `/api/v1/tasks/{task_id}` | 查询任务状态 |
| GET | `/api/v1/tasks/{task_id}/result` | 获取任务结果（含 `needs_confirmation`、`suggestions`） |
| DELETE | `/api/v1/tasks/{task_id}` | 取消任务 |
| POST | `/api/v1/tasks/sessions/{session_id}/confirm` | 确认挂起的高风险指令并续跑 |
| POST | `/api/v1/tasks/sessions/{session_id}/cancel` | 放弃挂起指令 |
| * | `/api/v1/{assets,timelines,exports,webhooks}/…` | V0.1 占位，返回 `501`，请改用 `/api/v1/tasks` |

### 使用示例

```bash
# 健康检查
curl http://localhost:8000/health

# 建会话 → 提交指令（异步）
SESSION=$(curl -s -X POST http://localhost:8000/api/v1/sessions | jq -r .session_id)
curl -s -X POST http://localhost:8000/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d "{\"user_input\": \"做个混剪：红色开头，绿色中间，蓝色结尾\", \"session_id\": \"$SESSION\"}"
# → {"task_id": "...", "session_id": "...", "status": "pending"}

# 轮询结果；高风险指令会停在确认门
curl -s http://localhost:8000/api/v1/tasks/{task_id}/result
# → {"needs_confirmation": true, "confirmation_message": "..."}

# 确认放行后继续（同样返回 task_id，再轮询）
curl -s -X POST http://localhost:8000/api/v1/tasks/sessions/$SESSION/confirm
```

> 交互式 API 文档：http://localhost:8000/docs。REST 异步为**备用方案**，主要交互方式请使用[交互控制台](docs/视频混剪智能体-控制台使用指南.md)。

## 目录结构

完整目录结构与模块说明见 [`.claude/skills/project.md`](.claude/skills/project.md)，简要总览：

```
src/penclip/
├── domain/          # 领域层：entities / value_objects / repositories（零依赖）
├── core/            # 应用层：hub / orchestration / state / event
├── agents/          # 智能体：BaseAgent + Planner/Asset/Analyzer/Matcher/Composer/State
├── services/        # 服务层：scene_detect / ffmpeg / file 已接通；llm / clip / vector 待 V0.2
├── infrastructure/  # 基础设施：persistence / cache / messaging
├── api/             # 接入层：v1 / task_backend(neotask) / middleware / websocket / schemas
├── cli/             # CLI（penclip-cli 控制台）
├── plugins/         # 插件系统 + Docker 沙箱
├── hub/ graph/ state/   # ⚠️ Bridge 兼容转发层（指向 core/、domain/）
├── llm/             # 遗留：多 AI 提供商客户端
├── tools/           # 遗留：6 个视频分析工具
└── utils/ config/ logger.py   # 遗留：工具库 / 配置 / 日志
```

## 技术栈

- **语言**：Python 3.9+
- **Web**：FastAPI + uvicorn（异步，自动 OpenAPI 文档）
- **AI**：OpenAI / 通义千问 Qwen / DeepSeek / Ollama；LangGraph 1.x + Checkpoint 已声明，V0.1 编排仍为直通 stub
- **视频**：FFmpeg、OpenCV（自研自适应场景切分）、PyDub；SpeechRecognition 工具已就位但未接入智能体
- **数据**：NumPy、Pandas、Scikit-learn
- **队列/缓存**：Redis（多进程模式）
- **代码质量**：ruff、black、mypy、pytest、pre-commit

## 版本路线

| 版本 | 代号 | 核心目标 | 状态 |
| :-- | :-- | :-- | :-- |
| V0.1 | 出片闭环 | DDD 分层 + 关键词中枢分发 + 端到端出片（控制台与 REST 双通道）| **当前** |
| V0.2 | 语义理解 | LLM 意图解析 + 真实 LangGraph 编排 + SQLite 状态 | 规划中 |
| V0.3 | 可视化协作 | Web UI + 多 Agent 协作 + 能力注册正式化 | 规划中 |
| V1.0 | 生产就绪 | 企业级能力（认证/限流/Postgres/MinIO/K8s） | 远期 |
| V2.0 | 生态开放 | 插件市场 + Docker 沙箱 | 远期 |

## 开发

```bash
# 代码格式化
black src/ tests/

# Lint 检查与自动修复
ruff check src/ tests/
ruff check --fix src/ tests/

# 类型检查
mypy src/penclip

# 运行测试
pytest

# Git 钩子（提交前自动检查）
pre-commit install
```

## 文档

| 文档 | 说明 |
| :-- | :-- |
| [控制台使用指南](docs/视频混剪智能体-控制台使用指南.md) | 交互式控制台（REPL）完整用法 |
| [快速开始](docs/视频混剪智能体-快速开始.md) | 从零到跑通的图文指南 |
| [项目总结](docs/视频混剪智能体-项目总结.md) | 项目设计理念与核心契约（原「技术架构 / 版本演进 / 设计原则 / 项目总览」四文档的精简版） |
| [AI 开发总览](docs/AI开发导向-项目总览.md) | AI 开发者视角的项目总览 |
| [项目技能](.claude/skills/SKILL.md) | Claude Code 技能文档索引 |

## License

[MIT](LICENSE)