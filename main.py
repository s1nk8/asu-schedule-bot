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

# Инициализация бота с базовыми настройками
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Кэширование
class Cache:
    def __init__(self):
        self.institutes = []
        self.groups = {}
        self.last_update = {}
        self.cache_ttl = 1800  # 30 минут
    
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

async def fetch_url(url, timeout=15):
    """Простая загрузка URL"""
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

def is_group_name(text):
    """Проверка, является ли текст названием группы"""
    if not text or len(text) < 3 or len(text) > 20:
        return False
    
    # Исключаем явно не группы
    exclude_words = ['http', 'www', 'javascript', 'mailto', 'tel:', 'api', 'json', 'xml']
    for word in exclude_words:
        if word in text.lower():
            return False
    
    # Группа должна содержать цифры
    if not re.search(r'\d', text):
        return False
    
    # Типичные паттерны групп АлтГУ: 9.501-1, 4.101-2 и т.д.
    if re.match(r'^\d+\.\d+[-.]?\d*$', text):
        return True
    
    # Если есть цифры и буквы/дефисы
    if re.search(r'[а-яА-Яa-zA-Z]', text) and len(text) < 15:
        return True
    
    return False

async def fetch_institutes():
    """Получение списка институтов"""
    if cache.is_valid("institutes") and cache.institutes:
        return cache.institutes
    
    logger.info("Fetching institutes...")
    html = await fetch_url(TIMETABLE_URL)
    
    if not html:
        logger.warning("Failed to fetch institutes")
        return get_fallback_institutes()
    
    soup = BeautifulSoup(html, 'html.parser')
    institutes = []
    
    # Ищем ссылки на /timetable/students/ID/
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        if '/timetable/students/' in href:
            match = re.search(r'/students/(\d+)/?', href)
            if match:
                inst_id = match.group(1)
                name = link.get_text(strip=True)
                if name and len(name) > 3 and len(name) < 100:
                    if not any(i['id'] == inst_id for i in institutes):
                        institutes.append({'id': inst_id, 'name': name})
    
    if institutes:
        logger.info(f"Found {len(institutes)} institutes")
        cache.institutes = institutes
        cache.update("institutes")
        return institutes
    
    return get_fallback_institutes()

def get_fallback_institutes():
    """Запасной список"""
    return [
        {"id": "1", "name": "Институт математики и ИТ"},
        {"id": "2", "name": "Институт гуманитарных наук"},
        {"id": "3", "name": "Институт географии"},
        {"id": "4", "name": "Юридический институт"},
        {"id": "5", "name": "Институт истории и международных отношений"},
        {"id": "6", "name": "Институт биологии и биотехнологии"},
        {"id": "7", "name": "Институт химии"},
        {"id": "8", "name": "Институт цифровых технологий"},
        {"id": "9", "name": "Международный институт экономики"},
        {"id": "10", "name": "Колледж АлтГУ"},
    ]

async def fetch_groups(inst_id):
    """Получение списка групп"""
    cache_key = f"groups_{inst_id}"
    if cache.is_valid(cache_key) and inst_id in cache.groups:
        return cache.groups[inst_id]
    
    logger.info(f"Fetching groups for institute {inst_id}")
    url = f"{BASE_URL}/timetable/students/{inst_id}/"
    html = await fetch_url(url)
    
    if not html:
        logger.warning(f"No HTML for institute {inst_id}")
        return []
    
    soup = BeautifulSoup(html, 'html.parser')
    groups = []
    
    # Ищем ТОЛЬКО ссылки, которые ведут на расписание
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        text = link.get_text(strip=True)
        
        # Ссылка должна вести на расписание группы
        if 'group=' in href and text:
            # Извлекаем название группы из ссылки
            match = re.search(r'group=([^&]+)', href)
            if match:
                group_name = match.group(1)
                # Декодируем URL
                try:
                    from urllib.parse import unquote
                    group_name = unquote(group_name)
                except:
                    pass
                
                if is_group_name(group_name) and group_name not in groups:
                    groups.append(group_name)
            elif is_group_name(text) and text not in groups:
                groups.append(text)
    
    # Очистка
    groups = [g.strip() for g in groups if is_group_name(g.strip())]
    groups = sorted(set(groups))
    
    if groups:
        logger.info(f"Found {len(groups)} groups: {groups[:5]}...")
        cache.groups[inst_id] = groups
        cache.update(cache_key)
    else:
        logger.warning(f"No groups found for institute {inst_id}")
    
    return groups

async def get_schedule(query):
    """Получение расписания"""
    logger.info(f"Getting schedule for: {query}")
    
    # Кодируем запрос для URL
    from urllib.parse import quote
    encoded_query = quote(query)
    url = f"{BASE_URL}/timetable/?group={encoded_query}"
    
    html = await fetch_url(url)
    
    if not html:
        return "❌ Сервер АлтГУ временно недоступен. Попробуйте позже."
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Удаляем скрипты и стили
    for script in soup(["script", "style"]):
        script.decompose()
    
    # Ищем расписание
    result_parts = []
    
    # Ищем таблицы или div с расписанием
    schedule_blocks = soup.find_all(['div', 'table'], class_=re.compile(r'day|schedule|timetable|pair|lesson', re.I))
    
    if schedule_blocks:
        for block in schedule_blocks[:14]:
            text = block.get_text(separator=' ', strip=True)
            if len(text) > 20:
                result_parts.append(text[:500])
    
    if result_parts:
        result = f"📅 <b>Расписание:</b> <code>{query}</code>\n\n"
        for i, part in enumerate(result_parts, 1):
            result += f"<b>📌 Занятие {i}:</b>\n{part}\n\n"
        return result
    
    # Если не нашли структурированное - ищем по тексту
    body = soup.find('body')
    if body:
        text = body.get_text(separator='\n', strip=True)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        # Ищем строки, где упоминается группа
        relevant = [line for line in lines if query.lower() in line.lower()]
        
        if relevant:
            result = f"📅 <b>Расписание:</b> <code>{query}</code>\n\n"
            result += '\n'.join(relevant[:20])
            return result
    
    # Пробуем найти хоть что-то похожее на расписание
    all_text = soup.get_text(separator='\n', strip=True)
    lines = all_text.split('\n')
    schedule_lines = []
    
    for line in lines:
        line = line.strip()
        # Ищем строки с временем (например, "8:00", "10:15")
        if re.search(r'\d{1,2}:\d{2}', line) and len(line) > 10:
            schedule_lines.append(line)
    
    if schedule_lines:
        result = f"📅 <b>Возможное расписание для:</b> <code>{query}</code>\n\n"
        result += '\n'.join(schedule_lines[:20])
        return result
    
    return (
        f"📅 <b>Запрос:</b> <code>{query}</code>\n\n"
        f"❌ Расписание не найдено.\n\n"
        f"💡 <i>Проверьте правильность номера группы или попробуйте позже.</i>"
    )

# Обработчики
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    logger.info(f"User {message.from_user.id} started")
    await message.answer(
        "👋 <b>Привет!</b> Я бот расписания АлтГУ.\n\n"
        "Выберите действие в меню:",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "<b>📚 Помощь:</b>\n\n"
        "<b>Через меню:</b>\n"
        "📅 Расписание → 🎓 Студенты → Институт → Группа\n\n"
        "<b>Прямая команда:</b>\n"
        "<code>/schedule 9.501-1</code>\n\n"
        "<b>Другие команды:</b>\n"
        "/start - главное меню\n"
        "/help - справка",
        parse_mode="HTML"
    )

@dp.message(Command("schedule"))
async def cmd_schedule(message: types.Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "❌ Укажите группу.\n"
            "Пример: <code>/schedule 9.501-1</code>",
            parse_mode="HTML"
        )
        return
    
    query = parts[1].strip()
    msg = await message.answer(f"⏳ Загружаю расписание...")
    
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
    await message.answer(
        "Выберите тип расписания:",
        reply_markup=get_schedule_menu()
    )

@dp.message(F.text == "🌐 Сайт АлтГУ")
async def btn_website(message: types.Message):
    await message.answer(f"🔗 {TIMETABLE_URL}")

@dp.message(F.text == "❓ Помощь")
async def btn_help(message: types.Message):
    await cmd_help(message)

@dp.callback_query(F.data == "type_students")
async def cb_students(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("⏳ Загружаю институты...")
    
    institutes = await fetch_institutes()
    
    keyboard = []
    for inst in institutes:
        keyboard.append([
            InlineKeyboardButton(
                text=inst['name'][:40],
                callback_data=f"inst_{inst['id']}"
            )
        ])
    keyboard.append([
        InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")
    ])
    
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
            "❌ Группы не найдены.\n\n"
            "Используйте ручной поиск:\n"
            "<code>/schedule НомерГруппы</code>\n\n"
            "Пример: <code>/schedule 9.501-1</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="type_students")]
            ])
        )
        return
    
    keyboard = []
    for i in range(0, len(groups), 2):
        row = []
        for group in groups[i:i+2]:
            row.append(InlineKeyboardButton(
                text=group[:20],
                callback_data=f"group_{group}"
            ))
        keyboard.append(row)
    keyboard.append([
        InlineKeyboardButton(text="🔙 К институтам", callback_data="type_students")
    ])
    
    await callback.message.edit_text(
        f"👥 <b>Выберите группу:</b> (найдено {len(groups)})",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@dp.callback_query(F.data.startswith("group_"))
async def cb_group(callback: CallbackQuery):
    await callback.answer()
    group = callback.data.replace("group_", "")
    
    await callback.message.edit_text(f"⏳ Загружаю расписание...")
    
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
    await callback.message.edit_text(
        "Выберите тип расписания:",
        reply_markup=get_schedule_menu()
    )

@dp.message()
async def handle_other(message: types.Message):
    await message.answer(
        "Используйте меню или команды:\n"
        "/start - главное меню\n"
        "/schedule - поиск расписания\n"
        "/help - справка"
    )

# Веб-сервер
async def handle_health(request):
    return web.Response(text="OK")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health)
    
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
    
    # Запускаем бота
    logger.info("Starting polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
