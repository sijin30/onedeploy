from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from models.refresh_token import RefreshToken
from models.user import User


async def register_user(
    email: str,
    password: str,
    db: AsyncSession,
):
    result = await db.execute(
        select(User).where(User.email == email)
    )

    existing_user = result.scalar_one_or_none()

    if existing_user:
        return None

    user = User(
        email=email.lower(),
        password_hash=hash_password(password),
    )

    db.add(user)

    await db.commit()
    await db.refresh(user)

    return user


async def login_user(
    email: str,
    password: str,
    db: AsyncSession,
):
    result = await db.execute(
        select(User).where(
            User.email == email.lower()
        )
    )

    user = result.scalar_one_or_none()

    if not user:
        return None

    if not verify_password(
        password,
        user.password_hash,
    ):
        return None

    access_token = create_access_token(
        str(user.id)
    )

    refresh_token = create_refresh_token()

    refresh_token_hash = hash_refresh_token(
        refresh_token
    )

    refresh_token_record = RefreshToken(
        user_id=user.id,
        token_hash=refresh_token_hash,
        expires_at=(
            datetime.now(timezone.utc)
            + timedelta(
                days=settings.REFRESH_TOKEN_EXPIRE_DAYS
            )
        ),
        created_at=datetime.now(timezone.utc),
    )

    db.add(refresh_token_record)

    await db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }


async def refresh_access_token(
    refresh_token: str,
    db: AsyncSession,
):
    token_hash = hash_refresh_token(
        refresh_token
    )

    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash
        )
    )

    stored_token = result.scalar_one_or_none()

    if not stored_token:
        return None

    now = datetime.now(timezone.utc)

    if stored_token.revoked_at is not None:
        return None

    if stored_token.expires_at <= now:
        return None

    stored_token.revoked_at = now

    new_access_token = create_access_token(
        str(stored_token.user_id)
    )

    new_refresh_token = create_refresh_token()

    new_refresh_token_record = RefreshToken(
        user_id=stored_token.user_id,
        token_hash=hash_refresh_token(
            new_refresh_token
        ),
        expires_at=(
            now
            + timedelta(
                days=settings.REFRESH_TOKEN_EXPIRE_DAYS
            )
        ),
        created_at=now,
    )

    db.add(new_refresh_token_record)

    await db.commit()

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
    }


async def logout_user(
    refresh_token: str,
    db: AsyncSession,
):
    token_hash = hash_refresh_token(
        refresh_token
    )

    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash
        )
    )

    stored_token = result.scalar_one_or_none()

    if not stored_token:
        return False

    if stored_token.revoked_at is not None:
        return False

    stored_token.revoked_at = datetime.now(
        timezone.utc
    )

    await db.commit()

    return True