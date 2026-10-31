"""Foydalanuvchi qismi: /start, shartlar, telefon, asosiy menyu, Premium to'lovlari (Stars), qo'llab-quvvatlash."""
import asyncio
import html
import logging

from aiogram import Bot, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, KeyboardButton, Message,
                           PreCheckoutQuery, ReplyKeyboardMarkup,
                           ReplyKeyboardRemove, WebAppInfo)
from aiogram import Dispatcher
from sqlalchemy import select

import config
from db import (PLAN_DAYS, Like, Payment, Session, Track, User, days_left,
                get_num, get_or_create_user, get_set, get_user, grant_premium,
                has_access, is_premium, is_trial, now, plans, tashkent)

log = logging.getLogger(__name__)
bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)


class Sup(StatesGroup):
    msg = State()


def B(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def webapp(tab: str | None = None) -> WebAppInfo | None:
    if not config.WEBAPP_URL:
        return None
    return WebAppInfo(url=config.WEBAPP_URL + (f"/?tab={tab}" if tab else "/"))


def menu_kb(u: User) -> InlineKeyboardMarkup:
    rows = []
    w = webapp()
    rows.append([InlineKeyboardButton(text="🎧 Musiqa tinglash", web_app=w) if w else B("🎧 Musiqa tinglash", "m:nourl")])
    wp = webapp("premium")
    rows.append([InlineKeyboardButton(text="💎 Premium sotib olish", web_app=wp) if wp else B("💎 Premium sotib olish", "m:nourl")])
    if is_premium(u):          # saqlangan musiqa faqat Premium egalariga ko'rinadi
        rows.append([B("💾 Saqlangan musiqa", "m:saved")])
    rows.append([B("👤 Adminga murojaat", "m:support")])
    rows.append([B("ℹ️ Bot haqida", "m:about")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def status_line(u: User) -> str:
    if is_premium(u):
        return f"💎 Premium faol: <b>{tashkent(u.premium_until)}</b> gacha"
    if is_trial(u):
        return f"🎁 Bepul sinov: <b>{days_left(u.trial_until)} kun</b> qoldi"
    return "⏳ Bepul sinov tugagan. Davom etish uchun Premium oling."


async def send_menu(chat_id: int, u: User):
    name = f"@{u.username}" if u.username else html.escape(u.first_name or "do'st")
    await bot.send_message(
        chat_id,
        f"Assalomu alaykum, {name}! 👋\n\nBu bot orqali siz musiqalarni <b>cheksiz daqiqalar</b> eshitishingiz mumkin!!!\n\n"
        f"{status_line(u)}", reply_markup=menu_kb(u))


async def ask_terms(chat_id: int):
    await bot.send_message(chat_id, await get_set("terms_text") + "\n\n🎁 <b>Botdan 1 hafta bepul foydalanasiz.</b>",
                           reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B("✅ Roziman", "terms:ok")]]))


@router.message(CommandStart())
@router.message(Command("menu"))
async def start(m: Message, state: FSMContext):
    await state.clear()
    u = await get_or_create_user(m.from_user.id, m.from_user.username, m.from_user.first_name)
    if u.banned:
        return await m.answer("🚫 Hisobingiz bloklangan.")
    if not u.terms_ok:
        return await ask_terms(m.chat.id)
    if not u.phone:
        return await ask_phone(m.chat.id)
    await send_menu(m.chat.id, u)


async def ask_phone(chat_id: int):
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]],
                             resize_keyboard=True, one_time_keyboard=True)
    await bot.send_message(chat_id, "Davom etish uchun telefon raqamingizni yuboring (pastdagi tugma orqali):", reply_markup=kb)


@router.callback_query(F.data == "terms:ok")
async def terms_ok(c: CallbackQuery):
    async with Session() as s:
        u = await s.scalar(select(User).where(User.tg_id == c.from_user.id))
        if not u:
            return await c.answer("Avval /start bosing", show_alert=True)
        u.terms_ok = True
        await s.commit()
    await c.answer()
    try:
        await c.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await ask_phone(c.message.chat.id)


@router.message(F.contact)
async def got_contact(m: Message):
    if m.contact.user_id != m.from_user.id:
        return await m.answer("Iltimos, o'zingizning raqamingizni tugma orqali yuboring.")
    phone = m.contact.phone_number if m.contact.phone_number.startswith("+") else "+" + m.contact.phone_number
    days = int(await get_num("trial_days"))
    async with Session() as s:
        u = await s.scalar(select(User).where(User.tg_id == m.from_user.id))
        if not u or not u.terms_ok:
            return await m.answer("Avval /start bosib, shartlarga rozilik bering.")
        u.phone = phone
        if not u.trial_until:                      # bepul sinov faqat bir marta beriladi
            from datetime import timedelta
            u.trial_until = now() + timedelta(days=days)
        await s.commit()
    await m.answer("✅ Raqamingiz saqlandi.", reply_markup=ReplyKeyboardRemove())
    await send_menu(m.chat.id, await get_user(m.from_user.id))


async def need_user(c: CallbackQuery) -> User | None:
    u = await get_user(c.from_user.id)
    if not u or not u.terms_ok or not u.phone or u.banned:
        await c.answer("Avval /start bosing", show_alert=True)
        return None
    return u


@router.callback_query(F.data == "m:nourl")
async def no_url(c: CallbackQuery):
    await c.answer("Mini App hali ulanmagan. Admin WEBAPP_URL ni kiritishi kerak.", show_alert=True)


@router.callback_query(F.data == "m:about")
async def about(c: CallbackQuery):
    await c.answer()
    await c.message.answer(await get_set("about_text"))


@router.callback_query(F.data == "m:saved")
async def saved(c: CallbackQuery):
    u = await need_user(c)
    if not u:
        return
    if not is_premium(u):
        return await c.answer("Saqlangan musiqa faqat Premium egalari uchun 💎", show_alert=True)
    async with Session() as s:
        tracks = (await s.execute(select(Track).join(Like, Like.track_id == Track.id)
                                  .where(Like.tg_id == u.tg_id, Track.active).order_by(Like.created_at.desc()).limit(40))).scalars().all()
    await c.answer()
    if not tracks:
        return await c.message.answer("Hali saralangan musiqa yo'q. Mini App'da ❤️ bosing.")
    rows = [[B(f"🎵 {t.title[:30]}{' – ' + t.artist[:18] if t.artist else ''}", f"sv:{t.id}")] for t in tracks]
    await c.message.answer("💾 <b>Saqlangan musiqalar</b>\nBosing — bot musiqani yuboradi:",
                           reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("sv:"))
async def send_saved(c: CallbackQuery):
    u = await need_user(c)
    if not u:
        return
    if not is_premium(u):
        return await c.answer("Bu faqat Premium uchun 💎", show_alert=True)
    async with Session() as s:
        t = await s.get(Track, int(c.data.split(":")[1]))
    if not t or not t.active:
        return await c.answer("Musiqa topilmadi", show_alert=True)
    await c.answer("Yuborilmoqda…")
    await bot.send_audio(c.from_user.id, t.file_id, title=t.title, performer=t.artist or None)


# ------------------------------------------------------------------ Adminga murojaat
@router.callback_query(F.data == "m:support")
async def support(c: CallbackQuery, state: FSMContext):
    if not await need_user(c):
        return
    await c.answer()
    await state.set_state(Sup.msg)
    await c.message.answer("Xabaringizni yozing (savol, taklif yoki muammo). Admin javob beradi.\nBekor qilish: /menu")


@router.message(Sup.msg, F.text)
async def support_msg(m: Message, state: FSMContext):
    if m.text.startswith("/"):
        return await start(m, state)
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[B("↩️ Javob berish", f"sup:{m.from_user.id}")]])
    for a in config.ADMIN_IDS:
        try:
            await bot.send_message(a, f"📩 <b>Murojaat</b>\n👤 {m.from_user.id} @{m.from_user.username or '-'} "
                                      f"{html.escape(m.from_user.first_name or '')}\n\n{html.escape(m.text)}", reply_markup=kb)
        except Exception:
            log.exception("adminga murojaat yuborilmadi")
    await m.answer("✅ Xabaringiz adminga yuborildi. Javobni shu yerda olasiz.")


# ------------------------------------------------------------------ Telegram Stars to'lovi
@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    ok = q.invoice_payload.startswith("prem:")
    await q.answer(ok=ok, error_message=None if ok else "To'lov ma'lumoti noto'g'ri")


@router.message(F.successful_payment)
async def paid(m: Message):
    sp = m.successful_payment
    try:
        months = int(sp.invoice_payload.split(":")[1])
        days = PLAN_DAYS[months]
    except (ValueError, IndexError, KeyError):
        log.error("noma'lum payload: %s", sp.invoice_payload)
        return
    until = await grant_premium(m.from_user.id, days)
    async with Session() as s:
        s.add(Payment(tg_id=m.from_user.id, method="stars", months=months, stars=sp.total_amount, status="ok"))
        await s.commit()
    await m.answer(f"✅ To'lov qabul qilindi! 💎 Premium <b>{tashkent(until)}</b> gacha faol.")
    for a in config.ADMIN_IDS:
        try:
            await bot.send_message(a, f"⭐ Stars to'lov: {m.from_user.id} @{m.from_user.username or '-'} — "
                                      f"{months} oy, {sp.total_amount} Stars")
        except Exception:
            pass


# ------------------------------------------------------------------ Ogohlantirishlar (bepul sinov tugashi)
async def reminder_loop():
    """Har 30 daqiqada: sinov tugashiga 1 kun qolganda va tugaganda foydalanuvchiga xabar yuboradi."""
    from datetime import timedelta
    while True:
        try:
            async with Session() as s:
                soon = (await s.execute(select(User).where(
                    User.notified < 1, User.trial_until.is_not(None), User.trial_until > now(),
                    User.trial_until < now() + timedelta(days=1)))).scalars().all()
                ended = (await s.execute(select(User).where(
                    User.notified < 2, User.trial_until.is_not(None), User.trial_until <= now()))).scalars().all()
                todo = [(u, 1) for u in soon if not is_premium(u)] + [(u, 2) for u in ended if not is_premium(u)]
                for u in soon + ended:
                    u.notified = 2 if u in ended else 1
                await s.commit()
            for u, kind in todo:
                text = ("⏰ Bepul sinov muddatingiz <b>ertaga tugaydi</b>. Musiqa tinglashni to'xtatmaslik uchun Premium oling 💎"
                        if kind == 1 else "⌛ Bepul sinov muddatingiz tugadi. Tinglashni davom ettirish uchun Premium oling 💎")
                w = webapp("premium")
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💎 Premium sotib olish", web_app=w)]]) if w else None
                try:
                    await bot.send_message(u.tg_id, text, reply_markup=kb)
                except Exception:
                    pass
                await asyncio.sleep(0.05)
        except Exception:
            log.exception("reminder_loop")
        await asyncio.sleep(1800)
