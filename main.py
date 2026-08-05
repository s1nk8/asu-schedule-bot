import asyncio
import logging
import os
import re
import time
from typing import Dict, List, Optional, Tuple
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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = "8639721738:AAEX_xUw7rtNLCVCFys2ng9zAWFjgO74NjU"
BASE_URL = "https://www.asu.ru"
TIMETABLE_URL = f"{BASE_URL}/timetable/"

# Заголовки для имитации браузера
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Кэширование данных
class Cache:
    def __init__(self):
        self.institutes: List[Dict] = []
        self.groups: Dict[str, List[str]] = {}  # inst_id -> groups
        self.last_update: Dict[str, float] = {}
        self.cache_ttl = 1800  # 30 минут
    
    def is_valid(self, key: str) -> bool:
        return key in self.last_update and (time.time() - self.last_update[key]) < self.cache_ttl
    
    def update(self, key: str):
        self.last_update[key] = time.time()

cache = Cache()

# Клавиатуры
def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Главная клавиатура бота"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Расписание")],
            [KeyboardButton(text="🌐 Сайт АлтГУ"), KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True,
    )

def get_schedule_menu() -> InlineKeyboardMarkup:
    """Меню выбора типа расписания"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎓 Студенты", callback_data="type_students")],
            [InlineKeyboardButton(text="👨‍🏫 Преподаватели", callback_data="type_teachers")],
            [InlineKeyboardButton(text="🏛 Аудитории", callback_data="type_rooms")],
        ]
    )

# Парсинг данных с сайта
async def fetch_url(url: str) -> Optional[str]:
    """Безопасная загрузка URL"""
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
    except httpx.HTTPError as e:
        logger.error(f"HTTP error for {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return None

async def fetch_institutes() -> List[Dict]:
    """Получение списка институтов с сайта"""
    if cache.is_valid("institutes"):
        logger.info("Using cached institutes")
        return cache.institutes
    
    logger.info("Fetching institutes from website")
    html = await fetch_url(TIMETABLE_URL)
    if not html:
        return get_fallback_institutes()
    
    soup = BeautifulSoup(html, 'html.parser')
    institutes = []
    
    # Поиск всех ссылок на страницы институтов
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        if '/timetable/students/' in href:
            # Извлекаем ID института из URL
            match = re.search(r'/students/(\d+)/?', href)
            if match:
                inst_id = match.group(1)
                name = link.get_text(strip=True)
                if name and len(name) > 2:
                    # Убираем дубликаты
                    if not any(i['id'] == inst_id for i in institutes):
                        institutes.append({
                            'id': inst_id,
                            'name': name[:50]  # Ограничиваем длину
                        })
    
    if institutes:
        cache.institutes = institutes
        cache.update("institutes")
        logger.info(f"Found {len(institutes)} institutes")
        return institutes
    
    logger.warning("No institutes found, using fallback")
    return get_fallback_institutes()

def get_fallback_institutes() -> List[Dict]:
    """Запасной список институтов"""
    return [
        {"id": "1", "name": "Институт математики и ИТ"},
        {"id": "2", "name": "Институт гуманитарных наук"},
        {"id": "3", "name": "Институт географии"},
        {"id": "4", "name": "Юридический институт"},
        {"id": "5", "name": "Институт истории и международных отношений"},
        {"id": "6", "name": "Институт биологии и биотехнологии"},
        {"id": "7", "name": "Институт химии и химико-фармацевтических технологий"},
        {"id": "8", "name": "Институт цифровых технологий, электроники и физики"},
        {"id": "9", "name": "Международный институт экономики, менеджмента и информационных систем"},
        {"id": "10", "name": "Колледж АлтГУ"},
    ]

async def fetch_groups(inst_id: str) -> List[str]:
    """Получение списка групп института"""
    cache_key = f"groups_{inst_id}"
    if cache.is_valid(cache_key) and inst_id in cache.groups:
        logger.info(f"Using cached groups for institute {inst_id}")
        return cache.groups[inst_id]
    
    logger.info(f"Fetching groups for institute {inst_id}")
    url = f"{BASE_URL}/timetable/students/{inst_id}/"
    html = await fetch_url(url)
    if not html:
        return []
    
    soup = BeautifulSoup(html, 'html.parser')
    groups = []
    
    # Ищем ссылки на группы
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        if 'group=' in href:
            group_name = link.get_text(strip=True)
            if group_name and group_name not in groups:
                groups.append(group_name)
    
    # Альтернативный поиск в таблицах
    if not groups:
        for row in soup.find_all(['tr', 'div'], class_=re.compile(r'group|group-row', re.I)):
            text = row.get_text(strip=True)
            if text and len(text) < 50:
                groups.append(text)
    
    if groups:
        cache.groups[inst_id] = sorted(set(groups))
        cache.update(cache_key)
        logger.info(f"Found {len(groups)} groups for institute {inst_id}")
    else:
        logger.warning(f"No groups found for institute {inst_id}")
    
    return cache.groups.get(inst_id, [])

async def get_schedule(query: str) -> str:
    """Получение расписания по запросу"""
    url = f"{BASE_URL}/timetable/?group={query}"
    logger.info(f"Fetching schedule for: {query}")
    
    html = await fetch_url(url)
    if not html:
        return "❌ Не удалось получить расписание. Попробуйте позже."
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Поиск расписания в разных форматах
    schedule_blocks = []
    
    # Поиск по дням недели
    days = soup.find_all(['div', 'table'], class_=re.compile(r'day|timetable', re.I))
    for day in days[:7]:  # Максимум 7 дней
        day_text = day.get_text(separator='\n', strip=True)
        if day_text and query.lower() in day_text.lower():
            schedule_blocks.append(day_text[:500])
    
    if schedule_blocks:
        result = f"📅 <b>Расписание для:</b> <code>{query}</code>\n\n"
        for i, block in enumerate(schedule_blocks, 1):
            result += f"<b>День {i}:</b>\n{block}\n\n"
        return result
    
    # Альтернативный поиск
    all_text = soup.get_text(separator='\n', strip=True)
    lines = all_text.split('\n')
    relevant_lines = [line.strip() for line in lines if query.lower() in line.lower()]
    
    if relevant_lines:
        return f"📅 <b>Расписание для:</b> <code>{query}</code>\n\n" + '\n'.join(relevant_lines[:20])
    
    return f"📅 <b>Расписание для:</b> <code>{query}</code>\n\n❌ Расписание не найдено на сайте."

# Обработчики команд
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    await message.answer(
        "👋 <b>Привет!</b> Я бот расписания АлтГУ.\n\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Обработчик команды /help"""
    await message.answer(
        "<b>📚 Как пользоваться ботом:</b>\n\n"
        "1️⃣ Нажмите <b>📅 Расписание</b>\n"
        "2️⃣ Выберите тип расписания\n"
        "3️⃣ Выберите институт и группу\n\n"
        "<b>Прямые команды:</b>\n"
        "• /schedule 9.501-1 - расписание группы\n"
        "• /schedule Иванов И.И. - расписание преподавателя\n"
        "• /schedule 327М - расписание аудитории\n"
        "• /update - обновить списки",
        parse_mode="HTML"
    )

@dp.message(Command("schedule"))
async def cmd_schedule(message: types.Message):
    """Обработчик команды /schedule"""
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❌ Укажите группу/преподавателя/аудиторию\nПример: /schedule 9.501-1")
        return
    
    query = parts[1].strip()
    msg = await message.answer(f"⏳ Ищу расписание для <b>{query}</b>...", parse_mode="HTML")
    
    schedule = await get_schedule(query)
    
    # Разбиваем длинные сообщения
    if len(schedule) > 4000:
        for i in range(0, len(schedule), 4000):
            await message.answer(schedule[i:i+4000], parse_mode="HTML")
        await msg.delete()
    else:
        await msg.edit_text(schedule, parse_mode="HTML")

@dp.message(Command("update"))
async def cmd_update(message: types.Message):
    """Принудительное обновление кэша"""
    global cache
    cache = Cache()
    await message.answer("✅ Кэш очищен. Данные будут загружены заново.")

@dp.message(F.text == "📅 Расписание")
async def btn_schedule(message: types.Message):
    """Кнопка выбора расписания"""
    await message.answer(
        "Выберите тип расписания:",
        reply_markup=get_schedule_menu()
    )

@dp.message(F.text == "🌐 Сайт АлтГУ")
async def btn_website(message: types.Message):
    """Кнопка сайта"""
    await message.answer(f"🔗 Официальный сайт: {TIMETABLE_URL}")

@dp.message(F.text == "❓ Помощь")
async def btn_help(message: types.Message):
    """Кнопка помощи"""
    await cmd_help(message)

# Callback обработчики
@dp.callback_query(F.data == "type_students")
async def cb_students(callback: CallbackQuery):
    """Показать список институтов"""
    await callback.answer()
    await callback.message.edit_text("⏳ Загружаю список институтов...")
    
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
    """Инструкция по поиску преподавателей"""
    await callback.answer()
    await callback.message.edit_text(
        "👨‍🏫 <b>Расписание преподавателя</b>\n\n"
        "Отправьте команду:\n"
        "<code>/schedule Фамилия И.О.</code>\n\n"
        "Пример: /schedule Иванов И.И.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
        ])
    )

@dp.callback_query(F.data == "type_rooms")
async def cb_rooms(callback: CallbackQuery):
    """Инструкция по поиску аудиторий"""
    await callback.answer()
    await callback.message.edit_text(
        "🏛 <b>Расписание аудитории</b>\n\n"
        "Отправьте команду:\n"
        "<code>/schedule НомерАудитории</code>\n\n"
        "Пример: /schedule 327М",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
        ])
    )

@dp.callback_query(F.data.startswith("inst_"))
async def cb_institute_selected(callback: CallbackQuery):
    """Выбор группы после выбора института"""
    await callback.answer()
    inst_id = callback.data.replace("inst_", "")
    
    await callback.message.edit_text(f"⏳ Загружаю группы института...")
    
    groups = await fetch_groups(inst_id)
    
    if not groups:
        await callback.message.edit_text(
            "❌ Не удалось загрузить список групп.\n"
            "Попробуйте использовать команду:\n"
            "<code>/schedule НомерГруппы</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="type_students")]
            ])
        )
        return
    
    # Создаем клавиатуру с группами (по 2 в ряд)
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
        f"👥 <b>Выберите группу:</b>\nНайдено групп: {len(groups)}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@dp.callback_query(F.data.startswith("group_"))
async def cb_group_selected(callback: CallbackQuery):
    """Показать расписание для выбранной группы"""
    await callback.answer()
    group = callback.data.replace("group_", "")
    
    await callback.message.edit_text(f"⏳ Загружаю расписание группы <b>{group}</b>...", parse_mode="HTML")
    
    schedule = await get_schedule(group)
    
    try:
        await callback.message.edit_text(schedule, parse_mode="HTML")
    except Exception:
        # Если не помещается в одно сообщение
        await callback.message.delete()
        for i in range(0, len(schedule), 4000):
            await callback.message.answer(schedule[i:i+4000], parse_mode="HTML")

@dp.callback_query(F.data == "back_to_menu")
async def cb_back_to_menu(callback: CallbackQuery):
    """Возврат в главное меню"""
    await callback.answer()
    await callback.message.edit_text(
        "Выберите тип расписания:",
        reply_markup=get_schedule_menu()
    )

# Веб-сервер для Amvera
async def handle_health(request):
    """Эндпоинт для проверки здоровья"""
    return web.Response(text="Bot is running")

async def start_web_server():
    """Запуск веб-сервера"""
    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    
    logger.info(f"Starting web server on port {port}")
    await site.start()

async def main():
    """Главная функция"""
    logger.info("Starting bot...")
    
    # Запускаем веб-сервер
    await start_web_server()
    
    # Запускаем бота
    logger.info("Starting bot polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
