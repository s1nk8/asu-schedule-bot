import asyncio
import logging
import os
import re
import sys
import time
from io import BytesIO
from typing import Dict, List, Optional
from urllib.parse import quote, unquote

from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    BufferedInputFile,
)
from bs4 import BeautifulSoup
import httpx
from PIL import Image, ImageDraw, ImageFont

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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.8",
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Запасной список институтов (так как сайт не отдаёт их напрямую)
INSTITUTES = [
    {"id": "1", "name": "Институт математики и информационных технологий (ИМИТ)"},
    {"id": "2", "name": "Институт гуманитарных наук (ИГН)"},
    {"id": "3", "name": "Институт географии (ИНГЕО)"},
    {"id": "4", "name": "Юридический институт (ЮИ)"},
    {"id": "5", "name": "Институт истории и международных отношений (ИИМО)"},
    {"id": "6", "name": "Институт биологии и биотехнологии (ИББ)"},
    {"id": "7", "name": "Институт химии и химико-фармацевтических технологий (ИХиХФТ)"},
    {"id": "8", "name": "Институт цифровых технологий, электроники и физики (ИЦТЭФ)"},
    {"id": "9", "name": "Международный институт экономики, менеджмента и информационных систем (МИЭМИС)"},
    {"id": "10", "name": "Колледж АлтГУ"},
]

# Популярные группы для быстрого выбора
POPULAR_GROUPS = [
    "9.501-1", "9.501-2", "9.502-1", "9.502-2",
    "4.101-1", "4.101-2", "4.102-1", "4.102-2",
    "1.201-1", "1.201-2", "1.202-1", "1.202-2",
    "5.301-1", "5.301-2", "5.302-1", "5.302-2",
    "8.401-1", "8.401-2", "8.402-1", "8.402-2",
    "3.001-1", "3.001-2", "6.101-1", "6.101-2",
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

async def fetch_url(url, timeout=15):
    """Загрузка URL с задержкой между запросами"""
    await asyncio.sleep(0.5)  # Защита от 429
    
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

async def search_timetable(query: str, search_type: str = "students"):
    """Поиск расписания через поисковую форму сайта"""
    logger.info(f"Searching: {query} (type: {search_type})")
    
    # Формируем URL для поиска
    params = f"query={quote(query)}&search_in={search_type}"
    url = f"{SEARCH_URL}?{params}"
    
    html = await fetch_url(url)
    
    if not html:
        return None
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Удаляем скрипты и стили
    for tag in soup(["script", "style"]):
        tag.decompose()
    
    # Ищем результаты
    results = []
    
    # Ищем таблицы
    for table in soup.find_all('table'):
        rows = table.find_all('tr')
        table_data = []
        for row in rows[:20]:
            cells = row.find_all(['td', 'th'])
            row_text = ' | '.join(c.get_text(strip=True) for c in cells if c.get_text(strip=True))
            if row_text and len(row_text) > 5:
                table_data.append(row_text)
        if table_data:
            results.append('\n'.join(table_data))
    
    # Ищем div с расписанием
    for div in soup.find_all('div', class_=True):
        classes = ' '.join(div.get('class', []))
        if any(w in classes.lower() for w in ['timetable', 'schedule', 'result', 'day', 'pair', 'lesson']):
            text = div.get_text(separator='\n', strip=True)
            if len(text) > 20:
                results.append(text[:1000])
    
    # Если ничего не нашли, ищем весь текст
    if not results:
        body = soup.find('body') or soup.find('main') or soup
        text = body.get_text(separator='\n', strip=True)
        lines = [line.strip() for line in text.split('\n') if line.strip() and len(line) > 10]
        
        # Ищем строки с query
        relevant = [line for line in lines if query.lower() in line.lower()]
        if relevant:
            results.append('\n'.join(relevant[:30]))
        else:
            # Берем первые строки
            results.append('\n'.join(lines[:30]))
    
    return '\n\n'.join(results[:5]) if results else None

async def get_schedule_text(query: str):
    """Получение расписания текстом"""
    # Пробуем прямой URL
    direct_url = f"{BASE_URL}/timetable/?group={quote(query)}"
    html = await fetch_url(direct_url)
    
    if html:
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(["script", "style"]):
            tag.decompose()
        
        tables = soup.find_all('table')
        if tables:
            result = []
            for table in tables[:3]:
                for row in table.find_all('tr')[:20]:
                    cells = [c.get_text(strip=True) for c in row.find_all(['td', 'th'])]
                    result.append(' | '.join(cells))
            return '\n'.join(result) if result else None
    
    # Если прямой URL не дал результатов - используем поиск
    return await search_timetable(query, "students")

def text_to_image(text: str, title: str = "") -> BytesIO:
    """Создает изображение из текста"""
    width = 800
    padding = 20
    font_size = 14
    title_font_size = 22
    line_height = 20
    
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", title_font_size)
    except:
        font = ImageFont.load_default()
        title_font = ImageFont.load_default()
    
    lines = []
    for line in text.split('\n'):
        words = line.split(' ')
        current = ""
        for word in words:
            test = current + " " + word if current else word
            if len(test) * 7 < width - 2 * padding:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
    
    height = padding * 2 + title_font_size + 30 + len(lines) * line_height + padding
    
    image = Image.new('RGB', (width, max(height, 100)), 'white')
    draw = ImageDraw.Draw(image)
    
    if title:
        draw.text((padding, padding), title, fill='darkblue', font=title_font)
    
    y = padding + title_font_size + 15
    draw.line([(padding, y), (width - padding, y)], fill='gray', width=1)
    y += 10
    
    for line in lines:
        if line.strip():
            color = 'black'
            if '|' in line and line.index('|') < 10:
                color = 'darkblue'
            draw.text((padding, y), line, fill=color, font=font)
        y += line_height
    
    img_byte_arr = BytesIO()
    image.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    
    return img_byte_arr

# Обработчики
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 <b>Привет!</b> Я бот расписания АлтГУ.\n\n"
        "🔍 <b>Найти расписание</b> - поиск по группе/преподавателю/аудитории\n"
        "📋 <b>Популярные группы</b> - быстрый выбор\n\n"
        "Или отправьте команду:\n"
        "<code>/search 9.501-1</code>",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )

@dp.message(Command("search"))
async def cmd_search(message: types.Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❌ Укажите запрос.\nПример: <code>/search 9.501-1</code>", parse_mode="HTML")
        return
    
    query = parts[1].strip()
    msg = await message.answer("⏳ Ищу расписание...")
    
    result = await get_schedule_text(query)
    
    await msg.delete()
    
    if result:
        if len(result) > 4000:
            for i in range(0, len(result), 4000):
                await message.answer(f"<pre>{result[i:i+4000]}</pre>", parse_mode="HTML")
        else:
            await message.answer(f"📅 <b>Результаты для:</b> <code>{query}</code>\n\n<pre>{result}</pre>", parse_mode="HTML")
    else:
        await message.answer(f"❌ Ничего не найдено для: <code>{query}</code>", parse_mode="HTML")

@dp.message(Command("image"))
async def cmd_image(message: types.Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❌ Укажите запрос.\nПример: <code>/image 9.501-1</code>", parse_mode="HTML")
        return
    
    query = parts[1].strip()
    msg = await message.answer("⏳ Создаю изображение...")
    
    result = await get_schedule_text(query)
    
    await msg.delete()
    
    if result:
        img = text_to_image(result, f"Расписание: {query}")
        photo = BufferedInputFile(img.read(), filename="schedule.png")
        await message.answer_photo(photo, caption=f"📅 {query}")
    else:
        await message.answer(f"❌ Ничего не найдено для: <code>{query}</code>", parse_mode="HTML")

@dp.message(F.text == "🔍 Найти расписание")
async def btn_search(message: types.Message):
    await message.answer(
        "<b>Что ищем?</b>\n\n"
        "Отправьте номер группы, фамилию преподавателя или номер аудитории.\n\n"
        "<b>Примеры:</b>\n"
        "• 9.501-1\n"
        "• Иванов И.И.\n"
        "• 327М",
        parse_mode="HTML",
        reply_markup=get_search_menu()
    )

@dp.message(F.text == "📋 Популярные группы")
async def btn_popular(message: types.Message):
    keyboard = []
    for i in range(0, len(POPULAR_GROUPS), 3):
        row = []
        for group in POPULAR_GROUPS[i:i+3]:
            row.append(InlineKeyboardButton(text=group, callback_data=f"popular_{group}"))
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_start")])
    
    await message.answer(
        "📋 <b>Популярные группы:</b>\nВыберите или отправьте свою:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@dp.callback_query(F.data.startswith("popular_"))
async def cb_popular(callback: CallbackQuery):
    await callback.answer()
    group = callback.data.replace("popular_", "")
    
    await callback.message.edit_text(f"⏳ Ищу расписание группы {group}...")
    
    result = await get_schedule_text(group)
    
    if result:
        try:
            await callback.message.edit_text(
                f"📅 <b>{group}</b>\n\n<pre>{result[:4000]}</pre>",
                parse_mode="HTML"
            )
        except:
            await callback.message.delete()
            for i in range(0, len(result), 4000):
                await callback.message.answer(f"<pre>{result[i:i+4000]}</pre>", parse_mode="HTML")
    else:
        await callback.message.edit_text(
            f"❌ Расписание для {group} не найдено.\nПопробуйте другой номер группы.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_start")]
            ])
        )

@dp.callback_query(F.data == "search_students")
async def cb_search_students(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "🎓 <b>Поиск расписания студентов</b>\n\n"
        "Отправьте номер группы:\n"
        "<code>9.501-1</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_start")]
        ])
    )

@dp.callback_query(F.data == "search_teachers")
async def cb_search_teachers(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "👨‍🏫 <b>Поиск преподавателя</b>\n\n"
        "Отправьте фамилию:\n"
        "<code>Иванов</code> или <code>Иванов И.И.</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_start")]
        ])
    )

@dp.callback_query(F.data == "search_rooms")
async def cb_search_rooms(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "🏛 <b>Поиск аудитории</b>\n\n"
        "Отправьте номер:\n"
        "<code>327М</code> или <code>215</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_start")]
        ])
    )

@dp.callback_query(F.data == "back_to_start")
async def cb_back_start(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "Главное меню. Используйте кнопки ниже.",
        reply_markup=None
    )
    await callback.message.answer(
        "Выберите действие:",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "🌐 Сайт АлтГУ")
async def btn_website(message: types.Message):
    await message.answer(f"🔗 {TIMETABLE_URL}")

@dp.message(F.text == "❓ Помощь")
async def btn_help(message: types.Message):
    await message.answer(
        "<b>📚 Помощь:</b>\n\n"
        "<b>🔍 Найти расписание</b> - поиск\n"
        "<b>📋 Популярные группы</b> - быстрый выбор\n\n"
        "<b>Команды:</b>\n"
        "/search 9.501-1 - поиск текстом\n"
        "/image 9.501-1 - поиск картинкой\n"
        "/start - меню\n"
        "/help - справка",
        parse_mode="HTML"
    )

@dp.message()
async def handle_message(message: types.Message):
    """Обработка любых текстовых сообщений как поискового запроса"""
    query = message.text.strip()
    
    # Определяем тип поиска по содержимому
    if re.match(r'^[\d]', query):
        search_type = "students"
    elif re.match(r'^[А-Яа-яЁё]', query):
        search_type = "lecturers"
    else:
        search_type = "students"
    
    msg = await message.answer(f"⏳ Ищу: <b>{query}</b>...", parse_mode="HTML")
    
    # Пробуем прямой URL
    result = await get_schedule_text(query)
    
    # Если не нашли - пробуем поиск
    if not result:
        result = await search_timetable(query, search_type)
    
    await msg.delete()
    
    if result:
        if len(result) > 4000:
            for i in range(0, len(result), 4000):
                await message.answer(f"<pre>{result[i:i+4000]}</pre>", parse_mode="HTML")
        else:
            await message.answer(
                f"📅 <b>Результаты:</b> <code>{query}</code>\n\n<pre>{result}</pre>",
                parse_mode="HTML"
            )
    else:
        await message.answer(
            f"❌ Ничего не найдено.\n\n"
            f"🔍 Попробуйте:\n"
            f"• Другой номер группы\n"
            f"• Только фамилию преподавателя\n"
            f"• Номер аудитории без буквы\n\n"
            f"Или откройте сайт: {TIMETABLE_URL}",
            parse_mode="HTML"
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
    await start_web_server()
    logger.info("Starting polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
