# xmind_testcase

从自然语言需求生成**测试用例脑图**，支持对话迭代、模块化规划、导出（含 XMind 相关能力）。  
后端基于 **FastAPI + LangChain**；前端为 **Vue 3 + Vite + Tailwind**。可选接入 **MCP**（如飞书/Lark）以拉取在线文档正文再生成用例。

## 仓库结构

| 路径 | 说明 |
|------|------|
| `backend/` | FastAPI 应用、`/api/test-case-agent/*`、LLM / MCP 逻辑 |
| `frontend/web/` | Vue 控制台与脑图展示（开发时代理到本机后端） |
| `docs/` | 其他文档（若有） |

### 代码框架（目录树）


```text
xmind_testcase/
├── README.md
├── .gitignore
├── backend/
│   ├── .env_example                      # 环境变量示例，复制为同目录下 .env 使用
│   ├── requirements.txt                  # Python 运行时依赖
│   ├── requirements-dev.txt             # 可选：测试/开发补全依赖
│   ├── pytest.ini                       # pytest 配置
│   ├── mcp.json.example                 # MCP 配置样例（运行时应在 cwd 下放 mcp.json）
│   ├── app/
│   │   ├── main.py                      # FastAPI 创建、CORS、挂载 `/api/test-case-agent`
│   │   ├── config.py                    # Pydantic Settings，从环境变量/.env 读取
│   │   ├── logging_setup.py             # 日志级别（含第三方库降噪）
│   │   ├── api/
│   │   │   ├── test_case_agent/          # `/api/test-case-agent/*`（按功能分子包，类 Next 路由目录）
│   │   │   │   ├── __init__.py           # 汇总子路由、GET `/mcp-diagnostics`、POST `/`（legacy）
│   │   │   │   ├── common.py             # 鉴权与统一错误响应
│   │   │   │   ├── plan/routes.py        # POST `/plan`、`/plan/requirement-source` 等
│   │   │   │   ├── module/routes.py      # POST `/module`
│   │   │   │   ├── chat/routes.py        # POST `/chat`
│   │   │   │   └── export_xmind/routes.py # POST `/export-xmind`（URL 用连字符，包名用下划线）
│   │   │   ├── main.py                  # 其余 API 占位（如有）
│   │   │   └── config.py
│   │   ├── schemas/                     # 请求体/响应体、LLM 结构化输出 Pydantic 模型
│   │   └── services/
│   │       ├── test_case_agent.py       # 脑图建树、提示词与纯函数（无 I/O）
│   │       ├── test_case_llm.py         # 各场景结构化 LLM 调用（plan/module/chat…）
│   │       ├── test_case_mcp_invoke.py  # MCP 取证 + 合并 prompt + 结构化收口
│   │       ├── xmind_export.py          # 生成 .xmind 二进制
│   │       ├── mcp_loader.py            # 读取 mcp.json、判断是否启用 MCP
│   │       ├── chat_model.py             # LangChain ChatModel 工厂
│   │       └── llm_response_extract.py   # 从模型/Agent 结果抽取文本与 JSON
│   └── tests/                            # pytest 单测（与 services/schemas 对齐）
│
└── frontend/
    ├── package.json                      # 工作区/聚合（如有）
    └── web/                              # Vue 3 + Vite 子工程
        ├── package.json
        ├── vite.config.ts                # 开发服务器；/api、/health 代理到后端 :8000
        ├── index.html
        └── src/
            ├── main.ts
            ├── App.vue                   # 主界面：需求输入、脑图工具栏、导出
            ├── api/                      # fetch 封装 → `/api/test-case-agent/*`
            ├── components/
            │   ├── ChatBubblePanel.vue   # 对话区
            │   └── mindmap/              # simple-mind-map 封装与数据双向绑定
            ├── composables/              # useTestCaseWorkspace：plan→module→chat 状态机
            ├── lib/                      # 脑图 normalize/合并、CSV 导出
            ├── types/                  # 与后端 JSON 对齐的 TS 类型
            └── data/                     # 需求模板等静态数据
```



## 环境要求

- Python **3.10+**（建议 3.11）
- Node.js **18+**，包管理可用 **pnpm** / **npm**
- 可访问所选 LLM API（官方 OpenAI 或兼容 **`OPENAI_BASE_URL`** 的网关）

## 快速开始

### 1. 后端

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

将 `backend/.env_example` 复制为 **`backend/.env`**，填入至少 **`OPENAI_API_KEY`**。（变量名详见下表。）

**注意：** 应用会从**当前工作目录**读取 **`mcp.json`** 与 **`.env`**。请在 **`backend`** 目录下启动 Uvicorn，或将上述文件放在你启动命令的 cwd 中。

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

健康检查：<http://127.0.0.1:8000/health>

### 2. 前端

```bash
cd frontend/web
pnpm install   # 或 npm install
pnpm dev       # 或 npm run dev
```

默认开发服务器会把 **`/api`**、**`/health`** 代理到 **`http://127.0.0.1:8000`**（见 `frontend/web/vite.config.ts`）。请先启动后端。

生产或自定义后端地址时，可设置：

```bash
set VITE_API_BASE=https://your-api.example.com   # Windows CMD
$env:VITE_API_BASE="https://..."                 # PowerShell
```

## 环境变量（后端）

摘自 `backend/.env_example`。实际密钥勿提交仓库；`.env` 已被 `.gitignore` 忽略。

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | LLM API 密钥（必需，除少量无需模型的接口） |
| `OPENAI_MODEL` | 模型名，默认如 `gpt-4.1-mini` |
| `OPENAI_BASE_URL` | 可选；非空时使用兼容 OpenAI 的自定义网关 |
| `LARK_MCP_APP_ID` / `LARK_MCP_APP_SECRET` / `LARK_MCP_USER_ACCESS_TOKEN` | 飞书 MCP 相关；可与 `mcp.json` 中 `${VAR}` 展开配合使用 |
| `LOG_LEVEL` | `INFO`（默认）或 `DEBUG`（日志更详尽） |

（Pydantic 同时接受小写别名，但示例文件使用大写，与运行时提示一致即可。）

## MCP（可选）

当用户输入中含链接或关键词（飞书、钉钉文档、Wiki 等，规则见 `mcp_loader.should_use_mcp`）且存在可用 MCP 配置时，可走「文档取证 → 结构化输出」链路。

在项目 **`backend`** 工作目录下放 **`mcp.json`**（Cursor 同款 `mcpServers` 结构），支持 **stdio** 与 **HTTP/SSE** 等。可参考各 MCP 提供方文档；敏感项建议用环境变量 + `${VAR}` 占位。

未配置或规则未命中时，仍可直接对粘贴的需求文本调用 LLM。

## 开发与测试

```bash
cd backend
pytest -q
```

可选：`pip install -r requirements-dev.txt`（若与主 `requirements.txt` 拆分使用）。

前端类型检查与构建：

```bash
cd frontend/web
pnpm run build
```

## API 概要

前缀：**`/api/test-case-agent`**（详见 `backend/app/api/test_case_agent.py`）。

- `GET /health` — 服务存活探测

典型流程：先做计划/模块化，再按需生成单模块或全文用例，并通过对话更新脑图；具体路径与请求体以前端调用与路由定义为准。

## 许可证

若需对外分发，请在仓库内补充所选许可证文件。
