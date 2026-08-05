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

BOT_TOKEN = "8639721738:AAEX_xUw7rtNLCVCFys2ng9zAWFjgO74NjU"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

USER_GROUPS_CACHE = {}

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

async def fetch_institutes():
    url = "https://www.asu.ru/timetable/"
    try:
        async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS, timeout=15.0) as client:
            response = await client.get(url)
            if response.status_code != 200:
                return []
            
            soup = BeautifulSoup(response.text, "html.parser")
            institutes = []
            
            inst_links = soup.find_all("a", href=re.compile(r"/timetable/students/\d+/"))
            for link in inst_links:
                name = link.get_text(strip=True)
                href = link.get("href")
                match = re.search(r"/timetable/students/(\d+)/", href)
                if match and name:
                    inst_id = match.group(1)
                    if not any(i['id'] == inst_id for i in institutes):
                        institutes.append({"id": inst_id, "name": name})
            
            return institutes
    except Exception as e:
        logging.error(f"Ошибка при получении институтов: {e}")
        return []

async def fetch_groups_by_institute(inst_id: str):
    url = f"https://www.asu.ru/timetable/students/{inst_id}/"
    try:
        async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS, timeout=15.0) as client:
            response = await client.get(url)
            if response.status_code != 200:
                return []
            
            soup = BeautifulSoup(response.text, "html.parser")
            groups = []
            
            group_links = soup.find_all("a", href=re.compile(r"\?group="))
            for link in group_links:
                g_name = link.get_text(strip=True)
                if g_name and g_name not in groups:
                    groups.append(g_name)
                    
            return sorted(groups)
    except Exception as e:
        logging.error(f"Ошибка при получении групп: {e}")
        return []

def build_institutes_keyboard(institutes):
    keyboard = []
    for inst in institutes:
        short_name = inst['name'][:35]
        keyboard.append([InlineKeyboardButton(text=short_name, callback_data=f"inst_{inst['id']}")])
    
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def build_groups_keyboard(groups, page: int = 0):
    items_per_page = 14
    total_pages = (len(groups) + items_per_page - 1) // items_per_page
    
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    current_groups = groups[start_idx:end_idx]
    
    keyboard = []
    row = []
    for g in current_groups:
        row.append(InlineKeyboardButton(text=g, callback_data=f"select_group_{g}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"page_{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {page + 1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"page_{page + 1}"))
    
    keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton(text="⬅️ К выбору института", callback_data="type_students")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

async def get_schedule(query_code: str) -> str:
    url = f"https://www.asu.ru/timetable/?group={query_code}"
    try:
        async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS, timeout=15.0) as client:
            response = await client.get(url)
            if response.status_code != 200:
                return "⚠️ Не удалось связаться с сервером АлтГУ."
            
            soup = BeautifulSoup(response.text, "html.parser")
            days = soup.find_all("div", class_="day") or soup.find_all("div", class_="timetable-day")
            
            if not days:
                return f"📅 <b>Запрос: {query_code}</b>\n\nℹ️ На данный момент расписание отсутствует на сайте АлтГУ."

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
                return f"📅 <b>Запрос: {query_code}</b>\n\nℹ️ На ближайшие дни занятий не найдено."

            return "\n".join(result)

    except Exception as e:
        logging.error(f"Ошибка парсинга: {e}")
        return f"📅 <b>Запрос: {query_code}</b>\n\nℹ️ Ошибка подключения к серверу АлтГУ."

# Хэндлеры
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    await message.answer("👋 <b>Добро пожаловать в бот расписания АлтГУ!</b>\n\nВыберите нужный раздел из меню ниже:", parse_mode="HTML", reply_markup=main_keyboard)

@dp.message(F.text == "📅 Выбрать расписание")
async def choose_schedule_type(message: types.Message):
    await message.answer("<b>Расписание занятий АлтГУ</b>\nВыберите категорию:", parse_mode="HTML", reply_markup=get_main_schedule_menu())

@dp.message(F.text == "🌐 Сайт АлтГУ")
async def open_website(message: types.Message):
    await message.answer("Официальный сайт расписания АлтГУ:\nhttps://www.asu.ru/timetable/")

@dp.message(F.text == "❓ Помощь")
async def help_cmd(message: types.Message):
    await message.answer("<b>Как пользоваться ботом:</b>\n\n1. Нажмите <b>📅 Выбрать расписание</b>.\n2. Выберите ваш институт и группу.\n\nИли введите группу вручную:\n<code>/schedule 9.501-1</code>", parse_mode="HTML")

@dp.message(Command("schedule"))
async def schedule_cmd(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Укажите группу, например: <code>/schedule 9.501-1</code>", parse_mode="HTML")
        return
    group = args[1].strip()
    status_msg = await message.answer(f"⏳ Запрашиваю расписание для <b>{group}</b>...", parse_mode="HTML")
    schedule = await get_schedule(group)
    await status_msg.delete()
    await message.answer(schedule, parse_mode="HTML")

@dp.callback_query(F.data == "back_to_main_menu")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_text("<b>Расписание занятий АлтГУ</b>\nВыберите категорию:", parse_mode="HTML", reply_markup=get_main_schedule_menu())
    await callback.answer()

@dp.callback_query(F.data == "type_students")
async def type_students_handler(callback: CallbackQuery):
    await callback.message.edit_text("⏳ Загружаю список институтов с сайта АлтГУ...")
    institutes = await fetch_institutes()
    if not institutes:
        await callback.message.edit_text("⚠️ Не удалось загрузить список институтов. Введите номер группы вручную через /schedule.")
        await callback.answer()
        return
    await callback.message.edit_text("<b>Шаг 1. Выбор учебного подразделения / института:</b>", parse_mode="HTML", reply_markup=build_institutes_keyboard(institutes))
    await callback.answer()

@dp.callback_query(F.data.startswith("inst_"))
async def inst_selected_handler(callback: CallbackQuery):
    inst_id = callback.data.split("_")[1]
    await callback.message.edit_text("⏳ Загружаю список групп института...")
    groups = await fetch_groups_by_institute(inst_id)
    if not groups:
        await callback.message.edit_text("⚠️ Группы для данного института не найдены.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="type_students")]]))
        await callback.answer()
        return
    USER_GROUPS_CACHE[callback.from_user.id] = groups
    await callback.message.edit_text("<b>Шаг 2. Выбор группы:</b>", parse_mode="HTML", reply_markup=build_groups_keyboard(groups, page=0))
    await callback.answer()

@dp.callback_query(F.data.startswith("page_"))
async def page_change_handler(callback: CallbackQuery):
    page = int(callback.data.split("_")[1])
    groups = USER_GROUPS_CACHE.get(callback.from_user.id, [])
    if not groups:
        await callback.answer("Сессия истекла. Попробуйте выбрать институт заново.", show_alert=True)
        return
    await callback.message.edit_text("<b>Шаг 2. Выбор группы:</b>", parse_mode="HTML", reply_markup=build_groups_keyboard(groups, page=page))
    await callback.answer()

@dp.callback_query(F.data.startswith("select_group_"))
async def group_final_selected(callback: CallbackQuery):
    group_name = callback.data.replace("select_group_", "")
    await callback.message.edit_text(f"⏳ Запрашиваю расписание для группы <b>{group_name}</b>...", parse_mode="HTML")
    schedule = await get_schedule(group_name)
    await callback.message.edit_text(schedule, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery):
    await callback.answer()

# Веб-сервер для Render
async def handle_ping(request):
    return web.Response(text="ASU Schedule Bot is active!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    logging.basicConfig(level=logging.INFO)
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
