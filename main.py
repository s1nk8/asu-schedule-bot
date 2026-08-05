import asyncio
import logging
import os
import re
import sys
import time
from typing import Dict, List, Optional
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

# Заголовки для имитации браузера
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

# Инициализация бота с увеличенным таймаутом
bot = Bot(token=BOT_TOKEN, session_timeout=60)
dp = Dispatcher()

# Кэширование
class Cache:
    def __init__(self):
        self.institutes = []
        self.groups = {}
        self.last_update = {}
        self.cache_ttl = 3600
    
    def is_valid(self, key):
        return key in self.last_update and (time.time() - self.last_update[key]) < self.cache_ttl
    
    def update(self, key):
        self.last_update[key] = time.time()

cache = Cache()

# Клавиатуры
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Расписание")],
            [KeyboardButton(text="🌐 Сайт АлтГУ"), KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True,
    )

def get_schedule_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎓 Студенты", callback_data="type_students")],
            [InlineKeyboardButton(text="👨‍🏫 Преподаватели", callback_data="type_teachers")],
            [InlineKeyboardButton(text="🏛 Аудитории", callback_data="type_rooms")],
        ]
    )

async def fetch_with_retry(url, max_retries=3):
    """Загрузка URL с повторными попытками"""
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                headers=HEADERS,
                timeout=30.0,
                verify=False
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.text
        except httpx.TimeoutException:
            logger.warning(f"Timeout for {url}, attempt {attempt + 1}/{max_retries}")
            if attempt == max_retries - 1:
                return None
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            if attempt == max_retries - 1:
                return None
            await asyncio.sleep(2)
    return None

async def fetch_institutes():
    if cache.is_valid("institutes"):
        return cache.institutes
    
    html = await fetch_with_retry(TIMETABLE_URL)
    if not html:
        return get_fallback_institutes()
    
    soup = BeautifulSoup(html, 'html.parser')
    institutes = []
    
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        if '/timetable/students/' in href:
            match = re.search(r'/students/(\d+)/?', href)
            if match:
                inst_id = match.group(1)
                name = link.get_text(strip=True)
                if name and len(name) > 2:
                    if not any(i['id'] == inst_id for i in institutes):
                        institutes.append({'id': inst_id, 'name': name[:50]})
    
    if institutes:
        cache.institutes = institutes
        cache.update("institutes")
        logger.info(f"Found {len(institutes)} institutes")
        return institutes
    
    return get_fallback_institutes()

def get_fallback_institutes():
    return [
        {"id": "1", "name": "ИМИТ (Институт математики и ИТ)"},
        {"id": "2", "name": "ИГН (Институт гуманитарных наук)"},
        {"id": "3", "name": "ИНГЕО (Институт географии)"},
        {"id": "4", "name": "ЮИ (Юридический институт)"},
        {"id": "5", "name": "ИИМО (Исторический)"},
        {"id": "6", "name": "ИББ (Биологии и биотехнологии)"},
        {"id": "7", "name": "ИХиХФТ (Химический)"},
        {"id": "8", "name": "ИЦТЭФ (Цифровых технологий)"},
        {"id": "9", "name": "МИЭМИС (Экономический)"},
        {"id": "10", "name": "Колледж АлтГУ"},
    ]

async def fetch_groups(inst_id):
    cache_key = f"groups_{inst_id}"
    if cache.is_valid(cache_key) and inst_id in cache.groups:
        return cache.groups[inst_id]
    
    url = f"{BASE_URL}/timetable/students/{inst_id}/"
    html = await fetch_with_retry(url)
    if not html:
        return []
    
    soup = BeautifulSoup(html, 'html.parser')
    groups = []
    
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        if 'group=' in href:
            group_name = link.get_text(strip=True)
            if group_name and group_name not in groups:
                groups.append(group_name)
    
    if groups:
        cache.groups[inst_id] = sorted(set(groups))
        cache.update(cache_key)
        logger.info(f"Found {len(groups)} groups for institute {inst_id}")
    
    return cache.groups.get(inst_id, [])

async def get_schedule(query):
    url = f"{BASE_URL}/timetable/?group={query}"
    html = await fetch_with_retry(url)
    
    if not html:
        return "❌ Сервер АлтГУ временно недоступен. Попробуйте позже."
    
    soup = BeautifulSoup(html, 'html.parser')
    text_parts = []
    
    # Ищем расписание
    days = soup.find_all(['div', 'table'], class_=re.compile(r'day|timetable', re.I))
    for day in days[:7]:
        day_text = day.get_text(separator='\n', strip=True)
        if len(day_text) > 20:
            text_parts.append(day_text[:500])
    
    if text_parts:
        result = f"📅 <b>Расписание для:</b> <code>{query}</code>\n\n"
        for i, part in enumerate(text_parts, 1):
            result += f"<b>День {i}:</b>\n{part}\n\n"
        return result
    
    # Поиск по тексту
    all_text = soup.get_text(separator='\n', strip=True)
    lines = [line.strip() for line in all_text.split('\n') if query.lower() in line.lower()]
    
    if lines:
        return f"📅 <b>Расписание для:</b> <code>{query}</code>\n\n" + '\n'.join(lines[:20])
    
    return f"📅 <b>Расписание для:</b> <code>{query}</code>\n\n❌ Не найдено на сайте."

# Обработчики команд
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 <b>Привет!</b> Я бот расписания АлтГУ.\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )

@dp.message(Command("schedule"))
async def cmd_schedule(message: types.Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❌ Укажите группу. Пример: /schedule 9.501-1")
        return
    
    query = parts[1].strip()
    msg = await message.answer(f"⏳ Ищу расписание для <b>{query}</b>...", parse_mode="HTML")
    
    schedule = await get_schedule(query)
    
    try:
        await msg.edit_text(schedule, parse_mode="HTML")
    except:
        await msg.delete()
        if len(schedule) > 4000:
            for i in range(0, len(schedule), 4000):
                await message.answer(schedule[i:i+4000], parse_mode="HTML")
        else:
            await message.answer(schedule, parse_mode="HTML")

@dp.message(F.text == "📅 Расписание")
async def btn_schedule(message: types.Message):
    await message.answer("Выберите тип расписания:", reply_markup=get_schedule_menu())

@dp.message(F.text == "🌐 Сайт АлтГУ")
async def btn_website(message: types.Message):
    await message.answer(f"🔗 Сайт расписания: {TIMETABLE_URL}")

@dp.message(F.text == "❓ Помощь")
async def btn_help(message: types.Message):
    await message.answer(
        "<b>📚 Помощь:</b>\n\n"
        "• Нажмите <b>📅 Расписание</b>\n"
        "• Выберите институт и группу\n\n"
        "<b>Прямые команды:</b>\n"
        "/schedule 9.501-1 - расписание группы",
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "type_students")
async def cb_students(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("⏳ Загружаю институты...")
    
    institutes = await fetch_institutes()
    
    keyboard = []
    for inst in institutes:
        keyboard.append([
            InlineKeyboardButton(text=inst['name'][:40], callback_data=f"inst_{inst['id']}")
        ])
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])
    
    await callback.message.edit_text(
        "🏛 <b>Выберите институт:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@dp.callback_query(F.data == "type_teachers")
async def cb_teachers(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "👨‍🏫 Отправьте: <code>/schedule Фамилия И.О.</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
        ])
    )

@dp.callback_query(F.data == "type_rooms")
async def cb_rooms(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "🏛 Отправьте: <code>/schedule НомерАудитории</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
        ])
    )

@dp.callback_query(F.data.startswith("inst_"))
async def cb_institute(callback: CallbackQuery):
    await callback.answer()
    inst_id = callback.data.replace("inst_", "")
    
    await callback.message.edit_text("⏳ Загружаю группы...")
    groups = await fetch_groups(inst_id)
    
    if not groups:
        await callback.message.edit_text(
            "❌ Группы не найдены. Используйте: /schedule НомерГруппы",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="type_students")]
            ])
        )
        return
    
    keyboard = []
    for i in range(0, len(groups), 2):
        row = []
        for group in groups[i:i+2]:
            row.append(InlineKeyboardButton(text=group[:20], callback_data=f"group_{group}"))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(text="🔙 К институтам", callback_data="type_students")])
    
    await callback.message.edit_text(
        f"👥 <b>Выберите группу:</b> (найдено {len(groups)})",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@dp.callback_query(F.data.startswith("group_"))
async def cb_group(callback: CallbackQuery):
    await callback.answer()
    group = callback.data.replace("group_", "")
    
    await callback.message.edit_text(f"⏳ Загружаю расписание группы <b>{group}</b>...", parse_mode="HTML")
    
    schedule = await get_schedule(group)
    
    try:
        await callback.message.edit_text(schedule, parse_mode="HTML")
    except:
        await callback.message.delete()
        if len(schedule) > 4000:
            for i in range(0, len(schedule), 4000):
                await callback.message.answer(schedule[i:i+4000], parse_mode="HTML")
        else:
            await callback.message.answer(schedule, parse_mode="HTML")

@dp.callback_query(F.data == "back_to_menu")
async def cb_back(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Выберите тип расписания:", reply_markup=get_schedule_menu())

# Веб-сервер
async def handle_health(request):
    return web.Response(text="Bot is running")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    
    logger.info(f"Web server on port {port}")
    await site.start()

async def main():
    logger.info("Starting bot...")
    
    # Запускаем веб-сервер
    await start_web_server()
    
    # Запускаем бота с повторными попытками
    for attempt in range(5):
        try:
            logger.info(f"Starting bot polling (attempt {attempt + 1})...")
            await dp.start_polling(bot)
            break
        except Exception as e:
            logger.error(f"Polling error: {e}")
            if attempt < 4:
                await asyncio.sleep(5)
            else:
                logger.error("Max retries reached")
                raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
