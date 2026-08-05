import asyncio
import logging
from bs4 import BeautifulSoup
import httpx
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command

# Вставьте сюда ваш токен от BotFather
BOT_TOKEN = "8639721738:AAEX_xUw7rtNLCVCFys2ng9zAWFjgO74NjU"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
}

async def get_schedule(group_code: str) -> str:
    # Базовый URL расписания АлтГУ
    url = f"https://www.asu.ru/timetable/?group={group_code}"
    
    async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS, timeout=15.0) as client:
        try:
            response = await client.get(url)
            if response.status_code != 200:
                return "⚠️ Не удалось связаться с сервером АлтГУ."
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Поиск основных элементов расписания
            days = soup.find_all("div", class_="day") or soup.find_all("div", class_="timetable-day")
            
            if not days:
                # Если блоки не найдены, извлекаем текстовые блоки со страницы
                text_content = soup.get_text(separator="\n", strip=True)
                if "Расписание" not in text_content:
                    return f"❌ Расписание для группы <b>{group_code}</b> не найдено. Проверьте правильность входа."
                return "📋 Расписание получено, но требует уточнения структуры парсинга."

            result = []
            for day in days[:4]:  # Выводим первые 4 дня
                date_header = day.find(["h3", "h4", "div"], class_=["date", "day-header"])
                header_text = date_header.get_text(strip=True) if date_header else "День"
                result.append(f"📅 <b>{header_text}</b>")
                
                items = day.find_all(["li", "tr", "div"], class_=["lesson", "pair"])
                for item in items:
                    result.append(f"▫️ {item.get_text(separator=' ', strip=True)}")
                result.append("")
                
            return "\n".join(result) if result else "Информация о парах не найдена."

        except Exception as e:
            logging.error(f"Ошибка при запросе: {e}")
            return "⚠️ Произошла ошибка при обработке запроса."

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    await message.answer(
        "👋 <b>Привет! Я бот расписания АлтГУ.</b>\n\n"
        "Чтобы узнать расписание, отправь команду с номером группы:\n"
        "<code>/schedule 3.201-1</code>",
        parse_mode="HTML"
    )

@dp.message(Command("schedule"))
async def schedule_cmd(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Пожалуйста, укажите номер группы после команды. Пример:\n<code>/schedule 3.201-1</code>", parse_mode="HTML")
        return
        
    group = args[1].strip()
    status_msg = await message.answer(f"⏳ Запрашиваю расписание для группы <b>{group}</b>...", parse_mode="HTML")
    
    schedule = await get_schedule(group)
    
    await status_msg.delete()
    await message.answer(schedule, parse_mode="HTML")

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
