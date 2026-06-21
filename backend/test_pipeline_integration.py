"""验证 pipeline_service + memory 模块的集成能工作。"""

import asyncio
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from internal.infrastructure.database.session import init_db, get_session
from internal.infrastructure.database.repositories.subscription_repo import SubscriptionRepository
from internal.infrastructure.database.models import SubscriptionModel
from internal.orchestrator.pipeline_service import PipelineService


async def main() -> None:
    print("=" * 60)
    print("  pipeline_service + memory 集成测试")
    print("=" * 60)

    init_db()
    user_id = 99  # 测试用户

    with get_session() as db:
        sub_repo = SubscriptionRepository(db)
        existing = sub_repo.list_by_user(user_id=user_id)
        if not existing:
            for _ in range(2):
                s = SubscriptionModel(
                    user_id=user_id, source_type="github",
                    source_url="trending:daily", priority=3, is_active=True,
                    config={},
                )
                sub_repo.create(s)
        print(f"✓ 测试订阅源: {len(sub_repo.list_by_user(user_id=user_id))} 个")

        service = PipelineService(db)
        print(f"✓ PipelineService 已接入 memory router")
        print(f"  memory router: {id(service.memory)}")
        print(f"  lifecycle manager: {id(service.lifecycle) if service.lifecycle else None}")

        # 先写入偏好（验证偏好→报告流程）
        service.memory.set_preference(user_id, "like_keywords",
                                       ["AI", "GPU", "Python"], agent_name="pipeline_service")
        service.memory.set_preference(user_id, "preferred_channels",
                                       ["email"], agent_name="pipeline_service")
        print("✓ 偏好已写入 GlobalShared 层")

        print("\n▶ 开始执行流水线（短版，抓取 1 个源）...")
        result = await service.run_pipeline(user_id=user_id)
        print(f"✓ 完成 report_id={result['report_id']} title={result['title']}")
        print(f"  stats keys: {list(result.get('stats', {}).keys())}")
        print(f"  memory stats: preference.keywords={result['stats'].get('preference', {}).get('like_keywords')}")

        # 查询 memory：确保 LTM 中能读到该报告
        ltm_items = service.memory.retrieve_long_term(
            "报告 摘要", user_id=user_id, top_k=5, agent_name="pipeline_service"
        )
        print(f"\n✓ LTM 中检索到 {len(ltm_items)} 条与报告相关的记忆")
        for item in ltm_items[:3]:
            snippet = item.content[:70].replace("\n", " ")
            print(f"  - [{item.kind.value}] importance={item.importance} tags={item.tags[:4]}")
            print(f"    {snippet}...")

        # 生命周期维护
        if service.lifecycle:
            tick_stats = service.lifecycle.tick(force=True)
            print(f"\n✓ 生命周期管理器 tick: {tick_stats}")

    print("\n" + "=" * 60)
    print("  集成测试完成 ✓")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
