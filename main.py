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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
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
    """Главная клавиатура"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Расписание")],
            [KeyboardButton(text="🌐 Сайт АлтГУ"), KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True,
    )

def get_schedule_menu():
    """Меню выбора типа расписания"""
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
    """Получение списка институтов"""
    if cache.is_valid("institutes"):
        logger.info("Using cached institutes")
        return cache.institutes
    
    logger.info("Fetching institutes from website...")
    html = await fetch_with_retry(TIMETABLE_URL)
    if not html:
        logger.warning("Failed to fetch institutes, using fallback")
        return get_fallback_institutes()
    
    soup = BeautifulSoup(html, 'html.parser')
    institutes = []
    
    # Ищем все возможные ссылки на институты
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        text = link.get_text(strip=True)
        
        # Разные форматы ссылок на институты
        if '/timetable/students/' in href and text:
            match = re.search(r'/students/(\d+)/?', href)
            if match:
                inst_id = match.group(1)
                if text and len(text) > 2 and not any(i['id'] == inst_id for i in institutes):
                    institutes.append({'id': inst_id, 'name': text[:50]})
    
    # Если не нашли через ссылки, ищем в других элементах
    if not institutes:
        for element in soup.find_all(['div', 'li', 'option'], class_=re.compile(r'institute|faculty', re.I)):
            text = element.get_text(strip=True)
            link = element.find('a')
            if link:
                href = link.get('href', '')
                match = re.search(r'/students/(\d+)/?', href)
                if match and text:
                    institutes.append({'id': match.group(1), 'name': text[:50]})
    
    if institutes:
        cache.institutes = institutes
        cache.update("institutes")
        logger.info(f"Found {len(institutes)} institutes: {[i['name'] for i in institutes[:3]]}...")
        return institutes
    
    logger.warning("No institutes found on website, using fallback")
    return get_fallback_institutes()

def get_fallback_institutes():
    """Запасной список институтов"""
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
    """Получение списка групп института"""
    cache_key = f"groups_{inst_id}"
    if cache.is_valid(cache_key) and inst_id in cache.groups:
        logger.info(f"Using cached groups for institute {inst_id}")
        return cache.groups[inst_id]
    
    logger.info(f"Fetching groups for institute {inst_id}")
    url = f"{BASE_URL}/timetable/students/{inst_id}/"
    html = await fetch_with_retry(url)
    
    if not html:
        logger.error(f"No HTML received for institute {inst_id}")
        return []
    
    soup = BeautifulSoup(html, 'html.parser')
    groups = []
    
    # Способ 1: Ищем ссылки с параметром group
    logger.info("Trying method 1: links with group parameter")
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        if 'group=' in href:
            group_name = link.get_text(strip=True)
            if group_name and group_name not in groups and len(group_name) > 1:
                groups.append(group_name)
    
    # Способ 2: Ищем все ссылки с цифрами в тексте
    if not groups:
        logger.info("Trying method 2: links with numbers in text")
        for link in soup.find_all('a', href=True):
            text = link.get_text(strip=True)
            href = link.get('href', '')
            if text and re.search(r'\d', text) and len(text) < 30 and len(text) > 2:
                if '/timetable/' in href or 'group=' in href or 'students/' in href:
                    if text not in groups:
                        groups.append(text)
    
    # Способ 3: Ищем в элементах списка или таблицы
    if not groups:
        logger.info("Trying method 3: list items and table rows")
        for element in soup.find_all(['li', 'td', 'option', 'div'], class_=re.compile(r'group|specialty', re.I)):
            text = element.get_text(strip=True)
            if text and re.search(r'\d', text) and len(text) < 30 and len(text) > 2:
                if text not in groups:
                    groups.append(text)
    
    # Способ 4: Пробуем найти группы через JavaScript
    if not groups:
        logger.info("Trying method 4: JavaScript data")
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string:
                # Ищем массивы с группами
                matches = re.findall(r'["\']([\d][^"\']{2,20})["\']', script.string)
                for match in matches:
                    if re.search(r'[а-яА-Я]', match) or re.search(r'[\d]', match):
                        if match not in groups and len(match) < 30:
                            groups.append(match)
    
    # Способ 5: Пробуем API endpoint
    if not groups:
        logger.info("Trying method 5: API endpoint")
        api_urls = [
            f"{BASE_URL}/timetable/api/students/{inst_id}/groups/",
            f"{BASE_URL}/timetable/api/groups/?faculty={inst_id}",
            f"{BASE_URL}/api/timetable/groups/?faculty_id={inst_id}"
        ]
        
        for api_url in api_urls:
            try:
                async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS, timeout=10.0) as client:
                    response = await client.get(api_url)
                    if response.status_code == 200:
                        try:
                            data = response.json()
                            if isinstance(data, list):
                                for item in data:
                                    if isinstance(item, dict):
                                        group_name = item.get('name') or item.get('title') or str(item)
                                    else:
                                        group_name = str(item)
                                    if group_name and group_name not in groups:
                                        groups.append(group_name)
                            elif isinstance(data, dict):
                                for key, value in data.items():
                                    if isinstance(value, str) and value not in groups:
                                        groups.append(value)
                                    elif isinstance(value, list):
                                        for item in value:
                                            if str(item) not in groups:
                                                groups.append(str(item))
                            if groups:
                                break
                        except:
                            continue
            except:
                continue
    
    # Способ 6: Пробуем прямые ссылки на известные группы
    if not groups:
        logger.info("Trying method 6: common group patterns")
        common_groups = [
            "9.501-1", "9.501-2", "9.502-1", "9.502-2",
            "4.101-1", "4.101-2", "4.102-1", "4.102-2",
            "1.201-1", "1.201-2", "1.202-1", "1.202-2",
            "5.301-1", "5.301-2", "5.302-1", "5.302-2",
            "8.401-1", "8.401-2", "8.402-1", "8.402-2"
        ]
        
        for group in common_groups:
            test_url = f"{BASE_URL}/timetable/?group={group}"
            try:
                async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS, timeout=5.0) as client:
                    response = await client.head(test_url)
                    if response.status_code == 200:
                        groups.append(group)
            except:
                continue
        
        if groups:
            logger.info(f"Found {len(groups)} groups via direct links")
    
    # Очистка и сортировка результатов
    if groups:
        clean_groups = []
        for g in groups:
            g = g.strip()
            # Пропускаем слишком длинные или короткие строки
            if 2 < len(g) < 30:
                # Пропускаем строки, которые явно не являются названиями групп
                if not g.startswith(('http', 'www', 'javascript', 'mailto')):
                    clean_groups.append(g)
        
        groups = sorted(set(clean_groups))
        cache.groups[inst_id] = groups
        cache.update(cache_key)
        logger.info(f"Successfully found {len(groups)} groups for institute {inst_id}")
        if groups:
            logger.info(f"Sample groups: {groups[:5]}")
    else:
        logger.warning(f"No groups found for institute {inst_id} after all methods")
        cache.groups[inst_id] = []
        cache.update(cache_key)
    
    return cache.groups.get(inst_id, [])

async def get_schedule(query):
    """Получение расписания"""
    logger.info(f"Getting schedule for: {query}")
    url = f"{BASE_URL}/timetable/?group={query}"
    html = await fetch_with_retry(url)
    
    if not html:
        return "❌ Сервер АлтГУ временно недоступен. Попробуйте позже."
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Ищем расписание в разных форматах
    schedule_parts = []
    
    # Поиск по классам
    for class_name in ['day', 'timetable', 'schedule', 'raspisanie', 'pair', 'lesson']:
        elements = soup.find_all(['div', 'table', 'tr', 'li'], class_=re.compile(class_name, re.I))
        for element in elements[:14]:  # Максимум 14 элементов (2 недели)
            text = element.get_text(separator='\n', strip=True)
            if text and len(text) > 15 and query.lower() in text.lower():
                schedule_parts.append(text[:500])
            elif text and len(text) > 15 and len(schedule_parts) < 14:
                # Добавляем даже если query не найден, но текст похож на расписание
                if re.search(r'\d{1,2}[:.]\d{2}', text) or 'пара' in text.lower():
                    schedule_parts.append(text[:500])
    
    # Если нашли структурированное расписание
    if schedule_parts:
        result = f"📅 <b>Расписание для:</b> <code>{query}</code>\n\n"
        for i, part in enumerate(schedule_parts[:14], 1):
            result += f"<b>Пара {i}:</b>\n{part}\n{'─' * 30}\n"
        return result
    
    # Поиск по всему тексту страницы
    all_text = soup.get_text(separator='\n', strip=True)
    lines = all_text.split('\n')
    
    # Ищем строки, содержащие запрос
    relevant_lines = []
    for line in lines:
        line = line.strip()
        if line and query.lower() in line.lower():
            relevant_lines.append(line)
    
    if relevant_lines:
        result = f"📅 <b>Расписание для:</b> <code>{query}</code>\n\n"
        result += '\n'.join(relevant_lines[:20])
        return result
    
    # Если ничего не нашли
    return (
        f"📅 <b>Расписание для:</b> <code>{query}</code>\n\n"
        f"❌ Расписание не найдено на сайте АлтГУ.\n\n"
        f"🔍 <i>Возможные причины:</i>\n"
        f"• Неправильный номер группы\n"
        f"• Расписание ещё не опубликовано\n"
        f"• Изменился формат номера группы\n\n"
        f"💡 <i>Проверьте номер группы в личном кабинете АлтГУ</i>"
    )

# Обработчики команд
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    logger.info(f"User {message.from_user.id} started bot")
    await message.answer(
        "👋 <b>Привет!</b> Я бот расписания АлтГУ.\n\n"
        "Я помогу узнать расписание занятий.\n"
        "Выберите действие в меню ниже:",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Обработчик команды /help"""
    await message.answer(
        "<b>📚 Как пользоваться ботом:</b>\n\n"
        "<b>Способ 1 (меню):</b>\n"
        "1️⃣ Нажмите <b>📅 Расписание</b>\n"
        "2️⃣ Выберите <b>🎓 Студенты</b>\n"
        "3️⃣ Выберите институт и группу\n\n"
        "<b>Способ 2 (команда):</b>\n"
        "Отправьте команду:\n"
        "<code>/schedule НомерГруппы</code>\n\n"
        "<b>Примеры:</b>\n"
        "• /schedule 9.501-1\n"
        "• /schedule 4.101-2\n"
        "• /schedule Иванов И.И.\n"
        "• /schedule 327М\n\n"
        "<b>Другие команды:</b>\n"
        "/start - перезапуск бота\n"
        "/help - эта справка",
        parse_mode="HTML"
    )

@dp.message(Command("schedule"))
async def cmd_schedule(message: types.Message):
    """Обработчик команды /schedule"""
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "❌ Укажите группу, преподавателя или аудиторию\n\n"
            "<b>Примеры:</b>\n"
            "<code>/schedule 9.501-1</code> - группа\n"
            "<code>/schedule Иванов И.И.</code> - преподаватель\n"
            "<code>/schedule 327М</code> - аудитория",
            parse_mode="HTML"
        )
        return
    
    query = parts[1].strip()
    logger.info(f"Schedule request for: {query}")
    
    msg = await message.answer(f"⏳ Ищу расписание для <b>{query}</b>...", parse_mode="HTML")
    
    schedule = await get_schedule(query)
    
    try:
        await msg.edit_text(schedule, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error editing message: {e}")
        await msg.delete()
        # Разбиваем длинные сообщения
        if len(schedule) > 4000:
            for i in range(0, len(schedule), 4000):
                await message.answer(schedule[i:i+4000], parse_mode="HTML")
        else:
            await message.answer(schedule, parse_mode="HTML")

# Обработчики кнопок главного меню
@dp.message(F.text == "📅 Расписание")
async def btn_schedule(message: types.Message):
    """Кнопка 'Расписание'"""
    logger.info(f"User {message.from_user.id} pressed 'Расписание'")
    await message.answer(
        "<b>📅 Расписание занятий АлтГУ</b>\n\n"
        "Выберите категорию:",
        parse_mode="HTML",
        reply_markup=get_schedule_menu()
    )

@dp.message(F.text == "🌐 Сайт АлтГУ")
async def btn_website(message: types.Message):
    """Кнопка 'Сайт АлтГУ'"""
    logger.info(f"User {message.from_user.id} pressed 'Сайт АлтГУ'")
    await message.answer(
        f"🔗 <b>Официальный сайт расписания АлтГУ:</b>\n\n"
        f"{TIMETABLE_URL}\n\n"
        f"<i>На сайте можно посмотреть расписание всех групп, преподавателей и аудиторий</i>",
        parse_mode="HTML"
    )

@dp.message(F.text == "❓ Помощь")
async def btn_help(message: types.Message):
    """Кнопка 'Помощь'"""
    logger.info(f"User {message.from_user.id} pressed 'Помощь'")
    await cmd_help(message)

# Обработчики callback-запросов (inline кнопки)
@dp.callback_query(F.data == "type_students")
async def cb_students(callback: CallbackQuery):
    """Показать список институтов для студентов"""
    await callback.answer()
    logger.info(f"User {callback.from_user.id} selected students")
    
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
        InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")
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
    logger.info(f"User {callback.from_user.id} selected teachers")
    
    await callback.message.edit_text(
        "👨‍🏫 <b>Расписание преподавателя</b>\n\n"
        "Отправьте команду с фамилией и инициалами:\n"
        "<code>/schedule Фамилия И.О.</code>\n\n"
        "<b>Примеры:</b>\n"
        "• <code>/schedule Иванов И.И.</code>\n"
        "• <code>/schedule Петрова А.С.</code>\n\n"
        "<i>Можно указать только фамилию:</i>\n"
        "• <code>/schedule Иванов</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")]
        ])
    )

@dp.callback_query(F.data == "type_rooms")
async def cb_rooms(callback: CallbackQuery):
    """Инструкция по поиску аудиторий"""
    await callback.answer()
    logger.info(f"User {callback.from_user.id} selected rooms")
    
    await callback.message.edit_text(
        "🏛 <b>Расписание аудитории</b>\n\n"
        "Отправьте команду с номером аудитории:\n"
        "<code>/schedule НомерАудитории</code>\n\n"
        "<b>Примеры:</b>\n"
        "• <code>/schedule 327М</code>\n"
        "• <code>/schedule 215</code>\n"
        "• <code>/schedule 401Л</code>\n\n"
        "<i>Номер аудитории можно найти в расписании группы</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")]
        ])
    )

@dp.callback_query(F.data.startswith("inst_"))
async def cb_institute(callback: CallbackQuery):
    """Показать группы выбранного института"""
    await callback.answer()
    inst_id = callback.data.replace("inst_", "")
    logger.info(f"User {callback.from_user.id} selected institute {inst_id}")
    
    await callback.message.edit_text("⏳ Загружаю список групп...")
    
    groups = await fetch_groups(inst_id)
    
    if not groups:
        # Если группы не найдены, предлагаем ручной ввод
        await callback.message.edit_text(
            "❌ Автоматический список групп временно недоступен.\n\n"
            "🔍 <b>Вы можете найти расписание вручную:</b>\n\n"
            "1️⃣ Отправьте команду:\n"
            "<code>/schedule НомерГруппы</code>\n\n"
            "2️⃣ Или нажмите кнопку ниже и введите группу:\n\n"
            "<b>Примеры номеров групп:</b>\n"
            "• 9.501-1\n"
            "• 4.101-2\n"
            "• 1.201-1\n\n"
            "<i>Точный номер группы можно узнать:\n"
            "- В личном кабинете АлтГУ\n"
            "- В зачетной книжке\n"
            "- У старосты группы</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔍 Ввести группу вручную", switch_inline_query_current_chat="/schedule ")],
                [InlineKeyboardButton(text="🔙 К институтам", callback_data="type_students")],
                [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]
            ])
        )
        return
    
    # Создаем клавиатуру с группами (по 2 в ряд)
    keyboard = []
    for i in range(0, len(groups), 2):
        row = []
        for group in groups[i:i+2]:
            row.append(InlineKeyboardButton(
                text=group[:25],
                callback_data=f"group_{group}"
            ))
        keyboard.append(row)
    
    # Навигационные кнопки
    keyboard.append([
        InlineKeyboardButton(text="🔙 К институтам", callback_data="type_students"),
        InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_menu")
    ])
    
    await callback.message.edit_text(
        f"👥 <b>Выберите группу:</b>\n"
        f"📊 Найдено групп: {len(groups)}\n\n"
        f"<i>Если вашей группы нет в списке, используйте:</i>\n"
        f"<code>/schedule НомерГруппы</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@dp.callback_query(F.data.startswith("group_"))
async def cb_group(callback: CallbackQuery):
    """Показать расписание для выбранной группы"""
    await callback.answer()
    group = callback.data.replace("group_", "")
    logger.info(f"User {callback.from_user.id} selected group {group}")
    
    await callback.message.edit_text(
        f"⏳ Загружаю расписание группы <b>{group}</b>...",
        parse_mode="HTML"
    )
    
    schedule = await get_schedule(group)
    
    try:
        await callback.message.edit_text(schedule, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error sending schedule: {e}")
        await callback.message.delete()
        # Разбиваем длинные сообщения
        if len(schedule) > 4000:
            for i in range(0, len(schedule), 4000):
                await callback.message.answer(schedule[i:i+4000], parse_mode="HTML")
        else:
            await callback.message.answer(schedule, parse_mode="HTML")

@dp.callback_query(F.data == "back_to_menu")
async def cb_back_to_menu(callback: CallbackQuery):
    """Возврат в главное меню"""
    await callback.answer()
    logger.info(f"User {callback.from_user.id} back to menu")
    
    await callback.message.edit_text(
        "<b>📅 Расписание занятий АлтГУ</b>\n\n"
        "Выберите категорию:",
        parse_mode="HTML",
        reply_markup=get_schedule_menu()
    )

# Запасной обработчик для неизвестных сообщений
@dp.message()
async def handle_unknown(message: types.Message):
    """Обработчик для неизвестных сообщений"""
    logger.info(f"Unknown message from {message.from_user.id}: {message.text}")
    
    # Проверяем, может это номер группы?
    if re.match(r'^[\d]', message.text):
        # Возможно пользователь ввел номер группы без команды
        await message.answer(
            f"🔍 Возможно, вы хотели найти расписание?\n\n"
            f"Используйте команду:\n"
            f"<code>/schedule {message.text}</code>\n\n"
            f"Или нажмите на кнопку меню ниже.",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer(
            "🤔 Я не понял ваш запрос.\n\n"
            "Используйте кнопки меню или команды:\n"
            "/start - главное меню\n"
            "/schedule - поиск расписания\n"
            "/help - справка",
            reply_markup=get_main_keyboard()
        )

# Веб-сервер для Amvera
async def handle_health(request):
    """Эндпоинт для проверки работоспособности"""
    return web.Response(text="Bot is running")

async def handle_root(request):
    """Корневой эндпоинт"""
    return web.Response(text="AltSU Schedule Bot is active!")

async def start_web_server():
    """Запуск веб-сервера"""
    app = web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_get("/health", handle_health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    
    logger.info(f"Starting web server on port {port}")
    await site.start()

async def main():
    """Главная функция запуска бота"""
    logger.info("=" * 50)
    logger.info("Starting AltSU Schedule Bot...")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Bot token starts with: {BOT_TOKEN[:10]}...")
    
    # Запускаем веб-сервер
    await start_web_server()
    
    # Запускаем бота с повторными попытками
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            logger.info(f"Starting bot polling (attempt {attempt + 1}/{max_attempts})...")
            await dp.start_polling(bot)
            break
        except Exception as e:
            logger.error(f"Polling error (attempt {attempt + 1}): {e}")
            if attempt < max_attempts - 1:
                wait_time = (attempt + 1) * 5
                logger.info(f"Waiting {wait_time} seconds before retry...")
                await asyncio.sleep(wait_time)
            else:
                logger.error("Max retries reached. Bot stopped.")
                raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
