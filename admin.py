"""Admin panel — hammasi Telegram ichida (/admin)."""
import asyncio
import csv
import html
import io
import logging

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)
from sqlalchemy import func, or_, select

import config
from bot import bot, dp
from db import (MOODS, PLAN_DAYS, RHYTHMS, Like, Payment, Session, Setting, Track, User,
                days_left, get_num, get_set, grant_premium, has_access, is_premium,
                is_trial, now, plans, set_set, tashkent)

log = logging.getLogger(__name__)


class IsAdmin(BaseFilter):
    async def __call__(self, event) -> bool:
        return bool(event.from_user) and event.from_user.id in config.ADMIN_IDS


router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())
dp.include_router(router)


def B(text, data):
    return InlineKeyboardButton(text=text, callback_data=data)


def KB(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back(to="adm:main"):
    return KB([[B("⬅️ Orqaga", to)]])


async def show(c: CallbackQuery, text: str, markup=None):
    try:
        await c.message.edit_text(text, reply_markup=markup)
    except Exception:
        await c.message.answer(text, reply_markup=markup)


class A(StatesGroup):
    audio = State()
    mood = State()
    rhythm = State()
    featured = State()
    rename = State()
    setval = State()
    find = State()
    about = State()
    terms = State()
    bc_text = State()
    reply = State()


PANEL = KB([
    [B("🎵 Musiqa qo'shish", "adm:add"), B("📚 Musiqalar", "adm:list:0")],
    [B("💎 Narx va kurs", "adm:price"), B("⏳ To'lov so'rovlari", "adm:pays")],
    [B("👤 Foydalanuvchi", "adm:find"), B("📣 Xabar yuborish", "adm:bc")],
    [B("ℹ️ Bot haqida matni", "adm:about"), B("📜 Shartlar matni", "adm:terms")],
    [B("📥 Telefonlar (CSV)", "adm:csv"), B("📈 Statistika", "adm:stats")],
])


@router.message(Command("admin"))
async def cmd_admin(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("👑 <b>Admin panel</b>", reply_markup=PANEL)


@router.callback_query(F.data == "adm:main")
async def adm_main(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    await show(c, "👑 <b>Admin panel</b>", PANEL)


# ------------------------------------------------------------------ Musiqa qo'shish
@router.callback_query(F.data == "adm:add")
async def add_start(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.clear()
    await state.set_state(A.audio)
    await show(c, "🎵 Musiqa (audio fayl) yuboring. Bir-biridan keyin yuboraverasiz.\n"
                  "Har biri uchun kayfiyat va ritmni so'rayman.\n\n⚠️ Fayl 20 MB dan oshmasin.", back())


@router.message(A.audio, F.audio | F.document)
async def add_audio(m: Message, state: FSMContext):
    a = m.audio
    if a:
        title = a.title or (a.file_name or "Nomsiz").rsplit(".", 1)[0]
        data = dict(file_id=a.file_id, title=title, artist=a.performer or "", duration=a.duration or 0,
                    mime=a.mime_type or "audio/mpeg", thumb=a.thumbnail.file_id if a.thumbnail else None, size=a.file_size or 0)
    else:
        d = m.document
        if not (d.mime_type or "").startswith("audio/"):
            return await m.answer("Bu audio fayl emas. MP3/M4A yuboring.")
        data = dict(file_id=d.file_id, title=(d.file_name or "Nomsiz").rsplit(".", 1)[0], artist="", duration=0,
                    mime=d.mime_type, thumb=d.thumbnail.file_id if d.thumbnail else None, size=d.file_size or 0)
    if data["size"] > 20 * 1024 * 1024:
        return await m.answer("⚠️ Fayl 20 MB dan katta — Telegram botlar bunday faylni Mini App'ga uzata olmaydi. Kichikroq yuboring.")
    await state.update_data(draft=data)
    await state.set_state(A.mood)
    rows = [[B(v, f"mood:{k}")] for k, v in MOODS.items()] + [[B("➖ Farqi yo'q", "mood:-")]]
    await m.answer(f"🎼 <b>{html.escape(data['title'])}</b> {('— ' + html.escape(data['artist'])) if data['artist'] else ''}\n\n<b>Kayfiyat</b> qanday?",
                   reply_markup=KB(rows))


@router.message(A.mood)
@router.message(A.rhythm)
@router.message(A.featured)
async def add_busy(m: Message):
    await m.answer("Avval joriy musiqaning savollarini tugating (tugmalarni bosing).")


@router.callback_query(A.mood, F.data.startswith("mood:"))
async def add_mood(c: CallbackQuery, state: FSMContext):
    v = c.data.split(":")[1]
    await state.update_data(mood=None if v == "-" else v)
    await state.set_state(A.rhythm)
    await c.answer()
    rows = [[B(v2, f"rh:{k}")] for k, v2 in RHYTHMS.items()] + [[B("➖ Farqi yo'q", "rh:-")]]
    await show(c, "<b>Ritm</b> qanday (qachon tinglanadi)?", KB(rows))


@router.callback_query(A.rhythm, F.data.startswith("rh:"))
async def add_rhythm(c: CallbackQuery, state: FSMContext):
    v = c.data.split(":")[1]
    await state.update_data(rhythm=None if v == "-" else v)
    await state.set_state(A.featured)
    await c.answer()
    await show(c, "Bosh sahifada <b>tavsiya</b> sifatida ko'rsatilsinmi?",
               KB([[B("⭐ Ha, tavsiya qilinsin", "ft:1"), B("Yo'q", "ft:0")]]))


@router.callback_query(A.featured, F.data.startswith("ft:"))
async def add_done(c: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    dr = d["draft"]
    async with Session() as s:
        t = Track(title=dr["title"][:200], artist=dr["artist"][:200], file_id=dr["file_id"], thumb_id=dr["thumb"],
                  mime=dr["mime"][:64], duration=dr["duration"], mood=d.get("mood"), rhythm=d.get("rhythm"),
                  featured=c.data.endswith("1"))
        s.add(t)
        await s.commit()
    await state.set_state(A.audio)
    await state.update_data(draft=None, mood=None, rhythm=None)
    await c.answer("Saqlandi")
    await show(c, f"✅ Saqlandi: <b>{html.escape(t.title)}</b>\n"
                  f"{MOODS.get(t.mood, 'kayfiyat: farqi yo`q')} · {RHYTHMS.get(t.rhythm, 'ritm: farqi yo`q')}"
                  f"{' · ⭐ tavsiya' if t.featured else ''}\n\nKeyingi musiqani yuboring yoki tugating:",
               back())


# ------------------------------------------------------------------ Musiqalar ro'yxati
PAGE = 8


@router.callback_query(F.data.startswith("adm:list:"))
async def tracks_list(c: CallbackQuery, state: FSMContext):
    await state.clear()
    page = int(c.data.split(":")[2])
    async with Session() as s:
        total = await s.scalar(select(func.count(Track.id))) or 0
        rows = (await s.execute(select(Track).order_by(Track.id.desc()).offset(page * PAGE).limit(PAGE))).scalars().all()
    await c.answer()
    kb = [[B(f"{'⭐' if t.featured else '🎵'} {t.title[:34]}", f"adm:t:{t.id}")] for t in rows]
    nav = []
    if page > 0:
        nav.append(B("◀️", f"adm:list:{page - 1}"))
    if (page + 1) * PAGE < total:
        nav.append(B("▶️", f"adm:list:{page + 1}"))
    if nav:
        kb.append(nav)
    kb.append([B("⬅️ Panel", "adm:main")])
    await show(c, f"📚 <b>Musiqalar</b>: {total} ta" + ("" if total else "\nHali yo'q."), KB(kb))


async def track_card(c: CallbackQuery, tid: int):
    async with Session() as s:
        t = await s.get(Track, tid)
    if not t:
        return await show(c, "Topilmadi.", back("adm:list:0"))
    await show(c, f"🎵 <b>{html.escape(t.title)}</b>\n{html.escape(t.artist) or '—'}\n"
                  f"{MOODS.get(t.mood, 'Kayfiyat: —')} · {RHYTHMS.get(t.rhythm, 'Ritm: —')}\n"
                  f"▶️ {t.plays} marta · {'⭐ tavsiyada' if t.featured else 'tavsiyada emas'}",
               KB([[B("⭐ Tavsiyani almashtirish", f"adm:tf:{t.id}")], [B("✏️ Nomini o'zgartirish", f"adm:rn:{t.id}")],
                   [B("🗑 O'chirish", f"adm:td:{t.id}")], [B("⬅️ Ro'yxat", "adm:list:0")]]))


@router.callback_query(F.data.startswith("adm:t:"))
async def tr_open(c: CallbackQuery):
    await c.answer()
    await track_card(c, int(c.data.split(":")[2]))


@router.callback_query(F.data.startswith("adm:tf:"))
async def tr_feat(c: CallbackQuery):
    tid = int(c.data.split(":")[2])
    async with Session() as s:
        t = await s.get(Track, tid)
        if t:
            t.featured = not t.featured
            await s.commit()
    await c.answer("Bajarildi")
    await track_card(c, tid)


@router.callback_query(F.data.startswith("adm:td:"))
async def tr_del(c: CallbackQuery):
    tid = int(c.data.split(":")[2])
    async with Session() as s:
        t = await s.get(Track, tid)
        if t:
            await s.delete(t)
            for lk in (await s.execute(select(Like).where(Like.track_id == tid))).scalars().all():
                await s.delete(lk)
            await s.commit()
    await c.answer("O'chirildi")
    await show(c, "🗑 O'chirildi.", back("adm:list:0"))


@router.callback_query(F.data.startswith("adm:rn:"))
async def tr_rename(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.set_state(A.rename)
    await state.update_data(tid=int(c.data.split(":")[2]))
    await show(c, "Yangi nomni yuboring. Ijrochi bilan: <code>Nom - Ijrochi</code>", back("adm:list:0"))


@router.message(A.rename, F.text)
async def tr_rename_do(m: Message, state: FSMContext):
    tid = (await state.get_data())["tid"]
    title, _, artist = m.text.partition(" - ")
    async with Session() as s:
        t = await s.get(Track, tid)
        if t:
            t.title = title.strip()[:200]
            if artist.strip():
                t.artist = artist.strip()[:200]
            await s.commit()
    await state.clear()
    await m.answer("✅ Saqlandi.", reply_markup=back("adm:list:0"))


# ------------------------------------------------------------------ Narx va kurs
PRICE_KEYS = [("price_month", "1 oylik narx (so'm)"), ("disc_3", "3 oy chegirma %"), ("disc_6", "6 oy chegirma %"),
              ("disc_12", "12 oy chegirma %"), ("stars_uzs", "1 Star = necha so'm"), ("trial_days", "Bepul sinov (kun)")]


@router.callback_query(F.data == "adm:price")
async def price_menu(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    pl = await plans()
    txt = "💎 <b>Narx va kurs</b>\n\n" + "\n".join(
        f"{p['months']} oy: <b>{p['price']:,}</b> so'm / {p['stars']} ⭐".replace(",", " ") + (f"  (−{p['disc']}%)" if p["disc"] else "") for p in pl)
    txt += "\n\n" + "\n".join(f"• {lbl}: <b>{await get_set(k)}</b>" for k, lbl in PRICE_KEYS)
    kb = [[B(f"✏️ {lbl}", f"adm:pv:{k}")] for k, lbl in PRICE_KEYS] + [[B("⬅️ Panel", "adm:main")]]
    await show(c, txt, KB(kb))


@router.callback_query(F.data.startswith("adm:pv:"))
async def price_edit(c: CallbackQuery, state: FSMContext):
    key = c.data.split(":")[2]
    await c.answer()
    await state.set_state(A.setval)
    await state.update_data(key=key)
    await show(c, f"<b>{dict(PRICE_KEYS)[key]}</b> uchun yangi qiymatni yuboring (faqat son):", back("adm:price"))


@router.message(A.setval, F.text)
async def price_set(m: Message, state: FSMContext):
    key = (await state.get_data())["key"]
    try:
        v = float(m.text.replace(" ", "").replace(",", "."))
        if v < 0 or (key == "stars_uzs" and v <= 0):
            raise ValueError
    except ValueError:
        return await m.answer("Iltimos, to'g'ri son yuboring.")
    await set_set(key, str(int(v)) if v == int(v) else str(v))
    await state.clear()
    await m.answer("✅ Saqlandi.", reply_markup=back("adm:price"))


# ------------------------------------------------------------------ To'lov so'rovlari (karta)
async def pay_caption(p: Payment, u: User | None) -> str:
    return (f"💳 <b>To'lov #{p.id}</b> — {p.months} oylik Premium\n👤 {p.tg_id} @{(u.username if u else None) or '-'} "
            f"{u.phone if u and u.phone else ''}\nSumma: <b>{p.amount_uzs:,}</b> so'm".replace(",", " "))


def pay_kb(pid: int):
    return KB([[B("✅ Tasdiqlash", f"pay:ok:{pid}"), B("❌ Rad etish", f"pay:no:{pid}")]])


@router.callback_query(F.data == "adm:pays")
async def pays_list(c: CallbackQuery):
    await c.answer()
    async with Session() as s:
        rows = (await s.execute(select(Payment).where(Payment.status == "pending", Payment.method == "card")
                                .order_by(Payment.id).limit(10))).scalars().all()
        users = {u.tg_id: u for u in (await s.execute(select(User).where(User.tg_id.in_([p.tg_id for p in rows])))).scalars().all()} if rows else {}
    if not rows:
        return await show(c, "⏳ Kutayotgan to'lov yo'q.", back())
    await show(c, f"⏳ Kutayotgan: {len(rows)} ta (pastda yuborildi)", back())
    for p in rows:
        cap = await pay_caption(p, users.get(p.tg_id))
        try:
            await bot.send_document(c.from_user.id, p.receipt_file_id, caption=cap, reply_markup=pay_kb(p.id))
        except Exception:
            await bot.send_message(c.from_user.id, cap, reply_markup=pay_kb(p.id))


@router.callback_query(F.data.startswith("pay:"))
async def pay_decide(c: CallbackQuery):
    _, act, pid = c.data.split(":")
    async with Session() as s:
        p = await s.get(Payment, int(pid), with_for_update=True)
        if not p or p.status != "pending":
            return await c.answer("Bu to'lov allaqachon ko'rib chiqilgan", show_alert=True)
        p.status = "ok" if act == "ok" else "no"
        await s.commit()
    if act == "ok":
        until = await grant_premium(p.tg_id, PLAN_DAYS.get(p.months, 30 * p.months))
        txt = f"✅ To'lovingiz tasdiqlandi! 💎 Premium <b>{tashkent(until)}</b> gacha faol."
    else:
        txt = "❌ To'lovingiz rad etildi. Savol bo'lsa, botdagi «Adminga murojaat» orqali yozing."
    try:
        await bot.send_message(p.tg_id, txt)
    except Exception:
        pass
    await c.answer("Bajarildi")
    mark = "✅ Tasdiqlandi" if act == "ok" else "❌ Rad etildi"
    try:
        await c.message.edit_caption(caption=(c.message.caption or "") + f"\n\n{mark}", reply_markup=None)
    except Exception:
        try:
            await c.message.edit_text((c.message.text or "") + f"\n\n{mark}", reply_markup=None)
        except Exception:
            pass


# ------------------------------------------------------------------ Foydalanuvchi
@router.callback_query(F.data == "adm:find")
async def find_start(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.set_state(A.find)
    await show(c, "Foydalanuvchi ID, @username yoki telefon raqamini yuboring:", back())


def user_card(u: User) -> str:
    st = "💎 Premium" if is_premium(u) else ("🎁 Sinov" if is_trial(u) else "⛔ Faol emas")
    return (f"👤 <b>{html.escape(u.first_name or '-')}</b> @{u.username or '-'}\nID: <code>{u.tg_id}</code>\n"
            f"📱 {u.phone or '—'}\nHolat: {st}\nSinov: {tashkent(u.trial_until)}\nPremium: {tashkent(u.premium_until)}\n"
            f"{'🚫 Bloklangan' if u.banned else ''}")


def user_kb(u: User):
    return KB([[B("+30 kun", f"adm:ug:{u.tg_id}:30"), B("+90", f"adm:ug:{u.tg_id}:90"), B("+365", f"adm:ug:{u.tg_id}:365")],
               [B("♻️ Premiumni bekor qilish", f"adm:ug:{u.tg_id}:0")],
               [B("✅ Blokdan chiqarish" if u.banned else "🚫 Bloklash", f"adm:ub:{u.tg_id}")],
               [B("⬅️ Panel", "adm:main")]])


@router.message(A.find, F.text)
async def find_do(m: Message, state: FSMContext):
    q = m.text.strip().lstrip("@")
    async with Session() as s:
        conds = [User.username.ilike(q), User.phone.like(f"%{q.replace('+', '')}")]
        if q.lstrip("-").isdigit():
            conds.append(User.tg_id == int(q))
        u = await s.scalar(select(User).where(or_(*conds)))
    if not u:
        return await m.answer("Topilmadi. Qayta yuboring yoki /admin.")
    await state.clear()
    await m.answer(user_card(u), reply_markup=user_kb(u))


@router.callback_query(F.data.startswith("adm:ug:"))
async def user_grant(c: CallbackQuery):
    _, _, _, tg, days = c.data.split(":")
    tg, days = int(tg), int(days)
    if days:
        until = await grant_premium(tg, days)
        try:
            await bot.send_message(tg, f"🎁 Sizga Premium berildi! 💎 <b>{tashkent(until)}</b> gacha faol.")
        except Exception:
            pass
    else:
        async with Session() as s:
            u = await s.scalar(select(User).where(User.tg_id == tg))
            if u:
                u.premium_until = None
                await s.commit()
    async with Session() as s:
        u = await s.scalar(select(User).where(User.tg_id == tg))
    await c.answer("Bajarildi")
    await show(c, user_card(u), user_kb(u))


@router.callback_query(F.data.startswith("adm:ub:"))
async def user_ban(c: CallbackQuery):
    tg = int(c.data.split(":")[2])
    async with Session() as s:
        u = await s.scalar(select(User).where(User.tg_id == tg))
        u.banned = not u.banned
        await s.commit()
    await c.answer("Bajarildi")
    await show(c, user_card(u), user_kb(u))


# ------------------------------------------------------------------ Matnlar
async def text_edit_start(c: CallbackQuery, state: FSMContext, st, key: str, label: str):
    await c.answer()
    await state.set_state(st)
    cur = await get_set(key)
    await show(c, f"✏️ <b>{label}</b>\nHozirgi matn pastda. Yangisini yuboring (qalin, kursiv va emoji ishlaydi).", back())
    await c.message.answer(cur)


@router.callback_query(F.data == "adm:about")
async def about_edit(c: CallbackQuery, state: FSMContext):
    await text_edit_start(c, state, A.about, "about_text", "Bot haqida")


@router.callback_query(F.data == "adm:terms")
async def terms_edit(c: CallbackQuery, state: FSMContext):
    await text_edit_start(c, state, A.terms, "terms_text", "Foydalanish shartlari")


@router.message(A.about, F.text)
async def about_save(m: Message, state: FSMContext):
    await set_set("about_text", m.html_text)
    await state.clear()
    await m.answer("✅ «Bot haqida» yangilandi.", reply_markup=back())


@router.message(A.terms, F.text)
async def terms_save(m: Message, state: FSMContext):
    await set_set("terms_text", m.html_text)
    await state.clear()
    await m.answer("✅ Shartlar yangilandi.", reply_markup=back())


# ------------------------------------------------------------------ Xabar yuborish
SEGMENTS = {"all": "Hammaga", "trial": "Sinovdagilarga", "expired": "Sinovi tugaganlarga (Premiumsiz)", "prem": "Premium egalariga"}


@router.callback_query(F.data == "adm:bc")
async def bc_menu(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    await show(c, "📣 Kimga yuboramiz?", KB([[B(v, f"adm:bs:{k}")] for k, v in SEGMENTS.items()] + [[B("⬅️ Panel", "adm:main")]]))


@router.callback_query(F.data.startswith("adm:bs:"))
async def bc_seg(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.set_state(A.bc_text)
    await state.update_data(seg=c.data.split(":")[2])
    await show(c, "Xabar matnini yuboring (yoki rasm + izoh):", back("adm:bc"))


async def segment_ids(seg: str) -> list[int]:
    async with Session() as s:
        users = (await s.execute(select(User).where(User.terms_ok, ~User.banned))).scalars().all()
    pick = {"all": lambda u: True, "trial": lambda u: is_trial(u) and not is_premium(u),
            "expired": lambda u: not has_access(u), "prem": is_premium}[seg]
    return [u.tg_id for u in users if pick(u)]


@router.message(A.bc_text)
async def bc_preview(m: Message, state: FSMContext):
    seg = (await state.get_data())["seg"]
    ids = await segment_ids(seg)
    await state.update_data(mid=m.message_id, chat=m.chat.id)
    await m.answer(f"{SEGMENTS[seg]}: <b>{len(ids)}</b> kishiga yuboriladi. Tasdiqlaysizmi?",
                   reply_markup=KB([[B("✅ Yuborish", "adm:bgo")], [B("🚫 Bekor", "adm:main")]]))


@router.callback_query(F.data == "adm:bgo")
async def bc_go(c: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    if not d.get("mid"):
        return await c.answer("Eskirgan", show_alert=True)
    ids = await segment_ids(d["seg"])
    await c.answer("Yuborilmoqda…")
    await show(c, f"📤 {len(ids)} kishiga yuborilmoqda…", None)

    async def run():
        ok = 0
        for tg in ids:
            try:
                await bot.copy_message(tg, d["chat"], d["mid"])
                ok += 1
            except Exception:
                pass
            await asyncio.sleep(0.05)
        await bot.send_message(c.from_user.id, f"✅ Yuborildi: {ok}/{len(ids)}")
    asyncio.create_task(run())


# ------------------------------------------------------------------ Javob (murojaat)
@router.callback_query(F.data.startswith("sup:"))
async def sup_reply_start(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.set_state(A.reply)
    await state.update_data(to=int(c.data.split(":")[1]))
    await c.message.answer("Javobingizni yozing:")


@router.message(A.reply, F.text)
async def sup_reply_send(m: Message, state: FSMContext):
    to = (await state.get_data())["to"]
    await state.clear()
    try:
        await bot.send_message(to, f"👤 <b>Admin javobi:</b>\n\n{html.escape(m.text)}")
        await m.answer("✅ Yuborildi.")
    except Exception:
        await m.answer("❌ Yuborib bo'lmadi (foydalanuvchi botni bloklagan bo'lishi mumkin).")


# ------------------------------------------------------------------ CSV va statistika
@router.callback_query(F.data == "adm:csv")
async def csv_export(c: CallbackQuery):
    await c.answer()
    async with Session() as s:
        users = (await s.execute(select(User).where(User.phone.is_not(None)).order_by(User.id))).scalars().all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["tg_id", "username", "ism", "telefon", "sinov_tugashi", "premium_tugashi"])
    for u in users:
        w.writerow([u.tg_id, u.username or "", u.first_name, u.phone, tashkent(u.trial_until), tashkent(u.premium_until)])
    await c.message.answer_document(BufferedInputFile(buf.getvalue().encode("utf-8-sig"), filename="foydalanuvchilar.csv"),
                                    caption=f"📥 {len(users)} ta foydalanuvchi")


@router.callback_query(F.data == "adm:stats")
async def stats(c: CallbackQuery):
    await c.answer()
    async with Session() as s:
        users = (await s.execute(select(User))).scalars().all()
        tracks = await s.scalar(select(func.count(Track.id))) or 0
        plays = await s.scalar(select(func.coalesce(func.sum(Track.plays), 0))) or 0
        likes = await s.scalar(select(func.count()).select_from(Like)) or 0
        paid = await s.scalar(select(func.coalesce(func.sum(Payment.amount_uzs), 0)).where(Payment.status == "ok", Payment.method == "card")) or 0
        stars = await s.scalar(select(func.coalesce(func.sum(Payment.stars), 0)).where(Payment.status == "ok", Payment.method == "stars")) or 0
    reg = [u for u in users if u.phone]
    await show(c, f"📈 <b>Statistika</b>\n\n👥 Ro'yxatdan o'tgan: {len(reg)} (jami /start: {len(users)})\n"
                  f"💎 Premium: {sum(is_premium(u) for u in users)}\n🎁 Sinovda: {sum(is_trial(u) and not is_premium(u) for u in users)}\n"
                  f"⛔ Faol emas: {sum(not has_access(u) for u in reg)}\n\n🎵 Musiqa: {tracks}\n▶️ Tinglashlar: {plays}\n❤️ Layklar: {likes}\n\n"
                  f"💳 Karta tushumi: {paid:,} so'm\n⭐ Stars: {stars}".replace(",", " "), back())
