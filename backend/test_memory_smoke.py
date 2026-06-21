"""记忆模块冒烟测试 - 验证三层混合记忆架构能工作。

运行方式:
    python backend/test_memory_smoke.py
    # 或
    cd backend && python test_memory_smoke.py
"""

from __future__ import annotations

import asyncio
import sys
import os

# 确保 backend 包可导入
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from internal.memory import (
    get_memory_router,
    get_lifecycle_manager,
    MemoryKind,
    MemoryImportance,
    AccessLevel,
    LAYER_GLOBAL,
    LAYER_SESSION,
    LAYER_TASK,
    SessionNotFoundError,
    TaskNotFoundError,
    AccessDeniedError,
)
from internal.memory.base import MemoryItem


def green(msg: str) -> str:
    return f"\033[32m✓ {msg}\033[0m"


def yellow(msg: str) -> str:
    return f"\033[33m● {msg}\033[0m"


def red(msg: str) -> str:
    return f"\033[31m✗ {msg}\033[0m"


def print_header(title: str) -> None:
    bar = "=" * 60
    print(f"\n{bar}")
    print(f"  {title}")
    print(bar)


# ====================== 1. Router 初始化 + ACL ======================
def test_01_router_and_acl() -> None:
    print_header("Test 01: MemoryRouter + ACL")

    router = get_memory_router(db_session=None)

    # 声明一个受限 Agent（只读 GlobalShared，不可写）
    router.declare_agent(
        "readonly_agent",
        global_shared=AccessLevel.READ,
        session_isolated=AccessLevel.NONE,
        task_specific=AccessLevel.NONE,
    )

    # 声明全权限 Agent
    router.declare_agent(
        "full_agent",
        global_shared=AccessLevel.READ_WRITE,
        session_isolated=AccessLevel.READ_WRITE,
        task_specific=AccessLevel.READ_WRITE,
    )
    print(green("Router 初始化完成，声明了 2 个 Agent"))

    # 全权限写 LTM
    router.remember_long_term(
        MemoryKind.LTM,
        "本文介绍了大模型驱动的信息摘要流水线，从抓取、LLM 摘要到邮件推送。",
        user_id=1,
        tags=["AI", "LLM", "pipeline"],
        importance=MemoryImportance.HIGH,
        agent_name="full_agent",
    )
    print(green("full_agent 写入 LTM 1 条"))

    # 测试 ACL 拒绝写操作
    denied = False
    try:
        router.remember_long_term(MemoryKind.LTM, "test", user_id=1,
                                    agent_name="readonly_agent")
    except AccessDeniedError:
        denied = True
    assert denied, "readonly_agent 应被拒绝写 LTM"
    print(green("readonly_agent 被正确拒绝写 LTM"))

    # 测试 ACL 允许读
    items = router.retrieve_long_term("摘要流水线", user_id=1, top_k=3,
                                       agent_name="readonly_agent")
    print(yellow(f"readonly_agent 成功读取 LTM，返回 {len(items)} 条"))


# ====================== 2. 用户偏好（PreferenceStore） ======================
def test_02_preference() -> None:
    print_header("Test 02: PreferenceStore（全局共享层）")

    router = get_memory_router(db_session=None)

    # 读写偏好
    pref_before = router.get_preference(user_id=1)
    print(yellow(f"初始 preference: like_keywords={pref_before.like_keywords}"))

    router.set_preference(1, "like_keywords", ["AI", "GPU", "Python"],
                           agent_name="full_agent")
    router.set_preference(1, "preferred_channels", ["email"],
                           agent_name="full_agent")
    router.set_preference(1, "summary_style", "concise", agent_name="full_agent")

    pref_after = router.get_preference(user_id=1)
    assert "AI" in pref_after.like_keywords, "关键词应该被设置"
    print(green("偏好设置成功: keywords=%s, channels=%s, style=%s" % (
        pref_after.like_keywords, pref_after.preferred_channels, pref_after.summary_style,
    )))

    # 偏好能被转换为 MemoryItem
    pref_items = list(router.get_preference(user_id=1).__class__.__dict__.keys())
    print(yellow(f"preference 对象字段: {[k for k in pref_items if not k.startswith('_')][:6]}"))


# ====================== 3. STM（会话隔离层） ======================
def test_03_stm() -> None:
    print_header("Test 03: ShortTermMemory（会话隔离层）")

    router = get_memory_router(db_session=None)
    session_id = router.open_session(user_id=1, agent_name="full_agent")

    # 写入多轮对话
    router.add_user_message(session_id, "帮我看看今天的 AI 新闻", agent_name="full_agent")
    router.add_agent_message(session_id, "我来为您抓取今日热点", agent_name="full_agent")
    router.add_user_message(session_id, "关注 GPU 相关内容", agent_name="full_agent")
    router.add_agent_message(session_id, "已生成 AI/GPU 相关摘要", agent_name="full_agent")

    context = router.session_context(session_id, limit=10, agent_name="full_agent")
    print(yellow(f"会话上下文（{len(context)} 字符）:"))
    for line in context.split("\n")[:4]:
        print(f"  {line}")

    # 测试 SessionNotFoundError：不存在的 session
    try:
        router.session_context("non-existent-session", agent_name="full_agent")
        assert False, "应该抛出 SessionNotFoundError"
    except SessionNotFoundError:
        print(green("正确拒绝访问不存在的 session"))


# ====================== 4. TaskMemBuf（任务专属层） ======================
def test_04_task_buf() -> None:
    print_header("Test 04: TaskMemBuf（任务步骤缓冲）")

    router = get_memory_router(db_session=None)

    task_id = router.start_task("pipeline_service", user_id=1, agent_name="full_agent")
    print(yellow(f"创建任务: {task_id}"))

    router.log_step(task_id, "fetch", "抓取 GitHub Trending 15 条",
                     payload={"source": "github_trending", "count": 15},
                     agent_name="full_agent")
    router.log_step(task_id, "fetch", "抓取 top-starred 10 条",
                     payload={"source": "github_top", "count": 10},
                     agent_name="full_agent")
    router.log_step(task_id, "summarize", "完成 25 条内容摘要",
                     payload={"count": 25, "provider": "qwen"},
                     agent_name="full_agent")
    router.log_step(task_id, "aggregate", "聚合生成 Markdown 报告",
                     payload={"chars": 3200}, agent_name="full_agent")
    router.log_step(task_id, "push", "尝试推送（未配置邮箱）",
                     payload={"channel": "email", "status": "skipped"},
                     agent_name="full_agent")

    task = router.get_task(task_id, agent_name="full_agent")
    steps = task.steps()
    print(green(f"任务完成，共 {len(steps)} 个步骤"))
    for step in steps[:3]:
        print(f"  - [{step.phase}] {step.description} ({step.duration_ms}ms)")

    # 错误场景：访问不存在的 task
    try:
        router.get_task("no-such-task", agent_name="full_agent")
        assert False
    except TaskNotFoundError:
        print(green("正确拒绝访问不存在的 task"))


# ====================== 5. GraphMem（实体关系图） ======================
def test_05_graph() -> None:
    print_header("Test 05: GraphMem（实体关系图）")

    router = get_memory_router(db_session=None)

    # 注入几组关键词
    router.add_cooccurrence(["AI", "GPU", "CUDA", "Python", "LLM"],
                             agent_name="full_agent")
    router.add_cooccurrence(["web", "frontend", "React", "TypeScript", "Node"],
                             agent_name="full_agent")
    router.add_cooccurrence(["AI", "transformer", "attention", "deep-learning"],
                             agent_name="full_agent")

    # 从"AI"出发查询关联
    related = router.infer_related(["AI"], hops=2, limit=8, agent_name="full_agent")
    print(yellow(f"以 'AI' 为种子的相关关键词（{len(related)} 个）:"))
    for name, score in related[:6]:
        print(f"  - {name}: {score:.3f}")

    assert len(related) > 0, "至少应该返回一些相关关键词"
    print(green("图推理完成"))


# ====================== 6. 跨层高级查询 ======================
def test_06_query() -> None:
    print_header("Test 06: 跨层 Query（三层混合）")

    router = get_memory_router(db_session=None)

    # 先在 STM 中加一段对话上下文
    sid = router.open_session(user_id=1, agent_name="full_agent")
    router.add_user_message(sid, "我想看看今天的 AI 和 GPU 相关内容", agent_name="full_agent")
    router.add_agent_message(sid, "好的，我为您检索今日热点，并结合您的长期兴趣排序", agent_name="full_agent")

    # 跨层查询：Global + Session
    result = router.query(
        "AI GPU 摘要",
        user_id=1,
        session_id=sid,
        layers=(LAYER_GLOBAL, LAYER_SESSION),
        top_k=8,
        agent_name="full_agent",
    )

    print(yellow(f"跨层查询返回 {len(result)} 条记忆，来源:"))
    for layer_name, count in result.sources.items():
        print(f"  - {layer_name}: {count} 条")

    # 打印 prompt 上下文
    ctx = result.as_context(max_chars=400)
    print(yellow("可拼进 prompt 的上下文（前 300 字符）:"))
    print(f"  {ctx[:250]}...")

    # 偏好应该被拉到
    if result.pref is not None:
        print(green(f"用户偏好可用: {len(result.pref.like_keywords)} 关键词"))
    print(green("跨层查询完成"))


# ====================== 7. Lifecycle Manager ======================
def test_07_lifecycle() -> None:
    print_header("Test 07: Lifecycle Manager（周期维护）")

    lifecycle = get_lifecycle_manager(db_session=None, auto_start=False)
    stats = lifecycle.tick(force=True)
    print(yellow(f"手动 tick() 结果: {stats}"))

    # 健康摘要
    snapshot = lifecycle.snapshot()
    print(yellow(f"各模块健康摘要:"))
    for key, value in snapshot.items():
        print(f"  - {key}: {value}")

    print(green("生命周期管理器工作正常"))


# ====================== 主入口 ======================
def main() -> int:
    print("\n" + "=" * 60)
    print("  DailyFeed 记忆模块（三层混合）冒烟测试")
    print("=" * 60)

    tests = [
        test_01_router_and_acl,
        test_02_preference,
        test_03_stm,
        test_04_task_buf,
        test_05_graph,
        test_06_query,
        test_07_lifecycle,
    ]

    passed = 0
    failed = 0
    for idx, fn in enumerate(tests, 1):
        try:
            fn()
            passed += 1
        except AssertionError as exc:
            print(red(f"{fn.__name__} 断言失败: {exc}"))
            failed += 1
        except Exception as exc:
            print(red(f"{fn.__name__} 异常: {type(exc).__name__}: {exc}"))
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"  结果: {passed}/{passed + failed} 通过" +
          (f"，{failed} 失败" if failed else "，全部通过"))
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
