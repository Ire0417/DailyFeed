# DailyFeed

> 一个基于 **多 Agent Swarm 架构** + **三层混合记忆模块** 的个人日报聚合系统。
> 
> 从 GitHub Trending / B站 / RSS 抓取内容 → LLM 摘要 → 聚合为 Markdown 报告 → 多渠道推送，
> 并通过 **偏好记忆 / 长期记忆 / 会话记忆 / 任务记忆 / 实体关系图** 的组合，使系统在多次运行后逐步"更懂用户"。

---

## 目录

1. [项目目标与定位](#1-项目目标与定位)
2. [架构全景图](#2-架构全景图)
3. [后端核心实现](#3-后端核心实现)
4. [前端实现](#4-前端实现)
5. [三层混合记忆模块（重点）](#5-三层混合记忆模块)
6. [数据抓取：GitHub / B站 / RSS](#6-数据抓取)
7. [LLM 摘要：Qwen / OpenAI + 抽取式降级](#7-llm-摘要)
8. [推送系统：Email / 微信 / 钉钉 / Webhook](#8-推送系统)
9. [API 设计与鉴权](#9-api-设计与鉴权)
10. [关键设计决策与亮点](#10-关键设计决策与亮点)
11. [快速开始](#11-快速开始)
12. [目录结构](#12-目录结构)
13. [未来扩展方向](#13-未来扩展方向)

---

## 1. 项目目标与定位

DailyFeed 不是一个通用的 LLM 聊天机器人，而是一个"信息处理流水线"：

- **输入**：用户订阅的一系列信息源（GitHub Trending / GitHub Top-starred / B站 UP 主 / RSS）
- **处理**：抓取 → 内容摘要（LLM）→ 聚合 → 按用户偏好排序
- **输出**：结构化 Markdown / HTML 日报 + 邮件/Webhook 推送

核心价值在于**把"持续的内容消费"从主动浏览（耗费注意力）变成"被动接收高质量摘要"**。

记忆模块的引入是为了让系统在多次运行后**持续学习用户偏好** — 今天关注的关键词，会影响明天报告的排序；过去 7 天没打开过的推送渠道，会被自动降权。

---

## 2. 架构全景图

### 2.1 演进路径：从异步 Swarm 到同步 Pipeline

最初计划的 **5 Agent 异步消息总线架构**：

```
 Scheduler (定时触发)
      │
      ▼
 MessageBus (Redis Stream)
      │
   ┌──┼──┬──────────┐
   ▼  ▼  ▼          ▼
Fetcher ─┐    Summarizer ─┐
   │     └─── Aggregator ─┘
   ▼
Pusher  (Email / 微信 / 钉钉 / Webhook)
```

**问题**：

- 需要 Redis + 多个进程/容器，本地启动门槛高
- 调试时多 Agent 的日志分散
- MVP 阶段"高并发吞吐"并不是瓶颈

**解决方案 → 同步流水线模式**：
保留 Agent 的模块化职责划分，但全部合并到一个 `PipelineService` 中同步执行：

```python
await PipelineService(db).run_pipeline(user_id=uid)
# └─ 读取用户偏好 (MemoryRouter)
#    ├─ 抓取所有订阅源 (Fetcher 家族)
#    ├─ 记录任务步骤 (TaskMemBuf)
#    ├─ 内容关键词 → 实体关系图 (GraphMem)
#    ├─ LLM 摘要 (Summarizer)
#    ├─ 聚合为 Markdown + HTML (Aggregator / ReportBuilder)
#    ├─ 报告写入 LTM (LongTermMemory)
#    └─ 推送到用户偏好渠道 (Pusher)
```

这种**"保留模块边界，但用同步调用替代消息总线"**的折中方案，
使得系统既保持了清晰的职责划分，又能在单进程中完整运行，
同时 `MemoryRouter` 的存在保证了当未来需要切回分布式模式时，Agent 可以无缝迁移。

### 2.2 完整架构图

```
               ┌────────────────────────────────────────────────────┐
               │                       前端 (frontend)              │
               │  React + TypeScript + Vite + Tailwind CSS          │
               │  仪表板 / 订阅源管理 / 报告列表 / 报告详情 / 设置    │
               │  登录注册 / Zustand 风格状态管理 / Axios 调用       │
               └───────────────────┬────────────────────────────────┘
                                   │  HTTP(S)
                                   ▼
               ┌────────────────────────────────────────────────────┐
               │   FastAPI (api/) - 5 handlers + 3 middlewares       │
               │  auth  | subscription | report | user | health      │
               │  认证: HS256 JWT / 邮箱注册 / 权限中间件             │
               │  CORS: 允许 http://localhost:5173  开发代理          │
               └───────────────────┬────────────────────────────────┘
                                   │
                                   ▼
               ┌────────────────────────────────────────────────────┐
               │  PipelineService (orchestrator/pipeline_service.py)│
               │  └─ 单一入口 run_pipeline()                          │
               └───────────────────┬────────────────────────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          ▼                        ▼                        ▼
   ┌─────────────┐           ┌────────────────────┐   ┌─────────────┐
   │  Fetcher    │           │   Memory Module    │   │  Summarizer │
   │  (RSS/GitHub│           │  (internal/memory)│   │  (Qwen/OpenAI│
   │  /Bilibili) │           │  Preference | LTM │   │  + 降级)     │
   └─────────────┘           │  STM | TaskBuf    │   └─────────────┘
                             │  Graph | Router    │          │
                             │  LifecycleManager │          ▼
                             └──────────┬─────────┘   ┌─────────────┐
                                        │             │  Aggregator│
                                        ▼             │  ReportBuilder│
                             ┌─────────────┐        └─────────────┘
                             │  Database   │
                             │  PostgreSQL │               ▼
                             │  + SQLite   │        ┌─────────────┐
                             │   fallback  │        │   Pusher    │
                             │  + 向量索引 │        │  Email/微信/│
                             └─────────────┘        │  钉钉/Webhook│
                                                    └─────────────┘
```

---

## 3. 后端核心实现

### 3.1 分层结构

```
backend/
├── api/                       # FastAPI 层
│   ├── main.py               # 应用入口（路由注册 + 中间件 + 事件触发）
│   ├── handlers/             # auth / subscription / report / user / health
│   ├── middlewares/          # CORS / 鉴权日志 / JWT
│   └── schemas/              # Pydantic 请求/响应模型
│
├── internal/
│   ├── orchestrator/
│   │   ├── pipeline_service.py    # ★ 同步流水线主入口（核心）
│   │   ├── message_bus.py          # 消息总线（保留，可扩展为异步）
│   │   └── supervisor.py           # 监控 & 自动重启（可扩展）
│   │
│   ├── domain/                     # ★ DDD 领域层（纯数据模型，无副作用）
│   │   ├── entities/               # User / Subscription / Content / Summary / Report
│   │   └── value_objects/          # SourceType / Priority / Status
│   │
│   ├── pipeline/                   # ★ 业务 Pipeline（抓取/摘要/聚合/推送）
│   │   ├── fetcher/                # github / bilibili / rss + factory 模式
│   │   ├── summarizer/             # llm（Qwen/OpenAI）+ extractive（抽取式）降级 + cache
│   │   ├── aggregator/             # report_builder + template（Markdown/HTML）
│   │   └── pusher/                 # email / wechat / dingtalk / notifier 路由
│   │
│   ├── memory/                     # ★ 三层混合记忆模块（本项目核心创新点）
│   │   ├── base.py                 # MemoryItem / MemoryKind / MemoryLayer / ACL
│   │   ├── preference_store.py     # GlobalShared - 用户偏好
│   │   ├── long_term_memory.py     # GlobalShared - 长期记忆（向量检索）
│   │   ├── short_term_memory.py    # SessionIsolated - 短期对话 ring buffer
│   │   ├── task_buf.py             # TaskSpecific - 任务步骤缓冲
│   │   ├── graph_mem.py            # TaskSpecific - 实体关系图（全局图 + 子图）
│   │   ├── memory_router.py        # ★ 统一入口（路由 + ACL + 跨层查询）
│   │   └── lifecycle_manager.py    # 周期清理 + 高价值条目升档
│   │
│   ├── infrastructure/
│   │   ├── database/               # models / session（SQLite 自动回退）+ repositories
│   │   ├── external/               # github_client / bilibili_client / openai_client
│   │   ├── cache/                  # cache_manager + redis_client（进程内回退）
│   │   └── monitoring/             # logger + metrics
│   │
│   ├── config/                     # settings.py + config.yaml
│   ├── agent/                      # 原 5 Agent（可扩展为独立进程）
│   ├── cmd/                        # CLI 脚本入口（每个 Agent 独立启动）
│   └── utils/                      # hash / markdown / retry / time
│
├── tests/                          # 单元/集成/E2E
├── test_memory_smoke.py            # ★ 记忆模块 7 个子用例
└── test_pipeline_integration.py    # ★ pipeline + memory 端到端测试
```

### 3.2 同步流水线主流程

`PipelineService.run_pipeline(user_id=...)` 是整个系统的核心入口。完整步骤：

```
(1) 初始化：
    └─ MemoryRouter + LifecycleManager（第一次请求时懒加载）

(2) 读取用户偏好（PreferenceStore）：
    └─ 关键词偏好 / 推送渠道偏好 / 摘要风格

(3) 启动 TaskMemBuf：
    └─ task = memory.start_task("pipeline_service", user_id=uid)

(4) 抓取所有订阅源（FetcherFactory → GitHub/B站/RSS）：
    ├─ 内容标题做关键词分词
    └─ 把关键词写入 GraphMem（add_cooccurrence）
    （→ 后续跨 Agent 可做"相关关键词推理"）

(5) LLM 摘要（Summarizer）：
    ├─ 主方案：Qwen（qwen-plus）/ OpenAI
    └─ 降级方案：extractive（textrank + TF-IDF）
    （失败会记录 step.error 但继续后续步骤）

(6) ReportBuilder 聚合：
    └─ 按订阅源分组 → Markdown 报告 → HTML 报告

(7) 写入长期记忆（remember_long_term）：
    └─ report_id + 内容哈希 → 30 天 TTL → 后续 query 可检索"之前给用户发过什么"

(8) 推送（Pusher）：
    └─ 根据用户偏好走 Email / 微信 / 钉钉 / Webhook

(9) LifecycleManager.tick()：
    └─ 清理过期 session / task
    └─ 高重要性 graph 节点升档到 LTM
```

### 3.3 设计模式与架构模式

| 模式                | 应用位置                                                             |
| ----------------- | ---------------------------------------------------------------- |
| **Repository 模式** | `database/repositories/`（users/subs/contents/reports/summaries）  |
| **工厂方法**          | `pipeline/fetcher/factory.py`（按 `source_type` 路由到 GitHub/B站/RSS） |
| **策略模式**          | `pipeline/summarizer/`（LLM vs 抽取式摘要，运行时切换）                       |
| **发布-订阅**         | `orchestrator/message_bus.py`（保留，Redis Stream）                   |
| **门面模式**          | `MemoryRouter`（对外提供一组统一 API，内部路由到 5 个记忆子模块）                      |
| **观察者模式**         | `PreferenceStore.on_update()`（LifecycleManager 订阅写事件 → 自动写入 LTM） |
| **DDD 分层**        | `domain/` 纯数据 + `pipeline/` 业务 + `infrastructure/` 外部依赖          |
| **容错模式**          | `utils/retry.py`（指数退避重试）+ summarizer 自动降级 + SQLite 回退            |

---

## 4. 前端实现

### 4.1 技术栈

- **React 18** + **TypeScript 5**（严格模式）
- **Vite 5**（HMR + 自动代理 `/api` → `localhost:8000`）
- **Tailwind CSS 3**（纯 utility-first，零自定义 CSS 框架）
- **Axios**（统一 HTTP 客户端 + 全局错误处理）
- **Zustand 风格** + 自实现 `useAuth` / `useSubscriptions` / `useReports` Hooks

### 4.2 路由结构（React Router v6）

```
/login                  # JWT 登录 + 持久化到 localStorage
/register               # 注册
/                       # 仪表板（统计卡片 + 最近报告 + 订阅概览 + 立即生成按钮）
/subscriptions          # 订阅源管理（添加/删除/切换开关；类型选择器 + 预设按钮）
/reports                # 报告列表（时间线视图）
/reports/:id            # 报告详情（Markdown 渲染 + 原始内容 / 统计）
/settings               # 用户设置（推送渠道 / 邮箱 / Webhook / 关键词偏好）
```

### 4.3 状态管理

没有硬依赖 Zustand。采用 "Service + Hook + 全局单例" 的模式：

- `services/auth.ts` — 登录/注册/me + token 持久化
- `services/subscription.ts` — 订阅源 CRUD
- `services/report.ts` — 报告列表/详情/生成
- `store/userStore.ts` — 用户状态 Hook（`useAuthenticated()` / `useUser()`）
- `hooks/useAuth.ts` / `useSubscriptions.ts` / `useReports.ts`

### 4.4 组件设计

```
Layout/           Header / Sidebar / Footer（通用壳）
Subscription/     SourceTypeSelector / SubscriptionForm / SubscriptionList（订阅源 UI）
Report/           ReportCard / ReportContent / ReportTimeline（报告相关组件）
Common/           Empty / Loading（通用占位）
```

### 4.5 前端亮点

- **Vite 代理**：`/api` → `http://localhost:8000`，无需 CORS 预检
- **Tailwind 驱动**：零自定义 CSS 文件（仅保留 `styles/globals.css` 做全局 reset）
- **路由守卫**：未登录自动跳 `/login`，`/login` 已登录自动跳 `/`
- **报告 Markdown 渲染**：`react-markdown` + 自定义 code/heading 样式

---

## 5. 三层混合记忆模块

> 这是 DailyFeed 区别于普通抓取脚本的核心部分。

### 5.1 设计思路

传统 Agent 系统常让每个 Agent 独立维护自己的"记忆"，导致三个问题：

1. **资源冗余**：相同知识被重复存储
2. **协作断裂**：一个 Agent 知道的用户偏好，另一个不知道
3. **一致性风险**：并发写时互相覆盖

DailyFeed 的解法是**"分层存储 + 路由访问"**：

```
                    ┌────────────────────────────────────┐
                    │        MemoryRouter（统一入口）     │
                    │  ── ACL（Agent 读/写权限声明）      │
                    │  ── 跨层 query() 合并结果          │
                    └──────────┬──────────┬──────────────┘
                               │          │
              ┌────────────────┼──────┐   │   ┌────────────┐
              ▼                ▼      │   │   ▼            │
     GlobalShared 层       SessionIsolated 层   TaskSpecific 层
   ┌──────────────────┐  ┌───────────────┐  ┌─────────────┐
   │ PreferenceStore  │  │ ShortTermMem  │  │ TaskMemBuf  │
   │  关键词偏好      │  │  对话 ringbuf │  │  任务步骤    │
   │  渠道偏好        │  │  session-bound│  │  task-bound │
   │  阅读反馈统计    │  │               │  │             │
   │                  │  │               │  │  GraphMem   │
   │ LongTermMemory  │  │               │  │  实体-关系  │
   │  向量检索        │  │               │  │  全局图+子图│
   └──────────────────┘  └───────────────┘  └─────────────┘
```

### 5.2 各层实现要点

#### GlobalShared 层：持久化 + 跨 Agent 共享

- **`PreferenceStore`**（`preference_store.py`）
  
  - 使用户级 KV 偏好。字段包括：`like_keywords / dislike_keywords / preferred_channels / preferred_push_hour / email_recipients / summary_style / total_reports / opened_reports / extra`
  - **写时事件机制**：`on_update(callback)` 让 `LifecycleManager` 能订阅并同步到 LTM
  - **SQLite UPSERT**：单条语句保证原子性，多进程并发安全
  - **内存缓存**：同一次请求内多次读不打数据库（首次写后缓存失效）

- **`LongTermMemory`**（`long_term_memory.py`）
  
  - **双索引**：内存热点索引（dict，高频读写）+ 数据库持久化（SQLite/PostgreSQL）
  - **伪向量降级**：没有 LLM embedding 服务时，用"关键词哈希 → 固定维度向量 → 余弦相似度"做基础检索。这保证系统在没有 API key 时也能运行
  - **打分函数**：`score = cosine × (0.5 + 0.3 × importance/5 + 0.2 × recency_factor)`
    - importance：用户偏好类记忆 4/5，报告摘要 4/5，任务摘要 3/5
    - recency：`1/(1 + days/7)`（7 日内近似 1.0，一月后衰减到 ~0.3）
  - **TTL 语义**：报告 30 天，偏好 14 天，任务摘要 7 天

#### SessionIsolated 层：短上下文（对话场景）

- **`ShortTermMemory`**（`short_term_memory.py`）
  - 每个 session 独立 `deque(maxlen=20)` ring buffer
  - 支持 Agent 名标记 + 角色标记（user/agent/tool）
  - 可直接格式化为 prompt 文本（`as_prompt(limit=10)`）
  - TTL = 2 小时无访问（超过即由 LifecycleManager 清理）
  - session 关闭即销毁，避免跨会话干扰

#### TaskSpecific 层：任务记忆 + 实体关系图

- **`TaskMemBuf`**（`task_buf.py`）
  
  - 每个任务：`TaskStep[]` + 状态（running/done/failed）
  - 步骤包含：`phase / description / payload(dict) / duration_ms / status`
  - 任务结束自动把高重要性 step 升档到 LTM（LifecycleManager）

- **`GraphMem`**（`graph_mem.py`）
  
  - 全局图：实体 → 关系 → 实体，带 weight + count
  - **边权重学习**：每次同现增强 weight，`w = 1 - 1/(1 + 0.3*log(count))`（S 曲线，逼近 0.95）
  - SubGraph 从全局图检索 + 私有节点，避免一次任务污染全局
  - 检索时支持**多跳扩散**（hops=2，从种子节点遍历邻居，合并后按得分排序）
  - 典型用法：从 "AI" → 推理相关 "GPU/PyTorch/Transformer/LLM"

### 5.3 MemoryRouter：统一入口

核心 API（对应文件 [`memory_router.py`](file:///d:/agent/dailyfeed/backend/internal/memory/memory_router.py)）：

```python
router = get_memory_router(db)

# 声明 Agent 权限（可选，默认全放行）
router.declare_agent(
    "scheduler",
    global_shared=AccessLevel.READ_WRITE,
    session_isolated=AccessLevel.NONE,
    task_specific=AccessLevel.READ_WRITE,
)

# 读/写偏好
pref = router.get_preference(user_id=1)
router.set_preference(1, "like_keywords", ["AI", "GPU"])

# 长期记忆（向量检索）
router.remember_long_term(MemoryKind.LTM, "报告内容...", user_id=1,
                          tags=["report"], importance=MemoryImportance.HIGH,
                          ttl_seconds=86400*30)
items = router.retrieve_long_term("AI 摘要", user_id=1, top_k=5)

# 短期对话
sid = router.open_session(user_id=1)
router.add_user_message(sid, "想看 AI 相关内容")
router.add_agent_message(sid, "好的，我为您生成了摘要")
context = router.session_context(sid, limit=10)

# 任务步骤
task_id = router.start_task("pipeline_service", user_id=1)
router.log_step(task_id, "fetch", "抓取了 20 条 GitHub trending")
router.log_step(task_id, "summarize", "完成摘要")

# 图推理
router.add_cooccurrence(["AI", "GPU", "CUDA"])
related = router.infer_related(["AI"], hops=2, limit=8)  # → [("GPU", 0.7), ...]

# 跨层高级查询
result = router.query(
    "用户今天想看什么？",
    user_id=1,
    session_id=sid,
    layers=(LAYER_GLOBAL, LAYER_SESSION, LAYER_TASK),
    top_k=8,
)
# result.items    — MemoryItem[]（pref + ltm + stm）
# result.pref     — UserPreference
# result.as_context(max_chars=2000)  — 可直接拼进 prompt
```

### 5.4 ACL 与权限隔离

每个 Agent 通过 `declare_agent()` 声明自己在三层的访问权限：

- **`scheduler`**：可读可写 GlobalShared（设置定时策略），可读写 TaskSpecific（启动/结束任务）
- **`pipeline_service`**：三层全读写（主处理 Agent）
- **只读展示 Agent**：仅 GlobalShared READ
- **`AccessDeniedError`**：越权访问时抛出异常，被 router 捕获并记录日志

### 5.5 生命周期管理

`LifecycleManager` 是一个**可选后台线程**（不阻塞主进程，不启动也能运行）：

```python
lm = get_lifecycle_manager(db, auto_start=False)  # 不自动启动
lm.start(interval_seconds=300)                     # 每 5 分钟跑一次 tick()
# tick() 做：
#   1) 清理过期 session（STM）
#   2) 清理过期 task（TaskMemBuf）
#   3) 清理过期 LTM 条目
#   4) 把图中高权重边升档到 LTM
#   5) 把偏好写进 LTM（事件驱动：PreferenceStore.on_update）
lm.stop()
```

---

## 6. 数据抓取

### 6.1 GitHub Trending

- **数据源**：`https://github.com/trending?since={daily|weekly|monthly}`
- **实现**：`pipeline/fetcher/github.py` + `infrastructure/external/github_client.py`
- **核心挑战**：GitHub 官方不提供 JSON API，必须解析 HTML
- **解析策略**：
  - 用浏览器 UA（`Mozilla/5.0 ...`）发送请求（避免 406）
  - 解析 `<article class="Box-row">` 提取：项目 owner/name、描述、语言、Star/Fork 数、今日新增 Star、URL
- **去重**：取 `{owner}/{repo}` 作为唯一键
- **关键词提取**：从 description + language → 分词 → 送入 GraphMem 建立实体关联

### 6.2 GitHub Top-starred

- **数据源**：GitHub Search API `https://api.github.com/search/repositories?q=stars:>10000+language:python&sort=stars&order=desc`
- **查询 DSL**：`topstarred:{min_stars}` / `topstarred:{min_stars}/{language}`
- **无需 token**（匿名 60 次/小时，足够 MVP）
- **同样做关键词提取**，和 trending 的关键词混合训练 GraphMem

### 6.3 Bilibili（B站）

- **数据源**：UP 主视频列表
- **挑战**：官方 API 可能返回 429/412 等风控状态
- **容错**：失败时自动跳过（不阻塞整个 pipeline）
- **未来可扩展**：接入 RSSHub `/bilibili/user/video/{uid}`

### 6.4 RSS / Atom

- 通用 feedparse 处理（依赖 `feedparser` 库，解析后提取 title/description/pubDate/link）

---

## 7. LLM 摘要

### 7.1 主方案：Qwen（通义千问）+ OpenAI 兼容

- **提供者注册**：`pipeline/summarizer/provider/`（抽象基类 `BaseProvider` + HTTP 实现）
- **Qwen 使用路径**：
  - `settings.llm_provider == "qwen"`
  - 端点：`https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`（OpenAI 兼容协议）
  - 模型：`qwen-plus`
- **OpenAI 使用路径**：
  - `settings.llm_provider == "openai"`
  - 端点：`https://api.openai.com/v1/chat/completions`
  - 模型：`gpt-4o-mini`（默认）
- **prompt 设计**：
  
  ```
  You are a tech content summarizer.
  Title: {title}
  Content: {content[:3000]}
  Please produce a concise 中文摘要 in 3 bullet points.
  Focus on key features, main purpose, and why it matters.
  ```

### 7.2 降级方案：Extractive 摘要（无 LLM 也能跑）

- **TextRank 式算法**（`pipeline/summarizer/extractive.py`）
- 步骤：中文分词 → 句子拆分 → tf 得分 → 选 top-3 句子
- **自动降级**：LLM 调用失败（超时 / API 错误 / 无 key）→ 走 extractive，报告中以 `[摘要：非 LLM]` 标记
- **摘要缓存**（`summarizer/cache.py`）：相同 title+content 24h 内不再重复生成，节省 token + 时间

### 7.3 摘要写入数据库

`summary_repo.create(SummaryModel(content_id=..., text=..., generated_by="qwen"))`，
并在 report 中以 Markdown list 形式聚合展示。

---

## 8. 推送系统

### 8.1 多渠道抽象

`pipeline/pusher/notifier.py` 根据用户 `preferences.preferred_channels` 选择要推送的渠道：

```python
async def push(report, user):
    for ch in user.settings.get("channels", []):
        try:
            if ch == "email":      await email_pusher.push(report, user)
            if ch == "wechat":     await wechat_pusher.push(report, user)
            if ch == "dingtalk":   await dingtalk_pusher.push(report, user)
        except Exception as e:
            logger.error(f"push({ch}) failed: {e}")
```

每个渠道有自己的模块：

- **`email.py`**：`smtplib` + MIME（纯文本 + HTML 多部分），可配置 `SMTP_HOST / SMTP_USER / SMTP_PASSWORD / SMTP_PORT`
- **`wechat.py`**：企业微信群机器人 Webhook（HTTP POST JSON）
- **`dingtalk.py`**：钉钉群机器人 Webhook（同样 HTTP POST JSON，支持加签）
- **`notifier.py`**：通用抽象，路由 + 聚合状态

### 8.2 失败不阻塞

任何单一推送渠道失败不会影响报告生成和其他渠道。失败在 `push_logs` 表记录，供前端/后台查看。

---

## 9. API 设计与鉴权

### 9.1 主路由

| 方法       | 路径                         | 功能                      | 认证  |
| -------- | -------------------------- | ----------------------- | --- |
| POST     | `/api/auth/register`       | 邮箱+密码注册 → 返回 token      | ✗   |
| POST     | `/api/auth/login`          | 登录 → 返回 JWT             | ✗   |
| GET      | `/api/auth/me`             | 当前用户信息                  | ✓   |
| GET      | `/api/subscriptions`       | 当前用户订阅源列表               | ✓   |
| POST     | `/api/subscriptions`       | 添加订阅源                   | ✓   |
| PUT      | `/api/subscriptions/{id}`  | 更新订阅源                   | ✓   |
| DELETE   | `/api/subscriptions/{id}`  | 删除订阅源                   | ✓   |
| GET      | `/api/reports`             | 报告列表（按时间倒序）             | ✓   |
| GET      | `/api/reports/{id}`        | 报告详情                    | ✓   |
| **POST** | **`/api/reports/run-now`** | **立即生成一次报告**（完整流水线）     | ✓   |
| PUT      | `/api/users/me/settings`   | 更新用户设置（推送渠道/邮箱/Webhook） | ✓   |
| GET      | `/health`                  | 健康检查                    | ✗   |

### 9.2 JWT 鉴权

- **算法**：HS256（对称）
- **Secret**：`settings.secret_key`（由 `.env` 配置，默认开发用占位值）
- **Token 结构**：`{"sub": user_id, "iat": ts, "exp": ts + 7d}`
- **验证中间件**：`Authorization: Bearer <token>` → 解析 → 查用户 → 注入 request.state.user
- **过期**：7 天（长会话，MVP 阶段方便调试）

### 9.3 响应格式

统一 JSON：

```json
{
  "data": {...},          // 具体数据
  "message": "ok",        // 可读消息
  "ok": true              // 成功/失败
}
```

`run-now` 的响应示例：

```json
{
  "ok": true,
  "report_id": 42,
  "title": "每日摘要 - 2026-06-21",
  "pushed_channels": ["email"],
  "seconds": 68.3,
  "memory_used": {
    "preference": {"keywords": ["AI", "GPU"], "style": "balanced"},
    "ltm_items_stored": 20,
    "task_steps": 5
  }
}
```

---

## 10. 关键设计决策与亮点

### 10.1 SQLite 自动回退（PostgreSQL 不可用时）

`internal/infrastructure/database/session.py::_init_engine()`：

- 先尝试用配置中的 PostgreSQL（如果 `settings.database_url` 以 `postgresql://` 开头且 psycopg2 存在）
- **连接失败** → 自动切到 `sqlite:///./dailyfeed.db`
- 日志中打印"primary database connect failed → falling back to SQLite"
- 效果：本地开发无需装 PostgreSQL，开箱即用

### 10.2 LLM 摘要的两层容错

```
第一次尝试: Qwen / OpenAI （真实 API 调用）
     ↓ 超时 / 网络 / API 错误
第二次尝试: 抽取式摘要（纯本地，零依赖）
     ↓ 仍失败
第三次: 简单截断（取 content 前 200 字符）
```

保证 pipeline 永远不会因摘要失败而中断。

### 10.3 记忆模块的"热/冷"双存储设计

- **热存储**：内存 dict / deque（微秒级读写，高频命中）
- **冷存储**：SQLite/PostgreSQL（持久化，重启恢复）
- **策略**：新数据先写热，再异步落库；读先查热，miss 再查库

### 10.4 PipelineService 作为单入口

让整个系统的"主流程"只有一个公开函数：

```python
result = await PipelineService(db).run_pipeline(user_id=uid)
```

这个设计使：

1. **可观测性强**：只需要在一处加日志/计时/监控
2. **可测试性好**：所有子模块通过依赖注入，测试时可替换
3. **可扩展性好**：未来切回 Swarm，只需把这个函数改成"发消息到 MQ"

### 10.5 前端代理转发（零 CORS 痛苦）

前端 `vite.config.ts`：

```ts
proxy: { "/api": "http://localhost:8000" }
```

效果：开发时所有前端请求访问 `http://localhost:5173/api/*`，Vite 自动转发到后端，
浏览器永远不会触发 CORS。

### 10.6 全中文可读的日志与错误信息

- 日志统一用 `internal.infrastructure.monitoring.logger`
- 每个关键步骤（抓取/摘要/聚合/推送）都有明确日志
- 错误信息包含：用户/订阅源/步骤/耗时/错误详情，方便快速定位

### 10.7 关键词 → 实体关系图 → 内容相关性排序

这是记忆模块最有价值的一条链：

1. **采集**：每个 report 中的内容 title 被分词 → 送入 GraphMem
2. **学习**：跨多次 report 累积边权重（今天和昨天都提到 "AI + GPU" → 权重增高）
3. **推理**：`infer_related(["AI"])` → 返回系统当前识别的相关关键词列表
4. **应用**：把推理结果返回给 ReportBuilder，用于调整摘要排序（**偏好相关的内容置顶**）
5. **持久化**：高权重边在 `LifecycleManager.tick()` 时被写入 LTM，跨重启保留

这条链路让 DailyFeed 在"持续使用"中持续积累对**你**的了解，而不是对**所有用户相同的一套静态规则**。

---

## 11. 快速开始

### 11.1 后端（Python 3.10+）

```bash
cd dailyfeed/backend
pip install -r requirements.txt

# 复制配置
cp .env.example .env

# 运行开发服务器（FastAPI，http://localhost:8000）
python run_server.py

# API 文档
# 浏览器打开 http://localhost:8000/docs
```

### 11.2 前端（Node.js 18+）

```bash
cd dailyfeed/frontend
npm install
npm run dev
# 浏览器打开 http://localhost:5173
```

### 11.3 一键联调（生产模式）

```bash
# 根目录
cd dailyfeed
make up   # docker-compose up（包含 postgres + api + frontend + nginx）
```

### 11.4 运行测试

```bash
cd dailyfeed/backend
python test_memory_smoke.py          # 记忆模块 7 个子用例
python test_pipeline_integration.py  # pipeline + memory 端到端
```

---

## 12. 目录结构

```
dailyfeed/
├── backend/                       # FastAPI + Python 后端
│   ├── api/                       # API handlers & schemas
│   │   └── main.py                # 应用入口
│   ├── internal/
│   │   ├── orchestrator/          # pipeline_service + message_bus
│   │   ├── domain/                # entities + value objects (DDD)
│   │   ├── pipeline/              # fetcher/summarizer/aggregator/pusher
│   │   ├── memory/                # ★ 三层混合记忆模块
│   │   ├── infrastructure/        # database/external/cache/monitoring
│   │   ├── config/                # settings.py + config.yaml
│   │   ├── agent/                 # 5 Agent 模块（可独立进程）
│   │   └── utils/
│   ├── tests/
│   ├── test_memory_smoke.py       # ★ 记忆模块单元测试（7/7 通过）
│   ├── test_pipeline_integration.py # ★ pipeline+memory 端到端测试
│   ├── run_server.py              # 开发服务器入口
│   ├── requirements.txt
│   ├── .env.example
│   └── Dockerfile
│
├── frontend/                      # React + TypeScript + Vite
│   ├── src/
│   │   ├── pages/                 # 7 个页面（Dashboard/Subscriptions/Reports/ReportDetail/Settings/Login/Register）
│   │   ├── components/            # Layout/Report/Subscription/Common
│   │   ├── services/              # api/auth/report/subscription
│   │   ├── store/                 # userStore / subscriptionStore
│   │   ├── hooks/                 # useAuth / useSubscriptions / useReports
│   │   └── types/                 # TypeScript 接口
│   ├── package.json               # vite 5 / react 18 / tailwindcss 3
│   ├── vite.config.ts             # /api proxy → localhost:8000
│   └── tsconfig.json
│
├── nginx/                         # 反向代理配置
├── .env.example                   # 顶层 env 示例（LLM_KEY / SMTP / DB）
├── docker-compose.yml             # 完整服务编排
├── Makefile
└── README.md
```

---

## 13. 未来扩展方向

1. **真实向量数据库替换伪向量**：接入 Chroma / Milvus，把 `LongTermMemory` 的伪向量替换成真正的 LLM embedding
2. **Agent 化（分布式）**：用 `message_bus.py` 为基础，把 5 个 Agent 切成独立进程/容器，通过 Redis Stream 通信
3. **智能排序**：基于 `UserPreference.total_reports / opened_reports` 的打开率回归，自动提升"高打开率"订阅源的摘要长度
4. **摘要风格个性化**：根据用户的 `summary_style`（brief / balanced / detailed）动态调整 prompt
5. **移动端推送**：接入 Firebase Cloud Messaging / Bark，做移动端通知
6. **RSSHub 路由**：让订阅源支持任意 RSSHub 路由（抖音/知乎/微博/...）
7. **用户反馈闭环**：让用户在报告详情页给每条摘要打"有用/没用"，
   训练偏好权重，并在次日报告中调整排序
8. **多用户/多租户**：当前所有记忆模块都带 `user_id`，天然支持多用户；
   加一层 project/team 即可变成 SaaS
9. **Webhook 订阅/转发**：支持用户把报告 POST 到自己的 API
10. **内容查重**：跨多天报告做去重，避免重复主题

---

**License**：MIT  
**主要语言**：Python (后端) · TypeScript (前端)  
**核心依赖**：FastAPI · SQLAlchemy · Pydantic · requests · feedparser · Vite · React · Tailwind CSS

---

> 每日自动抓取 → 理解你的兴趣 → 高质量摘要 → 定时推送。
> 这就是 DailyFeed。
