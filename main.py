import os
import asyncio
import logging
from bs4 import BeautifulSoup
import httpx
from aiohttp import web

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton
)

# ---------------------------------------------------------------------------
# Настройки бота
# ---------------------------------------------------------------------------
# Замените на ваш токен от @BotFather (токен обязательно внутри кавычек!)
BOT_TOKEN = "8639721738:AAEX_xUw7rtNLCVCFys2ng9zAWFjgO74NjU"

# Группа по умолчанию для быстрой кнопки на клавиатуре
DEFAULT_GROUP = "3.201-1"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
}

# ---------------------------------------------------------------------------
# Клавиатуры (Кнопки)
# ---------------------------------------------------------------------------

# Главная клавиатура внизу экрана (Reply Keyboard)
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text=f"📅 Расписание {DEFAULT_GROUP}"),
            KeyboardButton(text="🔍 Другая группа")
        ],
        [
            KeyboardButton(text="🌐 Сайт АлтГУ"),
            KeyboardButton(text="❓ Помощь")
        ]
    ],
    resize_keyboard=True
)

# Инлайн-кнопки под сообщением
inline_days_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="🌐 Открыть расписание на сайте", url="https://www.asu.ru/timetable/")
        ]
    ]
)

# ---------------------------------------------------------------------------
# Парсер расписания с сайта АлтГУ
# ---------------------------------------------------------------------------
async def get_schedule(group_code: str) -> str:
    url = f"https://www.asu.ru/timetable/?group={group_code}"
    
    async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS, timeout=15.0) as client:
        try:
            response = await client.get(url)
            if response.status_code != 200:
                return "⚠️ Не удалось связаться с сервером АлтГУ. Попробуйте позже."
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Поиск блоков с днями недели
            days = soup.find_all("div", class_="day") or soup.find_all("div", class_="timetable-day")
            
            if not days:
                return (
                    f"📅 <b>Группа: {group_code}</b>\n\n"
                    "На данный момент расписание для этой группы отсутствует на сайте АлтГУ "
                    "(возможно, идут каникулы или семестр еще не начался)."
                )

            result = [f"📋 <b>Расписание для группы {group_code}:</b>\n"]
            for day in days[:4]:  # Выводим первые 4 дня
                date_header = day.find(["h3", "h4", "div"], class_=["date", "day-header"])
                header_text = date_header.get_text(strip=True) if date_header else "День"
                result.append(f"📅 <b>{header_text}</b>")
                
                items = day.find_all(["li", "tr", "div"], class_=["lesson", "pair"])
                if items:
                    for item in items:
                        result.append(f"▫️ {item.get_text(separator=' ', strip=True)}")
                else:
                    result.append("▫️ Нет пар")
                result.append("")
                
            return "\n".join(result)

        except Exception as e:
            logging.error(f"Ошибка при запросе: {e}")
            return "⚠️ Произошла ошибка при обработке расписания с сайта."

# ---------------------------------------------------------------------------
# Хэндлеры команд и нажатий кнопок
# ---------------------------------------------------------------------------

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    await message.answer(
        "👋 <b>Привет! Я бот расписания АлтГУ.</b>\n\n"
        "Воспользуйтесь кнопками меню ниже или отправьте команду с номером группы:\n"
        "<code>/schedule 3.201-1</code>",
        parse_mode="HTML",
        reply_markup=main_keyboard
    )

@dp.message(F.text == f"📅 Расписание {DEFAULT_GROUP}")
async def default_group_schedule(message: types.Message):
    status_msg = await message.answer(f"⏳ Запрашиваю расписание для группы <b>{DEFAULT_GROUP}</b>...", parse_mode="HTML")
    schedule = await get_schedule(DEFAULT_GROUP)
    await status_msg.delete()
    await message.answer(schedule, parse_mode="HTML", reply_markup=inline_days_keyboard)

@dp.message(F.text == "🔍 Другая группа")
async def ask_other_group(message: types.Message):
    await message.answer(
        "Введите команду с номером нужной группы, например:\n"
        "<code>/schedule 3.101-2</code>",
        parse_mode="HTML"
    )

@dp.message(F.text == "🌐 Сайт АлтГУ")
async def open_website(message: types.Message):
    await message.answer(
        "Официальное расписание АлтГУ доступно по ссылке:\n"
        "https://www.asu.ru/timetable/"
    )

@dp.message(F.text == "❓ Помощь")
async def help_cmd(message: types.Message):
    await message.answer(
        "<b>Как пользоваться ботом:</b>\n\n"
        "1. Нажмите на кнопку вашей группы для быстрого запроса.\n"
        "2. Для любой другой группы напишите команду <code>/schedule номер_группы</code>.\n"
        "3. Бот работает круглосуточно в авто-режиме.",
        parse_mode="HTML"
    )

@dp.message(Command("schedule"))
async def schedule_cmd(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Пожалуйста, укажите номер группы после команды. Пример:\n"
            "<code>/schedule 3.201-1</code>", 
            parse_mode="HTML"
        )
        return
        
    group = args[1].strip()
    status_msg = await message.answer(f"⏳ Запрашиваю расписание для группы <b>{group}</b>...", parse_mode="HTML")
    schedule = await get_schedule(group)
    await status_msg.delete()
    await message.answer(schedule, parse_mode="HTML", reply_markup=inline_days_keyboard)

# ---------------------------------------------------------------------------
# Микро-веб-сервер для Render (борьба с Timed Out)
# ---------------------------------------------------------------------------
async def handle_ping(request):
    return web.Response(text="ASU Schedule Bot is active and running!")

# ---------------------------------------------------------------------------
# Запуск приложения
# ---------------------------------------------------------------------------
async def main():
    logging.basicConfig(level=logging.INFO)
    
    # 1. Запуск микро-веб-сервера для Render
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Веб-сервер успешно запущен на порту {port}")

    # 2. Запуск поллинга Telegram-бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
