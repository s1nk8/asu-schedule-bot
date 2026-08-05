import asyncio
import logging
import os
import re
import sys
from typing import Optional
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

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8639721738:AAEX_xUw7rtNLCVCFys2ng9zAWFjgO74NjU")
BASE_URL = "https://www.asu.ru"
TIMETABLE_URL = f"{BASE_URL}/timetable/"
SEARCH_URL = f"{BASE_URL}/timetable/search/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Популярные группы
POPULAR_GROUPS = [
    "9.501-1", "9.501-2", "9.502-1", "9.502-2",
    "4.101-1", "4.101-2", "4.102-1", "4.102-2",
    "1.201-1", "1.201-2", "1.202-1", "1.202-2",
    "5.301-1", "5.301-2", "5.302-1", "5.302-2",
    "8.401-1", "8.401-2", "8.402-1", "8.402-2",
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

def get_search_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎓 Студенты", callback_data="search_students")],
            [InlineKeyboardButton(text="👨‍🏫 Преподаватели", callback_data="search_teachers")],
            [InlineKeyboardButton(text="🏛 Аудитории", callback_data="search_rooms")],
        ]
    )

async def fetch_url(url, timeout=10):
    """Загрузка URL"""
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            headers=HEADERS,
            timeout=timeout,
            verify=False
        ) as client:
            response = await client.get(url)
            if response.status_code == 200:
                return response.text
            else:
                logger.error(f"HTTP {response.status_code} for {url}")
                return None
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return None

async def get_schedule(query: str):
    """Получение расписания"""
    # Пробуем прямой URL
    url = f"{BASE_URL}/timetable/?group={quote(query)}"
    html = await fetch_url(url)
    
    if not html:
        return None
    
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    
    # Ищем таблицы
    tables = soup.find_all('table')
    if tables:
        result = []
        for table in tables[:3]:
            for row in table.find_all('tr')[:30]:
                cells = [c.get_text(strip=True) for c in row.find_all(['td', 'th'])]
                if cells:
                    result.append(' | '.join(cells))
        if result:
            return '\n'.join(result)
    
    # Ищем div с расписанием
    for div in soup.find_all('div', class_=True):
        classes = ' '.join(div.get('class', []))
        if any(w in classes.lower() for w in ['timetable', 'schedule', 'day', 'rasp']):
            text = div.get_text(separator='\n', strip=True)
            if len(text) > 30:
                return text[:2000]
    
    # Берем весь текст
    body = soup.find('body') or soup
    text = body.get_text(separator='\n', strip=True)
    lines = [line.strip() for line in text.split('\n') if line.strip() and len(line) > 10]
    
    # Ищем строки с query
    relevant = [line for line in lines if query.lower() in line.lower()]
    if relevant:
        return '\n'.join(relevant[:30])
    
    # Возвращаем первые строки
    return '\n'.join(lines[:20]) if lines else None

# Обработчики команд
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 <b>Бот расписания АлтГУ</b>\n\n"
        "Отправьте номер группы, например:\n"
        "<code>9.501-1</code>\n\n"
        "Или используйте кнопки меню.",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "🔍 Найти расписание")
async def btn_search(message: types.Message):
    await message.answer(
        "Отправьте номер группы, фамилию преподавателя или аудиторию:",
        reply_markup=get_search_menu()
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
    
    await callback.message.edit_text(f"⏳ Поиск группы <b>{group}</b>...", parse_mode="HTML")
    
    result = await get_schedule(group)
    
    if result:
        try:
            await callback.message.edit_text(
                f"📅 <b>{group}</b>\n\n<pre>{result[:3500]}</pre>",
                parse_mode="HTML"
            )
        except:
            await callback.message.delete()
            for i in range(0, len(result), 3500):
                await callback.message.answer(f"<pre>{result[i:i+3500]}</pre>", parse_mode="HTML")
    else:
        await callback.message.edit_text(
            f"❌ Расписание для <b>{group}</b> не найдено.",
            parse_mode="HTML"
        )

@dp.callback_query(F.data == "search_students")
async def cb_students(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("🎓 Отправьте номер группы:")

@dp.callback_query(F.data == "search_teachers")
async def cb_teachers(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("👨‍🏫 Отправьте фамилию преподавателя:")

@dp.callback_query(F.data == "search_rooms")
async def cb_rooms(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("🏛 Отправьте номер аудитории:")

@dp.message(F.text == "🌐 Сайт АлтГУ")
async def btn_website(message: types.Message):
    await message.answer(f"🔗 {TIMETABLE_URL}")

@dp.message(F.text == "❓ Помощь")
async def btn_help(message: types.Message):
    await message.answer(
        "<b>📚 Помощь:</b>\n\n"
        "Просто отправьте боту:\n"
        "• <code>9.501-1</code> - группа\n"
        "• <code>Иванов</code> - преподаватель\n"
        "• <code>327М</code> - аудитория\n\n"
        "Или используйте кнопки меню.",
        parse_mode="HTML"
    )

@dp.message()
async def handle_message(message: types.Message):
    """Обработка всех текстовых сообщений"""
    query = message.text.strip()
    
    # Пропускаем слишком короткие
    if len(query) < 2:
        await message.answer("Отправьте номер группы (например: 9.501-1)")
        return
    
    msg = await message.answer(f"⏳ Поиск...")
    
    result = await get_schedule(query)
    
    await msg.delete()
    
    if result:
        if len(result) > 3500:
            for i in range(0, len(result), 3500):
                await message.answer(f"<pre>{result[i:i+3500]}</pre>", parse_mode="HTML")
        else:
            await message.answer(
                f"📅 <b>{query}</b>\n\n<pre>{result}</pre>",
                parse_mode="HTML"
            )
    else:
        await message.answer(
            f"❌ Ничего не найдено.\n"
            f"Проверьте номер и попробуйте позже.\n"
            f"Сайт: {TIMETABLE_URL}",
            parse_mode="HTML"
        )

# Веб-сервер
async def handle_health(request):
    return web.Response(text="OK")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Web server on port {port}")

async def main():
    logger.info("Starting bot...")
    
    # Запускаем веб-сервер
    await start_web_server()
    
    # Запускаем бота
    logger.info("Starting polling...")
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Polling error: {e}")
        # Ждем и пробуем снова
        await asyncio.sleep(5)
        await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
    except Exception as e:
        logger.error(f"Fatal: {e}")
