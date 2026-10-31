"""Baza: foydalanuvchilar, musiqalar, layklar, to'lovlar. Jadval nomlari m_ bilan boshlanadi."""
import logging
import math
from datetime import datetime, timedelta

from sqlalchemy import (BigInteger, Boolean, DateTime, Integer, String, Text,
                        func, select, text)
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from config import DATABASE_URL, DEFAULT_SETTINGS

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False)
log = logging.getLogger(__name__)

MOODS = {"quvnoq": "😄 Quvnoq", "ortacha": "😐 O'rtacha", "gamgin": "😢 G'amgin"}
RHYTHMS = {"yugurish": "🏃 Yugurayapman", "uxlash": "😴 Uxlayapman",
           "uygonish": "🌅 Uyg'onayapman", "otirish": "🪑 O'tiribman"}
PLAN_MONTHS = (1, 3, 6, 12)
PLAN_DAYS = {1: 30, 3: 90, 6: 180, 12: 365}


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "m_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(String(128), default="")
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    terms_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    banned: Mapped[bool] = mapped_column(Boolean, default=False)
    trial_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    premium_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notified: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Track(Base):
    __tablename__ = "m_tracks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    artist: Mapped[str] = mapped_column(String(200), default="")
    file_id: Mapped[str] = mapped_column(String(300))
    thumb_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    mime: Mapped[str] = mapped_column(String(64), default="audio/mpeg")
    duration: Mapped[int] = mapped_column(Integer, default=0)
    mood: Mapped[str | None] = mapped_column(String(16), nullable=True)
    rhythm: Mapped[str | None] = mapped_column(String(16), nullable=True)
    featured: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    plays: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Like(Base):
    __tablename__ = "m_likes"
    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    track_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Payment(Base):
    __tablename__ = "m_payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    method: Mapped[str] = mapped_column(String(8))          # card | stars
    months: Mapped[int] = mapped_column(Integer)
    amount_uzs: Mapped[int] = mapped_column(BigInteger, default=0)
    stars: Mapped[int] = mapped_column(Integer, default=0)
    receipt_file_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(8), default="pending")   # pending | ok | no
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Setting(Base):
    __tablename__ = "m_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as s:
        for k, v in DEFAULT_SETTINGS.items():
            if not await s.get(Setting, k):
                s.add(Setting(key=k, value=v))
        await s.commit()


async def get_set(key: str, default: str = "") -> str:
    async with Session() as s:
        row = await s.get(Setting, key)
        return row.value if row else DEFAULT_SETTINGS.get(key, default)


async def set_set(key: str, value: str):
    async with Session() as s:
        row = await s.get(Setting, key)
        if row:
            row.value = value
        else:
            s.add(Setting(key=key, value=value))
        await s.commit()


async def get_num(key: str) -> float:
    try:
        return float(await get_set(key))
    except ValueError:
        return float(DEFAULT_SETTINGS.get(key, "0"))


async def get_user(tg_id: int) -> User | None:
    async with Session() as s:
        return await s.scalar(select(User).where(User.tg_id == tg_id))


async def get_or_create_user(tg_id: int, username: str | None, first_name: str) -> User:
    async with Session() as s:
        u = await s.scalar(select(User).where(User.tg_id == tg_id))
        if not u:
            u = User(tg_id=tg_id, username=username, first_name=first_name or "")
            s.add(u)
        else:
            u.username, u.first_name = username, first_name or u.first_name
        await s.commit()
        return u


def now() -> datetime:
    return datetime.utcnow()


def is_premium(u: User) -> bool:
    return bool(u.premium_until and u.premium_until > now())


def is_trial(u: User) -> bool:
    return bool(u.trial_until and u.trial_until > now())


def has_access(u: User) -> bool:
    return is_premium(u) or is_trial(u)


def tashkent(dt: datetime | None) -> str:
    return (dt + timedelta(hours=5)).strftime("%d.%m.%Y %H:%M") if dt else "—"


def days_left(dt: datetime | None) -> int:
    return max(0, math.ceil((dt - now()).total_seconds() / 86400)) if dt else 0


async def grant_premium(tg_id: int, days: int) -> datetime | None:
    """Premium muddatini uzaytiradi (mavjud muddat ustiga qo'shiladi)."""
    async with Session() as s:
        u = await s.scalar(select(User).where(User.tg_id == tg_id).with_for_update())
        if not u:
            return None
        base = u.premium_until if u.premium_until and u.premium_until > now() else now()
        u.premium_until = base + timedelta(days=days)
        u.notified = 0
        await s.commit()
        return u.premium_until


async def plans() -> list[dict]:
    """Narxlar admin belgilagan asosiy narx va chegirmalardan hisoblanadi."""
    base, rate = await get_num("price_month"), max(await get_num("stars_uzs"), 1)
    out = []
    for m in PLAN_MONTHS:
        disc = 0 if m == 1 else await get_num(f"disc_{m}")
        price = int(round(base * m * (1 - disc / 100)))
        out.append({"months": m, "disc": int(disc), "price": price, "stars": max(1, math.ceil(price / rate))})
    return out
