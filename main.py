import os
import asyncio
import logging
import re
from bs4 import BeautifulSoup
import httpx
from aiohttp import web

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton,
    CallbackQuery
)

# ---------------------------------------------------------------------------
# Настройки бота
# ---------------------------------------------------------------------------
BOT_TOKEN = "8639721738:AAEX_xUw7rtNLCVCFys2ng9zAWFjgO74NjU"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
}

# ---------------------------------------------------------------------------
# Статический список институтов АлтГУ (Гарантия работы без ошибок)
# ---------------------------------------------------------------------------
INSTITUTES = [
    ("Институт географии (ИНГЕО)", "10714"),
    ("Институт географии заоч. отд. (ИНГ-З)", "10715"),
    ("Биологии и биотехнологии (ИББ)", "10711"),
    ("Инс.гуманитарных наук (ИГН)", "10712"),
    ("Исторический (ИИМО)", "10713"),
    ("ИХиХФТ", "10716"),
    ("ИЦТЭФ", "10717"),
    ("Колледж АГУ (СПО)", "10718"),
    ("Математики и инф.технологий (ИМИИТ)", "10719"),
    ("МИЭМИС (ЭФ)", "10720"),
    ("Юридический (ЮИ)", "10721")
]

# ---------------------------------------------------------------------------
# Клавиатуры
# ---------------------------------------------------------------------------
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📅 Выбрать расписание")],
        [KeyboardButton(text="🌐 Сайт АлтГУ"), KeyboardButton(text="❓ Помощь")]
    ],
    resize_keyboard=True
)

def get_main_schedule_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎓 Расписание занятий студентов", callback_data="type_students")],
            [InlineKeyboardButton(text="👨‍🏫 Расписание занятий преподавателей", callback_data="type_teachers")],
            [InlineKeyboardButton(text="🏛 Расписание занятий в аудиториях", callback_data="type_rooms")]
        ]
    )

def get_institutes_keyboard():
    keyboard = []
    for name, inst_id in INSTITUTES:
        keyboard.append([InlineKeyboardButton(text=name, callback_data=f"inst_{inst_id}")])
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ---------------------------------------------------------------------------
# Автоматический парсинг групп и расписания
# ---------------------------------------------------------------------------
async def fetch_groups(inst_id: str):
    """Динамический парсинг всех групп конкретного института с сайта АлтГУ"""
    url = f"https://www.asu.ru/timetable/students/{inst_id}/"
    try:
        async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS, timeout=15.0) as client:
            resp = await client.get(url)
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Ищем все элементы/ссылки с номерами групп
            group_elements = soup.find_all("a", href=re.compile(r"group="))
            groups = set()
            
            for elem in group_elements:
                text = elem.get_text(strip=True)
                if text:
                    groups.add(text)
                    
            return sorted(list(groups))
    except Exception as e:
        logging.error(f"Ошибка получения групп: {e}")
        return []

async def get_schedule(query_code: str) -> str:
    """Парсинг расписания для группы"""
    url = f"https://www.asu.ru/timetable/?group={query_code}"
    
    try:
        async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS, timeout=15.0) as client:
            response = await client.get(url)
            
            if response.status_code != 200:
                return "⚠️ Не удалось связаться с сервером АлтГУ."
            
            soup = BeautifulSoup(response.text, "html.parser")
            days = soup.find_all("div", class_="day") or soup.find_all("div", class_="timetable-day")
            
            if not days:
                return (
                    f"📅 <b>Запрос: {query_code}</b>\n\n"
                    "ℹ️ На данный момент расписание отсутствует на сайте АлтГУ.\n"
                    "<i>(Возможно, сейчас каникулы, выходные дни или расписание еще не загружено).</i>"
                )

            result = [f"📋 <b>Расписание ({query_code}):</b>\n"]
            has_lessons = False
            
            for day in days[:4]:
                date_header = day.find(["h3", "h4", "div"], class_=["date", "day-header"])
                header_text = date_header.get_text(strip=True) if date_header else "День"
                result.append(f"📅 <b>{header_text}</b>")
                
                items = day.find_all(["li", "tr", "div"], class_=["lesson", "pair"])
                if items:
                    has_lessons = True
                    for item in items:
                        result.append(f"▫️ {item.get_text(separator=' ', strip=True)}")
                else:
                    result.append("▫️ Нет пар")
                result.append("")
                
            if not has_lessons:
                return (
                    f"📅 <b>Запрос: {query_code}</b>\n\n"
                    "ℹ️ На ближайшие дни занятий не найдено (каникулы или выходные)."
                )

            return "\n".join(result)

    except Exception as e:
        logging.error(f"Ошибка при парсинге: {e}")
        return (
            f"📅 <b>Запрос: {query_code}</b>\n\n"
            "ℹ️ На данный момент расписание отсутствует на сайте АлтГУ (каникулы или переходный период)."
        )

# ---------------------------------------------------------------------------
# Хэндлеры бота
# ---------------------------------------------------------------------------
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    await message.answer(
        "👋 <b>Добро пожаловать в бот расписания АлтГУ!</b>\n\n"
        "Выберите нужный раздел из меню ниже:",
        parse_mode="HTML",
        reply_markup=main_keyboard
    )

@dp.message(F.text == "📅 Выбрать расписание")
async def choose_schedule_type(message: types.Message):
    await message.answer(
        "<b>Расписание занятий АлтГУ</b>\nВыберите категорию:",
        parse_mode="HTML",
        reply_markup=get_main_schedule_menu()
    )

@dp.message(F.text == "🌐 Сайт АлтГУ")
async def open_website(message: types.Message):
    await message.answer("Официальный сайт расписания АлтГУ:\nhttps://www.asu.ru/timetable/")

@dp.message(F.text == "❓ Помощь")
async def help_cmd(message: types.Message):
    await message.answer(
        "<b>Как пользоваться ботом:</b>\n\n"
        "1. Нажмите <b>📅 Выбрать расписание</b>.\n"
        "2. Выберите институт и вашу группу из списка.\n\n"
        "Также можно ввести команду вручную:\n<code>/schedule 3.201-1</code>",
        parse_mode="HTML"
    )

@dp.message(Command("schedule"))
async def schedule_cmd(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Укажите группу, например: <code>/schedule 3.201-1</code>", parse_mode="HTML")
        return
        
    group = args[1].strip()
    status_msg = await message.answer(f"⏳ Запрашиваю расписание для <b>{group}</b>...", parse_mode="HTML")
    schedule = await get_schedule(group)
    await status_msg.delete()
    await message.answer(schedule, parse_mode="HTML")

# ---------------------------------------------------------------------------
# Callback-обработчики
# ---------------------------------------------------------------------------
@dp.callback_query(F.data == "back_to_main_menu")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_text(
        "<b>Расписание занятий АлтГУ</b>\nВыберите категорию:",
        parse_mode="HTML",
        reply_markup=get_main_schedule_menu()
    )
    await callback.answer()

@dp.callback_query(F.data == "type_students")
async def type_students_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "<b>Шаг 1. Выбор учебного подразделения / института:</b>",
        parse_mode="HTML",
        reply_markup=get_institutes_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("inst_"))
async def institute_selected_handler(callback: CallbackQuery):
    inst_id = callback.data.replace("inst_", "")
    await callback.message.edit_text("⏳ Загружаю список групп с сайта АлтГУ...")
    
    groups = await fetch_groups(inst_id)
    
    if not groups:
        # Резервный список для ИНГЕО, если сайт временно недоступен
        groups = ["3.201-1", "3.201-2", "9.101-1", "9.101-2", "9.401-1", "9.401-2", "9.103", "9.104"]

    # Формируем кнопки групп по 2 в ряд
    keyboard = []
    row = []
    for group in groups:
        row.append(InlineKeyboardButton(text=group, callback_data=f"select_group_{group}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад к институтам", callback_data="type_students")])
    
    await callback.message.edit_text(
        "<b>Шаг 2. Выбор группы:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("select_group_"))
async def group_final_selected(callback: CallbackQuery):
    group_name = callback.data.replace("select_group_", "")
    await callback.message.edit_text(f"⏳ Запрашиваю расписание для группы <b>{group_name}</b>...", parse_mode="HTML")
    schedule = await get_schedule(group_name)
    await callback.message.edit_text(schedule, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.in_({"type_teachers", "type_rooms"}))
async def other_types_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "ℹ️ Для быстрого поиска отправьте номер группы или фамилию командой в чат:\n<code>/schedule 3.201-1</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_main_menu")]])
    )
    await callback.answer()

# ---------------------------------------------------------------------------
# Сервер для Render
# ---------------------------------------------------------------------------
async def handle_ping(request):
    return web.Response(text="ASU Schedule Bot is active!")

async def main():
    logging.basicConfig(level=logging.INFO)
    
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
