"""
Auth handlers - 注册、登录、token 验证。
"""
import re
import secrets
import hashlib
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel

from internal.config.settings import settings
from internal.infrastructure.database.session import get_db
from internal.infrastructure.database.repositories.user_repo import UserRepository
from internal.infrastructure.database.models import UserModel

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _is_email(s: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s.strip()))


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


# ---------- helpers ----------
def _hash_password(password: str) -> str:
    salt = secrets.token_hex(8)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"{salt}${hashed.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, hashed = stored.split("$", 1)
    except Exception:
        return False
    computed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()
    return computed == hashed


def _make_token(user_id: int) -> str:
    # Simple, short-lived self-contained token (signed by app secret).
    # For Phase 1, we use an HS256 JWT produced by hand via PyJWT if available;
    # otherwise fall back to a simpler token structure.
    payload = {
        "sub": user_id,
        "iat": int(datetime.utcnow().timestamp()),
        "exp": int((datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()),
    }
    try:
        import jwt  # PyJWT
        return jwt.encode(payload, settings.secret_key, algorithm="HS256")
    except Exception:
        # Fallback: naive signed token
        import json
        import base64
        data = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
        sig = hashlib.sha256(f"{data}.{settings.secret_key}".encode("utf-8")).hexdigest()
        return f"{data}.{sig}"


def _decode_token(token: str) -> dict | None:
    try:
        import jwt
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except Exception:
        pass
    try:
        import json
        import base64
        data, sig = token.rsplit(".", 1)
        expected = hashlib.sha256(f"{data}.{settings.secret_key}".encode("utf-8")).hexdigest()
        if sig != expected:
            return None
        return json.loads(base64.urlsafe_b64decode(data).decode("utf-8"))
    except Exception:
        return None


# ---------- public endpoints ----------
@router.post("/register", response_model=AuthResponse)
def register(body: RegisterRequest, db=Depends(get_db)):
    if not _is_email(body.email):
        raise HTTPException(status_code=400, detail="invalid email")
    user_repo = UserRepository(db)
    if user_repo.get_by_email(body.email.lower()):
        raise HTTPException(status_code=400, detail="email already registered")
    if user_repo.get_by_username(body.username):
        raise HTTPException(status_code=400, detail="username already taken")

    user = UserModel(
        username=body.username,
        email=body.email.lower(),
        password_hash=_hash_password(body.password),
        is_active=True,
        settings={},
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    created = user_repo.create(user)
    token = _make_token(created.id)
    return AuthResponse(
        access_token=token,
        user={"id": created.id, "username": created.username, "email": created.email},
    )


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, db=Depends(get_db)):
    if not _is_email(body.email):
        raise HTTPException(status_code=400, detail="invalid email")
    user_repo = UserRepository(db)
    user = user_repo.get_by_email(body.email.lower())
    if not user or not _verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")
    user_repo.update_last_login(user.id)
    token = _make_token(user.id)
    return AuthResponse(
        access_token=token,
        user={"id": user.id, "username": user.username, "email": user.email},
    )


# ---------- dependency: current user ----------
def _extract_token(authorization: str | None = Header(default=None)) -> str | None:
    if not authorization:
        return None
    parts = authorization.strip().split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def get_current_user(
    db=Depends(get_db),
    authorization: str | None = Header(default=None),
) -> UserModel:
    token = _extract_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="missing token")
    payload = _decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="invalid token")
    if payload.get("exp") and payload["exp"] < int(datetime.utcnow().timestamp()):
        raise HTTPException(status_code=401, detail="token expired")
    user_id = int(payload.get("sub", 0))
    user_repo = UserRepository(db)
    user = user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="user not found")
    return user


@router.get("/me")
def me(user: UserModel = Depends(get_current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "settings": user.settings or {},
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }
