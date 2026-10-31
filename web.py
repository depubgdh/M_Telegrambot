"""Mini App serveri (FastAPI): bot bilan bitta baza. Musiqa Telegram'dan olinib, Range qo'llab-quvvatlab uzatiladi."""
import asyncio
import hashlib
import hmac
import html
import json
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qsl

from aiogram.types import (BufferedInputFile, InlineKeyboardButton,
                           InlineKeyboardMarkup, LabeledPrice)
from fastapi import FastAPI, File, Form, Header, HTTPException, Request as HReq, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select

import config
from bot import bot
from db import (MOODS, PLAN_DAYS, RHYTHMS, Like, Payment, Session, Track, User, days_left,
                get_user, has_access, is_premium, is_trial, plans, tashkent)

app = FastAPI()
INDEX = Path(__file__).resolve().parent / "index.html"
CACHE = Path(tempfile.gettempdir()) / "music_cache"
CACHE.mkdir(exist_ok=True)
SECRET = hashlib.sha256(("audio:" + config.BOT_TOKEN).encode()).digest()


# ------------------------------------------------------------------ xavfsizlik
def verify_init_data(init_data: str) -> dict:
    data = dict(parse_qsl(init_data or "", keep_blank_values=True))
    recv = data.pop("hash", None)
    if not recv:
        raise HTTPException(401, "Mini App'ni Telegram ichidan oching")
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(secret, check.encode(), hashlib.sha256).hexdigest(), recv):
        raise HTTPException(401, "Imzo noto'g'ri")
    try:
        if time.time() - int(data.get("auth_date", "0")) > 86400:
            raise HTTPException(401, "Sessiya eskirgan. Mini App'ni qayta oching")
        return json.loads(data["user"])
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Foydalanuvchi ma'lumoti noto'g'ri")


async def auth(x_init_data: str) -> User:
    tg = verify_init_data(x_init_data)
    u = await get_user(int(tg["id"]))
    if not u or not u.terms_ok or not u.phone:
        raise HTTPException(403, "Avval botda /start bosib, shartlarga rozilik bering va raqamingizni yuboring")
    if u.banned:
        raise HTTPException(403, "Hisobingiz bloklangan")
    return u


def make_token(tg_id: int) -> str:
    exp = int(time.time()) + 6 * 3600
    sig = hmac.new(SECRET, f"{tg_id}.{exp}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{tg_id}.{exp}.{sig}"


def check_token(tok: str) -> int:
    try:
        tg, exp, sig = tok.split(".")
        good = hmac.new(SECRET, f"{tg}.{exp}".encode(), hashlib.sha256).hexdigest()[:32]
        if hmac.compare_digest(good, sig) and int(exp) > time.time():
            return int(tg)
    except Exception:
        pass
    raise HTTPException(401, "Havola eskirgan")


# ------------------------------------------------------------------ sahifa
@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return {"ok": True}


@app.get("/")
async def index():
    return FileResponse(INDEX, headers={"Cache-Control": "no-cache"})


def track_json(t: Track, liked: set[int]) -> dict:
    return {"id": t.id, "title": t.title, "artist": t.artist, "dur": t.duration, "cover": bool(t.thumb_id),
            "liked": t.id in liked, "mood": t.mood, "rhythm": t.rhythm}


async def liked_ids(tg_id: int) -> set[int]:
    async with Session() as s:
        return set((await s.execute(select(Like.track_id).where(Like.tg_id == tg_id))).scalars().all())


# ------------------------------------------------------------------ profil
@app.get("/api/me")
async def me(x_init_data: str = Header(...)):
    u = await auth(x_init_data)
    prem, trial = is_premium(u), is_trial(u)
    return {
        "title": config.BOT_TITLE,
        "name": u.first_name or (u.username or ""), "username": u.username, "phone": u.phone,
        "premium": prem, "trial": trial and not prem, "access": prem or trial,
        "premium_until": tashkent(u.premium_until) if prem else None,
        "days_left": days_left(u.premium_until if prem else u.trial_until),
        "plans": await plans(),
        "card": {"number": config.CARD_NUMBER, "owner": config.CARD_OWNER},
        "moods": [{"k": k, "t": v} for k, v in MOODS.items()],
        "rhythms": [{"k": k, "t": v} for k, v in RHYTHMS.items()],
        "token": make_token(u.tg_id),
    }


# ------------------------------------------------------------------ musiqalar
@app.get("/api/tracks")
async def tracks(q: str = "", featured: int = 0, x_init_data: str = Header(...)):
    u = await auth(x_init_data)
    stmt = select(Track).where(Track.active)
    q = q.strip()[:80]
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Track.title.ilike(like), Track.artist.ilike(like)))
        stmt = stmt.order_by(Track.plays.desc(), Track.id.desc())
    else:
        stmt = stmt.order_by(Track.id.desc())
    async with Session() as s:
        rows = (await s.execute(stmt.limit(60))).scalars().all()
        if featured and not q:
            fe = [t for t in rows if t.featured]
            rows = fe or rows[:30]
    lk = await liked_ids(u.tg_id)
    return [track_json(t, lk) for t in rows]


@app.get("/api/wave")
async def wave(mood: str = "", rhythm: str = "", exclude: str = "", x_init_data: str = Header(...)):
    """Tanlangan kayfiyat/ritmga mos tasodifiy musiqalar. Mos topilmasa — hammasidan."""
    u = await auth(x_init_data)
    ex = [int(x) for x in exclude.split(",") if x.strip().isdigit()][-200:]
    base = select(Track).where(Track.active)
    async with Session() as s:
        async def pick(cond):
            st = base
            if cond is not None:
                st = st.where(*cond)
            if ex:
                st = st.where(Track.id.notin_(ex))
            return (await s.execute(st.order_by(func.random()).limit(12))).scalars().all()
        cond = []
        if mood in MOODS:
            cond.append(Track.mood == mood)
        if rhythm in RHYTHMS:
            cond.append(Track.rhythm == rhythm)
        rows = await pick(cond or None)
        if not rows and cond:
            rows = await pick(None)
        if not rows and ex:           # hammasi tinglab bo'lingan — qaytadan boshlaymiz
            ex = []
            rows = await pick(cond or None) or await pick(None)
    lk = await liked_ids(u.tg_id)
    return [track_json(t, lk) for t in rows]


@app.get("/api/liked")
async def liked(x_init_data: str = Header(...)):
    u = await auth(x_init_data)
    async with Session() as s:
        rows = (await s.execute(select(Track).join(Like, Like.track_id == Track.id)
                                .where(Like.tg_id == u.tg_id, Track.active).order_by(Like.created_at.desc()))).scalars().all()
    return [track_json(t, {t.id for t in rows}) for t in rows]


class LikeIn(BaseModel):
    track_id: int


@app.post("/api/like")
async def like(body: LikeIn, x_init_data: str = Header(...)):
    u = await auth(x_init_data)
    async with Session() as s:
        lk = await s.get(Like, (u.tg_id, body.track_id))
        if lk:
            await s.delete(lk)
            state = False
        else:
            if not await s.get(Track, body.track_id):
                raise HTTPException(404, "Musiqa topilmadi")
            s.add(Like(tg_id=u.tg_id, track_id=body.track_id))
            state = True
        await s.commit()
    return {"liked": state}


@app.post("/api/download")
async def download(body: LikeIn, x_init_data: str = Header(...)):
    u = await auth(x_init_data)
    if not is_premium(u):
        raise HTTPException(403, "Yuklab olish faqat Premium egalari uchun")
    async with Session() as s:
        t = await s.get(Track, body.track_id)
    if not t or not t.active:
        raise HTTPException(404, "Musiqa topilmadi")
    await bot.send_audio(u.tg_id, t.file_id, title=t.title, performer=t.artist or None)
    return {"ok": True, "msg": "Musiqa botga yuborildi ✅"}


# ------------------------------------------------------------------ audio oqimi (Range bilan)
_locks: dict[int, asyncio.Lock] = {}


async def cached_file(t: Track) -> Path:
    p = CACHE / f"{t.id}.bin"
    if p.exists() and p.stat().st_size > 0:
        os.utime(p)
        return p
    lock = _locks.setdefault(t.id, asyncio.Lock())
    async with lock:
        if p.exists() and p.stat().st_size > 0:
            return p
        try:
            f = await bot.get_file(t.file_id)
            tmp = p.with_suffix(".part")
            await bot.download_file(f.file_path, destination=str(tmp))
            tmp.replace(p)
        except Exception:
            raise HTTPException(404, "Musiqani yuklab bo'lmadi (fayl 20 MB dan katta bo'lishi mumkin)")
    files = sorted(CACHE.glob("*.bin"), key=lambda x: x.stat().st_mtime)      # joy tugamasligi uchun eskilarini o'chiramiz
    total = sum(x.stat().st_size for x in files)
    while total > 300 * 1024 * 1024 and len(files) > 1:
        old = files.pop(0)
        total -= old.stat().st_size
        old.unlink(missing_ok=True)
    return p


@app.get("/audio/{tid}")
async def audio(tid: int, request: HReq, t: str = ""):
    tg = check_token(t)
    u = await get_user(tg)
    if not u or u.banned or not has_access(u):
        raise HTTPException(403, "Tinglash uchun Premium kerak")
    async with Session() as s:
        tr = await s.get(Track, tid)
        if not tr or not tr.active:
            raise HTTPException(404, "Musiqa topilmadi")
    path = await cached_file(tr)
    size = path.stat().st_size
    start, end = 0, size - 1
    rng = request.headers.get("range")
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", (rng or "").strip())
    if m and (m.group(1) or m.group(2)):
        if m.group(1):
            start = int(m.group(1))
            end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
        else:
            start = max(0, size - int(m.group(2)))
        if start > end or start >= size:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    if start == 0:
        async with Session() as s:
            tt = await s.get(Track, tid)
            if tt:
                tt.plays += 1
                await s.commit()
    with open(path, "rb") as f:
        f.seek(start)
        body = f.read(end - start + 1)
    headers = {"Accept-Ranges": "bytes", "Content-Length": str(len(body)), "Cache-Control": "private, max-age=3600"}
    if rng:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return Response(body, status_code=206 if rng else 200, media_type=tr.mime or "audio/mpeg", headers=headers)


_cover_cache: dict[int, bytes] = {}


@app.get("/cover/{tid}")
async def cover(tid: int):
    data = _cover_cache.get(tid)
    if data is None:
        async with Session() as s:
            t = await s.get(Track, tid)
        if not t or not t.thumb_id:
            raise HTTPException(404, "Rasm yo'q")
        try:
            import io
            f = await bot.get_file(t.thumb_id)
            buf = io.BytesIO()
            await bot.download_file(f.file_path, destination=buf)
            data = buf.getvalue()
        except Exception:
            raise HTTPException(404, "Rasm topilmadi")
        if len(_cover_cache) > 300:
            _cover_cache.clear()
        _cover_cache[tid] = data
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


# ------------------------------------------------------------------ to'lov
class PayIn(BaseModel):
    months: int


async def plan_of(months: int) -> dict:
    for p in await plans():
        if p["months"] == months:
            return p
    raise HTTPException(400, "Noto'g'ri tarif")


@app.post("/api/pay/stars")
async def pay_stars(body: PayIn, x_init_data: str = Header(...)):
    u = await auth(x_init_data)
    p = await plan_of(body.months)
    link = await bot.create_invoice_link(
        title=f"Premium — {p['months']} oy", description="Musiqalarni cheksiz tinglash va yuklab olish",
        payload=f"prem:{p['months']}", provider_token="", currency="XTR",
        prices=[LabeledPrice(label=f"Premium {p['months']} oy", amount=p["stars"])])
    return {"link": link}


@app.post("/api/pay/card")
async def pay_card(x_init_data: str = Header(...), months: int = Form(...), file: UploadFile = File(...)):
    u = await auth(x_init_data)
    p = await plan_of(months)
    content = await file.read()
    if not content:
        raise HTTPException(400, "Chek faylini tanlang")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "Fayl 10 MB dan katta")
    async with Session() as s:
        pay = Payment(tg_id=u.tg_id, method="card", months=months, amount_uzs=p["price"])
        s.add(pay)
        await s.commit()
    cap = (f"💳 <b>To'lov #{pay.id}</b> — {months} oylik Premium\n👤 {u.tg_id} @{u.username or '-'} {u.phone or ''}\n"
           f"Summa: <b>{p['price']:,}</b> so'm".replace(",", " "))
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"pay:ok:{pay.id}"),
                                                InlineKeyboardButton(text="❌ Rad etish", callback_data=f"pay:no:{pay.id}")]])
    sent = False
    for a in config.ADMIN_IDS:
        try:
            msg = await bot.send_document(a, BufferedInputFile(content, filename=file.filename or "chek.jpg"), caption=cap, reply_markup=kb)
            if not sent:
                async with Session() as s:
                    row = await s.get(Payment, pay.id)
                    row.receipt_file_id = msg.document.file_id
                    await s.commit()
            sent = True
        except Exception:
            pass
    if not sent:
        raise HTTPException(503, "Chekni adminga yuborib bo'lmadi. Birozdan so'ng urinib ko'ring")
    return {"ok": True, "msg": "Chek adminga yuborildi. Tasdiqlangach Premium yoqiladi."}
