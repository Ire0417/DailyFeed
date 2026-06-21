"""查看现有账号，或创建初始账号。"""
import sys

sys.path.insert(0, ".")

from sqlalchemy import text
from internal.infrastructure.database.session import init_db, get_session
from internal.infrastructure.database.repositories.user_repo import UserRepository
from internal.infrastructure.database.models import UserModel
import datetime
import hashlib
import secrets


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(8)
    hashed = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
    ).hex()
    return f"{salt}${hashed}"


def show_users(db):
    result = db.execute(
        text("SELECT id, username, email, is_active FROM users ORDER BY id")
    )
    users = [dict(r) for r in result.mappings()]
    print("=" * 60)
    print(f"现有账号 ({len(users)} 个):")
    if not users:
        print("  (空)")
    for u in users:
        print(f'  id={u["id"]:>2}  username={u["username"]:<15}  email={u["email"]:<30}  active={u["is_active"]}')
    print("=" * 60)
    return users


def create_user(db, username: str, email: str, password: str):
    user_repo = UserRepository(db)
    if user_repo.get_by_email(email.lower()):
        print(f"⚠️  邮箱 {email} 已存在，跳过创建")
        return None
    if user_repo.get_by_username(username):
        print(f"⚠️  用户名 {username} 已存在，跳过创建")
        return None
    user = UserModel(
        username=username,
        email=email.lower(),
        password_hash=_hash_password(password),
        is_active=True,
        settings={
            "channels": ["email"],
            "email_recipients": [email.lower()],
        },
        created_at=datetime.datetime.utcnow(),
        updated_at=datetime.datetime.utcnow(),
    )
    created = user_repo.create(user)
    print(f"✅ 创建账号: id={created.id} username={username} email={email}")
    return created


if __name__ == "__main__":
    init_db()

    with get_session() as db:
        show_users(db)

        # 如果没有任何账号 → 创建默认演示账号
        # 有命令行参数 → 创建自定义账号
        if len(sys.argv) >= 4:
            username, email, password = sys.argv[1], sys.argv[2], sys.argv[3]
            create_user(db, username, email, password)
            show_users(db)
        elif not sys.argv[1:2] == ["--check-only"]:
            # 没有账号时自动创建一个默认账号
            users = db.execute(text("SELECT count(*) as cnt FROM users")).scalar()
            if users == 0:
                print("\n🚀 数据库为空，创建初始账号...")
                create_user(db, "admin", "admin@dailyfeed.local", "admin1234")
                print("\n📋 初始账号信息:")
                print("   用户名: admin")
                print("   邮箱  : admin@dailyfeed.local")
                print("   密码  : admin1234")
                print("\n   💡 提示: 登录后请立即在 '设置' 页面修改邮箱为真实邮箱")
                print("   💡 提示: 也可以在前端注册页面创建新账号")
            else:
                print("\nℹ️  已有账号，如需创建新账号:")
                print("   python init_user.py <用户名> <邮箱> <密码>")
                print("   或在前端注册页面直接注册")
