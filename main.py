import asyncio
import logging
import os
import re
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

# Токен твоего бота
BOT_TOKEN = "8639721738:AAEX_xUw7rtNLCVCFys2ng9zAWFjgO74NjU"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
        " like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

USER_GROUPS_CACHE = {}

# Запасной базовый список институтов АлтГУ (если сайт временно недоступен или блокирует по IP)
FALLBACK_INSTITUTES = [
    {"id": "3", "name": "Институт географии (ИНГЕО)"},
    {"id": "1", "name": "Биологии и биотехнологии (ИББ)"},
    {"id": "2", "name": "Гуманитарных наук (ИГН)"},
    {"id": "4", "name": "Исторический (ИИМО)"},
    {"id": "5", "name": "ИХиХФТ"},
    {"id": "6", "name": "ИЦТЭФ"},
    {"id": "7", "name": "Колледж АГУ (СПО)"},
    {"id": "8", "name": "Математики и инф.технологий (ИМИИТ)"},
    {"id": "9", "name": "МИЭМИС (ЭФ)"},
    {"id": "10", "name": "Юридический институт (ЮИ)"},
]

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📅 Выбрать расписание")],
        [KeyboardButton(text="🌐 Сайт АлтГУ"), KeyboardButton(text="❓ Помощь")],
    ],
    resize_keyboard=True,
)


def get_main_schedule_menu():
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="🎓 Расписание занятий студентов",
                  callback_data="type_students",
              )
          ],
          [
              InlineKeyboardButton(
                  text="👨‍🏫 Расписание занятий преподавателей",
                  callback_data="type_teachers",
              )
          ],
          [
              InlineKeyboardButton(
                  text="🏛 Расписание занятий в аудиториях",
                  callback_data="type_rooms",
              )
          ],
      ]
  )


async def fetch_institutes():
  """Парсит институты с сайта АлтГУ с расширенным логированием и фоллбэком"""
  url = "https://www.asu.ru/timetable/"
  try:
    async with httpx.AsyncClient(
        follow_redirects=True, headers=HEADERS, timeout=10.0
    ) as client:
      response = await client.get(url)

      if response.status_code != 200:
        logging.error(
            f"❌ Ошибка доступа к главной странице {url}. Статус код:"
            f" {response.status_code}"
        )
        return FALLBACK_INSTITUTES

      soup = BeautifulSoup(response.text, "html.parser")
      institutes = []

      links = soup.find_all("a", href=re.compile(r"/timetable/students/"))
      for link in links:
        name = link.get_text(strip=True)
        href = link.get("href", "")
        match = re.search(r"/students/(\d+)/", href)
        if match and name:
          inst_id = match.group(1)
          if not any(i["id"] == inst_id for i in institutes):
            institutes.append({"id": inst_id, "name": name})

      if institutes:
        return institutes
      else:
        logging.warning(
            f"⚠️ Институты не найдены в HTML. Возможно, изменилась верстка:"
            f" {url}"
        )
        return FALLBACK_INSTITUTES

  except Exception as e:
    logging.error(f"❌ Ошибка получения списка институтов: {e}")

  return FALLBACK_INSTITUTES


async def fetch_groups_by_institute(inst_id: str):
  """Парсит группы конкретного института с расширенным логированием"""
  url = f"https://www.asu.ru/timetable/students/{inst_id}/"
  try:
    async with httpx.AsyncClient(
        follow_redirects=True, headers=HEADERS, timeout=10.0
    ) as client:
      response = await client.get(url)

      if response.status_code != 200:
        logging.error(
            f"❌ Ошибка доступа к {url}. Статус код: {response.status_code}"
        )
        return []

      soup = BeautifulSoup(response.text, "html.parser")
      groups = []

      group_links = soup.find_all("a", href=re.compile(r"\?group="))
      for link in group_links:
        g_name = link.get_text(strip=True)
        if g_name and g_name not in groups:
          groups.append(g_name)

      if groups:
        return sorted(groups)
      else:
        logging.warning(
            f"⚠️ Группы не найдены в HTML. Возможно, изменилась верстка сайта:"
            f" {url}"
        )

  except Exception as e:
    logging.error(f"❌ Ошибка получения групп: {e}")

  return []


def build_institutes_keyboard(institutes):
  keyboard = []
  for inst in institutes:
    short_name = inst["name"][:35]
    keyboard.append([
        InlineKeyboardButton(
            text=short_name, callback_data=f"inst_{inst['id']}"
        )
    ])

  keyboard.append([
      InlineKeyboardButton(
          text="⬅️ Назад в меню", callback_data="back_to_main_menu"
      )
  ])
  return InlineKeyboardMarkup(inline_keyboard=keyboard)


def build_groups_keyboard(groups, page: int = 0):
  items_per_page = 14
  total_pages = max(1, (len(groups) + items_per_page - 1) // items_per_page)

  start_idx = page * items_per_page
  end_idx = start_idx + items_per_page
  current_groups = groups[start_idx:end_idx]

  keyboard = []
  row = []
  for g in current_groups:
    row.append(
        InlineKeyboardButton(text=g, callback_data=f"select_group_{g}")
    )
    if len(row) == 2:
      keyboard.append(row)
      row = []
  if row:
    keyboard.append(row)

  nav_row = []
  if page > 0:
    nav_row.append(
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"page_{page - 1}")
    )
  nav_row.append(
      InlineKeyboardButton(
          text=f"📄 {page + 1}/{total_pages}", callback_data="ignore"
      )
  )
  if page < total_pages - 1:
    nav_row.append(
        InlineKeyboardButton(text="Вперед ➡️", callback_data=f"page_{page + 1}")
    )

  keyboard.append(nav_row)
  keyboard.append([
      InlineKeyboardButton(
          text="⬅️ К выбору института", callback_data="type_students"
      )
  ])

  return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def get_schedule(query_code: str) -> str:
  """Универсальная функция поиска расписания (для групп, аудиторий и т.д.)

  на любой доступный срок с сайта АлтГУ.
  """
  url = f"https://www.asu.ru/timetable/?group={query_code}"
  try:
    async with httpx.AsyncClient(
        follow_redirects=True, headers=HEADERS, timeout=15.0
    ) as client:
      response = await client.get(url)
      if response.status_code != 200:
        return (
            "⚠️ Не удалось связаться с сервером АлтГУ. (Возможно, сайт блокирует"
            " запросы)"
        )

      soup = BeautifulSoup(response.text, "html.parser")

      # Сначала пробуем стандартные дни, если они есть
      days = soup.find_all("div", class_="day") or soup.find_all(
          "div", class_="timetable-day"
      )

      if days:
        result = [f"📋 <b>Расписание ({query_code}):</b>\n"]
        has_lessons = False
        for day in days[:7]:  шире охват дней
          date_header = day.find(["h3", "h4", "div"], class_=["date", "day-header"])
          header_text = (
              date_header.get_text(strip=True) if date_header else "День"
          )
          result.append(f"📅 <b>{header_text}</b>")

          items = day.find_all(["li", "tr", "div"], class_=["lesson", "pair"])
          if items:
            has_lessons = True
            for item in items:
              result.append(f"▫️ {item.get_text(separator=' ', strip=True)}")
          else:
            result.append("▫️ Нет пар")
          result.append("")

        if has_lessons:
          return "\n".join(result)

      # УНИВЕРСАЛЬНЫЙ РЕЖИМ (если верстка изменилась или запрашивается аудитория/преподаватель)
      results = []
      query_lower = query.strip().lower()

      # Ищем по табличным строкам и блокам расписания
      for element in soup.find_all(["tr", "div", "p", "li"]):
        text = element.get_text(separator=" ", strip=True)
        if query_lower in text.lower() and len(text) < 300:
          if text not in results:
            results.append(text)

      if results:
        unique_results = list(dict.fromkeys(results))
        response_text = (
            f"📅 <b>Результаты для:</b> <code>{query}</code>\n\n"
            + "\n".join([f"▫️ {item}" for item in unique_results[:15]])
        )
        return response_text

      return (
          f"📅 <b>Запрос: {query_code}</b>\n\nℹ️ На данный момент расписание"
          " отсутствует на сайте АлтГУ или указано в другом формате."
      )

  except Exception as e:
    logging.error(f"Ошибка парсинга расписания: {e}")
    return f"📅 <b>Запрос: {query_code}</b>\n\nℹ️ Ошибка подключения к серверу АлтГУ."


# ---------------------------------------------------------------------------
# Хэндлеры сообщений
# ---------------------------------------------------------------------------
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
  await message.answer(
      "👋 <b>Добро пожаловать в бот расписания АлтГУ!</b>\n\nВыберите нужный раздел"
      " из меню ниже:",
      parse_mode="HTML",
      reply_markup=main_keyboard,
  )


@dp.message(F.text == "📅 Выбрать расписание")
async def choose_schedule_type(message: types.Message):
  await message.answer(
      "<b>Расписание занятий АлтГУ</b>\nВыберите категорию:",
      parse_mode="HTML",
      reply_markup=get_main_schedule_menu(),
  )


@dp.message(F.text == "🌐 Сайт АлтГУ")
async def open_website(message: types.Message):
  await message.answer(
      "Официальный сайт расписания АлтГУ:\nhttps://www.asu.ru/timetable/"
  )


@dp.message(F.text == "❓ Помощь")
async def help_cmd(message: types.Message):
  await message.answer(
      "<b>Как пользоваться ботом:</b>\n\n1. Нажмите <b>📅 Выбрать"
      " расписание</b>.\n2. Выберите ваш институт и группу.\n\nИли введите"
      " команду напрямую:\n<code>/schedule 9.501-1</code>\n<code>/schedule 327"
      " М</code>",
      parse_mode="HTML",
  )


@dp.message(Command("schedule"))
async def schedule_cmd(message: types.Message):
  args = message.text.split(maxsplit=1)
  if len(args) < 2:
    await message.answer(
        "Укажите группу или аудиторию, например: <code>/schedule"
        " 9.501-1</code> или <code>/schedule 327 М</code>",
        parse_mode="HTML",
    )
    return
  query = args[1].strip()
  status_msg = await message.answer(
      f"⏳ Запрашиваю расписание для <b>{query}</b>...", parse_mode="HTML"
  )
  schedule = await get_schedule(query)
  await status_msg.delete()
  await message.answer(schedule, parse_mode="HTML")


# ---------------------------------------------------------------------------
# Callback-события
# ---------------------------------------------------------------------------
@dp.callback_query(F.data == "back_to_main_menu")
async def back_to_main(callback: CallbackQuery):
  await callback.answer()
  await callback.message.edit_text(
      "<b>Расписание занятий АлтГУ</b>\nВыберите категорию:",
      parse_mode="HTML",
      reply_markup=get_main_schedule_menu(),
  )


@dp.callback_query(F.data == "type_students")
async def type_students_handler(callback: CallbackQuery):
  await callback.answer()
  await callback.message.edit_text("⏳ Загружаю список институтов...")
  institutes = await fetch_institutes()
  await callback.message.edit_text(
      "<b>Шаг 1. Выбор учебного подразделения / института:</b>",
      parse_mode="HTML",
      reply_markup=build_institutes_keyboard(institutes),
  )


@dp.callback_query(F.data == "type_teachers")
async def type_teachers_handler(callback: CallbackQuery):
  await callback.answer()
  await callback.message.edit_text(
      "👨‍🏫 <b>Поиск расписания преподавателя</b>\n\nДля просмотра расписания"
      " отправьте команду со структурой:\n<code>/schedule Фамилия"
      " И.О.</code>",
      parse_mode="HTML",
      reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
          InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main_menu")
      ]]),
  )


@dp.callback_query(F.data == "type_rooms")
async def type_rooms_handler(callback: CallbackQuery):
  await callback.answer()
  await callback.message.edit_text(
      "🏛 <b>Поиск расписания в аудитории</b>\n\nДля просмотра расписания"
      " отправьте номер аудитории командой:\n<code>/schedule 327 М</code>",
      parse_mode="HTML",
      reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
          InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main_menu")
      ]]),
  )


@dp.callback_query(F.data.startswith("inst_"))
async def inst_selected_handler(callback: CallbackQuery):
  await callback.answer()
  inst_id = callback.data.split("_")[1]
  await callback.message.edit_text("⏳ Загружаю список групп института...")
  groups = await fetch_groups_by_institute(inst_id)

  if not groups:
    await callback.message.edit_text(
        "ℹ️ Автоматический список групп недоступен.\nОтправьте номер вашей"
        " группы командой:\n<code>/schedule 9.501-1</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="⬅️ Назад к институтам", callback_data="type_students"
            )
        ]]),
    )
    return

  USER_GROUPS_CACHE[callback.from_user.id] = groups
  await callback.message.edit_text(
      "<b>Шаг 2. Выбор группы:</b>",
      parse_mode="HTML",
      reply_markup=build_groups_keyboard(groups, page=0),
  )


@dp.callback_query(F.data.startswith("page_"))
async def page_change_handler(callback: CallbackQuery):
  page = int(callback.data.split("_")[1])
  groups = USER_GROUPS_CACHE.get(callback.from_user.id, [])
  if not groups:
    await callback.answer(
        "Сессия истекла. Попробуйте выбрать институт заново.", show_alert=True
    )
    return
  await callback.answer()
  await callback.message.edit_text(
      "<b>Шаг 2. Выбор группы:</b>",
      parse_mode="HTML",
      reply_markup=build_groups_keyboard(groups, page=page),
  )


@dp.callback_query(F.data.startswith("select_group_"))
async def group_final_selected(callback: CallbackQuery):
  await callback.answer()
  group_name = callback.data.replace("select_group_", "")
  await callback.message.edit_text(
      f"⏳ Запрашиваю расписание для группы <b>{group_name}</b>...",
      parse_mode="HTML",
  )
  schedule = await get_schedule(group_name)
  await callback.message.edit_text(schedule, parse_mode="HTML")


@dp.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery):
  await callback.answer()


# ---------------------------------------------------------------------------
# Веб-сервер для поддержания работы на Render
# ---------------------------------------------------------------------------
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
