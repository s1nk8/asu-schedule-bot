import asyncio
import logging
import os
import re
import sys
from urllib.parse import quote

from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from bs4 import BeautifulSoup
import httpx

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8639721738:AAEX_xUw7rtNLCVCFys2ng9zAWFjgO74NjU")
BASE_URL = "https://www.asu.ru"
TIMETABLE_URL = f"{BASE_URL}/timetable/"

HEADERS = {"User-Agent": "Mozilla/5.0"}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

POPULAR_GROUPS = [
    "9.501-1", "9.501-2", "9.502-1", "4.101-1", "4.101-2",
    "1.201-1", "1.201-2", "5.301-1", "8.401-1", "8.401-2",
]

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Найти расписание")],
            [KeyboardButton(text="📋 Популярные группы")],
            [KeyboardButton(text="🌐 Сайт АлтГУ"), KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True,
    )

async def search_group_url(query: str) -> str | None:
    """Ищет URL страницы группы через поиск сайта"""
    try:
        url = f"{BASE_URL}/timetable/search/students/?query={quote(query)}"
        
        async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS, timeout=10) as client:
            r = await client.get(url)
            
            if r.status_code != 200:
                return None
            
            soup = BeautifulSoup(r.text, 'html.parser')
            
            # Ищем ссылку на группу
            for link in soup.find_all('a', href=True):
                if query in link.get_text() and '/timetable/students/' in link.get('href', ''):
                    return BASE_URL + link.get('href')
            
            return None
    except Exception as e:
        logger.error(f"Search error: {e}")
        return None

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 <b>Бот расписания АлтГУ</b>\n\n"
        "Отправьте номер группы:\n"
        "<code>9.501-1</code>\n\n"
        "Или используйте кнопки меню.",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "🔍 Найти расписание")
async def btn_search(message: types.Message):
    await message.answer(
        "Отправьте номер группы, фамилию преподавателя или аудиторию.\n\n"
        "<b>Примеры:</b>\n"
        "• <code>9.501-1</code>\n"
        "• <code>Иванов</code>\n"
        "• <code>327М</code>",
        parse_mode="HTML"
    )

@dp.message(F.text == "📋 Популярные группы")
async def btn_popular(message: types.Message):
    keyboard = []
    for i in range(0, len(POPULAR_GROUPS), 3):
        row = []
        for group in POPULAR_GROUPS[i:i+3]:
            row.append(InlineKeyboardButton(text=group, callback_data=f"g_{group}"))
        keyboard.append(row)
    
    await message.answer(
        "📋 <b>Выберите группу:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@dp.callback_query(F.data.startswith("g_"))
async def cb_group(callback: CallbackQuery):
    await callback.answer()
    group = callback.data.replace("g_", "")
    
    await callback.message.edit_text(f"⏳ Ищу группу <b>{group}</b>...", parse_mode="HTML")
    
    group_url = await search_group_url(group)
    
    if group_url:
        await callback.message.edit_text(
            f"📅 <b>Группа {group}</b>\n\n"
            f"🔗 <a href='{group_url}'>Открыть расписание на сайте АлтГУ</a>\n\n"
            f"<i>Нажмите на ссылку, чтобы посмотреть расписание.</i>",
            parse_mode="HTML",
            disable_web_page_preview=False
        )
    else:
        await callback.message.edit_text(
            f"❌ Группа <b>{group}</b> не найдена.\n"
            f"Попробуйте открыть сайт: {TIMETABLE_URL}",
            parse_mode="HTML"
        )

@dp.message(F.text == "🌐 Сайт АлтГУ")
async def btn_website(message: types.Message):
    await message.answer(f"🔗 {TIMETABLE_URL}")

@dp.message(F.text == "❓ Помощь")
async def btn_help(message: types.Message):
    await message.answer(
        "<b>📚 Помощь:</b>\n\n"
        "Отправьте боту номер группы, например:\n"
        "<code>9.501-1</code>\n\n"
        "Бот найдёт ссылку на расписание вашей группы.",
        parse_mode="HTML"
    )

@dp.message()
async def handle_message(message: types.Message):
    query = message.text.strip()
    
    if len(query) < 2:
        return
    
    msg = await message.answer(f"⏳ Ищу <b>{query}</b>...", parse_mode="HTML")
    
    group_url = await search_group_url(query)
    
    await msg.delete()
    
    if group_url:
        await message.answer(
            f"📅 <b>{query}</b>\n\n"
            f"🔗 <a href='{group_url}'>Открыть расписание на сайте АлтГУ</a>",
            parse_mode="HTML",
            disable_web_page_preview=False
        )
    else:
        await message.answer(
            f"❌ <b>{query}</b> не найдено.\n\n"
            f"🔗 Откройте сайт: {TIMETABLE_URL}",
            parse_mode="HTML"
        )

async def handle_health(request):
    return web.Response(text="OK")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    logger.info("Starting bot...")
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
