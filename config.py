import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
# Admin: raqamli Telegram ID (bir nechta bo'lsa vergul bilan). Standart: sizning ID.
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "6942515055").replace(" ", "").split(",")
             if x.strip().lstrip("-").isdigit()]
BOT_TITLE = os.getenv("BOT_TITLE", "Musiqa")           # Mini App'da ko'rinadigan nom
WEBAPP_URL = os.getenv("WEBAPP_URL", "").rstrip("/")   # https://xxxx.onrender.com
CARD_NUMBER = os.getenv("CARD_NUMBER", "")
CARD_OWNER = os.getenv("CARD_OWNER", "")
PORT = int(os.getenv("PORT", "8000"))


def _normalize_db(url: str) -> str:
    """Neon / Render havolalarini asyncpg uchun avtomatik moslaydi."""
    url = (url or "").strip()
    if not url:
        return "sqlite+aiosqlite:///music.db"   # DIQQAT: Render'da qayta deploydan keyin o'chib ketadi!
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    url = url.replace("sslmode=require", "ssl=require")
    base, _, query = url.partition("?")
    params = [p for p in query.split("&") if p and not p.startswith("channel_binding")]
    return base + ("?" + "&".join(params) if params else "")


DATABASE_URL = _normalize_db(os.getenv("DATABASE_URL", ""))

DEFAULT_TERMS = (
    "📜 <b>Foydalanish shartlari</b>\n\n"
    "1. Botdan <b>1 hafta mutlaqo bepul</b> foydalanasiz — musiqalarni cheksiz tinglang.\n"
    "2. Bepul muddat tugagach, tinglashni davom ettirish uchun <b>Premium</b> olasiz (1, 3, 6 yoki 12 oy).\n"
    "3. Premium'da musiqalarni saqlab, botga yuklab olish mumkin.\n"
    "4. Musiqalar faqat shaxsiy tinglash uchun. Ularni tarqatish yoki qayta sotish mumkin emas.\n"
    "5. To'langan Premium muddati qaytarilmaydi.\n"
    "6. Bot ishlashi uchun telefon raqamingiz so'raladi va xavfsiz saqlanadi."
)
DEFAULT_ABOUT = "ℹ️ Bu bot orqali sevimli musiqalaringizni cheksiz tinglang."

DEFAULT_SETTINGS = {
    "price_month": "4590",     # 1 oylik Premium narxi (so'm)
    "disc_3": "10",            # 3 oylik chegirma %
    "disc_6": "20",
    "disc_12": "25",
    "stars_uzs": "230",        # 1 Star = necha so'm (admin belgilaydi)
    "trial_days": "7",
    "terms_text": DEFAULT_TERMS,
    "about_text": DEFAULT_ABOUT,
}
