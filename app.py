import os
import json
import sqlite3
import random
import base64
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from html import escape

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup,
    InlineKeyboardButton, Update
)
from fastapi import FastAPI, Request, HTTPException

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "kip-helper-secret")
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
DATA_PATH = os.environ.get("DATA_PATH", "/tmp/kip_helper.db")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

user_modes = {}
user_data = {}
quiz_state = {}
dialog_memory = {}
last_visual_context = {}

COLORS = {
    "black": ("⚫ Чёрный", 0),
    "brown": ("🟤 Коричневый", 1),
    "red": ("🔴 Красный", 2),
    "orange": ("🟠 Оранжевый", 3),
    "yellow": ("🟡 Жёлтый", 4),
    "green": ("🟢 Зелёный", 5),
    "blue": ("🔵 Синий", 6),
    "violet": ("🟣 Фиолетовый", 7),
    "gray": ("⚪ Серый", 8),
    "white": ("⬜ Белый", 9),
}

QUIZ = [
    ("Какой ток соответствует 50% диапазона 4–20 мА?", ["8 мА", "12 мА", "16 мА"], 1),
    ("Как подключают вольтметр?", ["Последовательно", "Параллельно", "Как угодно"], 1),
    ("Как подключают амперметр?", ["Параллельно", "Последовательно", "Через землю"], 1),
    ("Что означает NO?", ["Нормально открытый", "Нормально закрытый", "Нет питания"], 0),
    ("Что означает NC?", ["Нормально открытый", "Нормально закрытый", "Нет контакта"], 1),
    ("Какой ток соответствует 0% для 4–20 мА?", ["0 мА", "4 мА", "20 мА"], 1),
    ("Формула мощности постоянного тока?", ["P=U×I", "P=U/I", "P=I/R"], 0),
    ("Pt100 при 0°C имеет примерно:", ["50 Ом", "100 Ом", "1000 Ом"], 1),
    ("При 0 мА в петле первым делом проверяют:", ["Питание и обрыв", "Цвет корпуса", "Марку кабеля"], 0),
    ("Стабильно >20 мА может означать:", ["Выход за диапазон/аварию", "Всегда норму", "Нет питания"], 0),
]

LESSONS = {
    "lesson_signals": (
        "📘 <b>Урок: токовые сигналы</b>\n\n"
        "• 4–20 мА: 4 мА = 0%, 20 мА = 100%.\n"
        "• 0–20, 0–10 и 0–5 мА начинаются с 0 мА.\n"
        "• «Живой ноль» 4 мА помогает отличить 0% измерения от обрыва.\n"
        "• Токовый сигнал удобен на длинных линиях."
    ),
    "lesson_multimeter": (
        "📘 <b>Урок: мультиметр</b>\n\n"
        "Напряжение измеряют параллельно, ток — последовательно. "
        "Сопротивление и прозвонку измеряют на обесточенной цепи. "
        "Перед измерением тока проверь гнездо щупа и предел."
    ),
    "lesson_schemes": (
        "📘 <b>Урок: схемы</b>\n\n"
        "NO — нормально открытый, NC — нормально закрытый, COM — общий. "
        "Для DC часто встречаются +24V и 0V. "
        "Распиновку конкретного прибора всегда сверяй по его схеме."
    ),
    "lesson_pt100": (
        "📘 <b>Урок: Pt100</b>\n\n"
        "Pt100 имеет 100 Ω при 0°C. С ростом температуры сопротивление растёт. "
        "Для точной проверки используют таблицу IEC 60751; быстрый расчёт в боте — приближённый."
    ),
}

BASE_DEVICES = {
    "base_sh79": (
        "Ш-79",
        "Преобразователь/прибор старых систем автоматики. Точные вход, выход и питание зависят от исполнения. "
        "Для проверки сначала прочитай шильдик и схему конкретного экземпляра; затем проверь питание, вход и выход."
    ),
    "base_bu12": (
        "БУ-12",
        "Блок управления/преобразования, встречающийся в старых системах автоматики. "
        "Точные характеристики без шильдика не угадываются — бот может разобрать фото маркировки."
    ),
    "base_pt100": (
        "Pt100",
        "Платиновый термосопротивление: около 100 Ω при 0°C. "
        "Проверяется омметром на обесточенной цепи, с учётом схемы 2/3/4 провода."
    ),
    "base_420": (
        "Преобразователь 4–20 мА",
        "Типовой промышленный выход: 4 мА = 0%, 20 мА = 100%. "
        "Проверяют питание, ток петли, нагрузку, полярность и соответствие физическому параметру."
    ),
}


def db():
    conn = sqlite3.connect(DATA_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS journal(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            note TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS devices(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            range_text TEXT,
            signal TEXT,
            power TEXT,
            note TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS progress(
            user_id INTEGER PRIMARY KEY,
            xp INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def add_xp(uid, amount):
    conn = db()
    conn.execute(
        "INSERT INTO progress(user_id,xp) VALUES(?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET xp=xp+excluded.xp",
        (uid, amount)
    )
    conn.commit()
    xp = conn.execute("SELECT xp FROM progress WHERE user_id=?", (uid,)).fetchone()[0]
    conn.close()
    return xp


def get_xp(uid):
    conn = db()
    row = conn.execute("SELECT xp FROM progress WHERE user_id=?", (uid,)).fetchone()
    conn.close()
    return row[0] if row else 0


def level_name(xp):
    if xp < 50:
        return "Новичок"
    if xp < 150:
        return "Слесарь КИПиА"
    if xp < 300:
        return "Специалист"
    if xp < 600:
        return "Мастер"
    return "Эксперт КИПиА"


def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def b(text, data):
    return InlineKeyboardButton(text=text, callback_data=data)


def back(target="menu"):
    return kb([[b("⬅️ Назад", target)]])


def main_menu():
    return kb([
        [b("🧰 Рабочий режим", "work")],
        [b("📈 Токовые сигналы", "signals")],
        [b("⚡ Электрокалькуляторы", "electric")],
        [b("🌡 Температура / Pt100", "temperature")],
        [b("🔧 Диагностика", "diagnostics")],
        [b("🧪 Мультиметр", "multimeter")],
        [b("📐 Схемы и подключения", "schemes")],
        [b("🎛 База приборов", "devices")],
        [b("⭐ Мои приборы", "my_devices")],
        [b("📝 Журнал работ", "journal")],
        [b("🎓 Обучение", "learning")],
        [b("🤖 ИИ-КИПовец", "ai")],
        [b("📷 Фото-анализ", "photo_menu")],
        [b("🔎 Найти документацию", "docs_search")],
        [b("🎙 Голосовой вопрос", "voice_help")],
    ])


def work_menu():
    return kb([
        [b("🧮 Рассчитать сигнал", "universal_scale")],
        [b("🔧 Найти неисправность", "diagnostics")],
        [b("🧪 Проверить мультиметром", "multimeter")],
        [b("📷 Сфотографировать прибор", "vision")],
        [b("🤖 Спросить ИИ", "ai")],
        [b("⬅️ В меню", "menu")],
    ])


def signals_menu():
    return kb([
        [b("🧮 Универсальный пересчёт", "universal_scale")],
        [b("4–20: мА → %", "ma_to_percent"), b("% → мА", "percent_to_ma")],
        [b("4–20: мА → значение", "ma_to_value")],
        [b("4–20: значение → мА", "value_to_ma")],
        [b("0–5 мА → %", "ma05_to_percent"), b("% → 0–5", "percent_to_ma05")],
        [b("0–10 мА → %", "ma010_to_percent"), b("% → 0–10", "percent_to_ma010")],
        [b("0–20 мА → %", "ma020_to_percent"), b("% → 0–20", "percent_to_ma020")],
        [b("0–10 В → %", "v_to_percent")],
        [b("📚 Разница сигналов", "signal_info")],
        [b("⬅️ В меню", "menu")],
    ])


def electric_menu():
    return kb([
        [b("Найти U", "calc_u"), b("Найти I", "calc_i"), b("Найти R", "calc_r")],
        [b("Мощность P", "calc_p")],
        [b("Последовательные R", "series_r")],
        [b("Параллельные R", "parallel_r")],
        [b("Делитель напряжения", "divider")],
        [b("⬅️ В меню", "menu")],
    ])


def temp_menu():
    return kb([
        [b("Pt100: Ω → °C", "pt100_r_to_t")],
        [b("Pt100: °C → Ω", "pt100_t_to_r")],
        [b("Термопары: справка", "thermocouples")],
        [b("Как проверить Pt100", "pt100_check")],
        [b("⬅️ В меню", "menu")],
    ])


def diag_menu():
    return kb([
        [b("🧭 Пошаговая диагностика", "diag_wizard")],
        [b("0 мА", "diag_0"), b("<4 мА", "diag_low")],
        [b("4 мА постоянно", "diag_4")],
        [b("20 мА постоянно", "diag_20")],
        [b(">20 мА", "diag_high")],
        [b("Показания скачут", "diag_jump")],
        [b("⬅️ В меню", "menu")],
    ])


def multimeter_menu():
    return kb([
        [b("Измерить напряжение", "mm_voltage")],
        [b("Измерить ток", "mm_current")],
        [b("Измерить сопротивление", "mm_resistance")],
        [b("Прозвонить цепь", "mm_continuity")],
        [b("Проверить 4–20 мА", "mm_420")],
        [b("Проверить Pt100", "pt100_check")],
        [b("⬅️ В меню", "menu")],
    ])


def scheme_menu():
    return kb([
        [b("NO / NC", "scheme_contacts")],
        [b("Реле / катушка", "scheme_relay")],
        [b("Клеммы / питание", "scheme_power")],
        [b("2-проводный датчик", "scheme_2wire")],
        [b("3-проводный датчик", "scheme_3wire")],
        [b("4-проводный датчик", "scheme_4wire")],
        [b("📷 Разобрать схему по фото", "photo_scheme")],
        [b("⬅️ В меню", "menu")],
    ])


def devices_menu():
    rows = [[b(name, key)] for key, (name, _) in BASE_DEVICES.items()]
    rows.append([b("⬅️ В меню", "menu")])
    return kb(rows)


def my_devices_menu():
    return kb([
        [b("➕ Добавить прибор", "mydev_add")],
        [b("📋 Показать мои приборы", "mydev_list")],
        [b("⬅️ В меню", "menu")],
    ])


def journal_menu():
    return kb([
        [b("➕ Добавить запись", "journal_add")],
        [b("📋 Последние записи", "journal_list")],
        [b("⬅️ В меню", "menu")],
    ])


def learning_menu():
    return kb([
        [b("📘 Токовые сигналы", "lesson_signals")],
        [b("📘 Мультиметр", "lesson_multimeter")],
        [b("📘 Чтение схем", "lesson_schemes")],
        [b("📘 Pt100", "lesson_pt100")],
        [b("🧠 Тест 10 вопросов", "quiz")],
        [b("🏆 Мой уровень", "profile")],
        [b("⬅️ В меню", "menu")],
    ])


def photo_menu():
    return kb([
        [b("📟 Что за прибор?", "vision")],
        [b("🏷 Разобрать шильдик", "photo_label")],
        [b("📐 Разобрать схему", "photo_scheme")],
        [b("🎨 Номинал резистора", "photo_resistor")],
        [b("⬅️ В меню", "menu")],
    ])


@dp.message(CommandStart())
async def start(message: Message):
    uid = message.from_user.id
    user_modes.pop(uid, None)
    user_data.pop(uid, None)
    xp = get_xp(uid)
    await message.answer(
        f"⚙️ <b>КИП Помощник MAX</b>\n"
        f"Уровень: <b>{level_name(xp)}</b> · {xp} XP\n\n"
        "Выбери раздел:",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "menu")
async def menu(callback: CallbackQuery):
    uid = callback.from_user.id
    user_modes.pop(uid, None)
    user_data.pop(uid, None)
    xp = get_xp(uid)
    await callback.message.edit_text(
        f"⚙️ <b>КИП Помощник MAX</b>\n"
        f"Уровень: <b>{level_name(xp)}</b> · {xp} XP\n\n"
        "Выбери раздел:",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "work")
async def cb_work(callback: CallbackQuery):
    await callback.message.edit_text("🧰 <b>Рабочий режим</b>", reply_markup=work_menu(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "signals")
async def cb_signals(callback: CallbackQuery):
    await callback.message.edit_text("📈 <b>Токовые сигналы</b>", reply_markup=signals_menu(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "electric")
async def cb_electric(callback: CallbackQuery):
    await callback.message.edit_text("⚡ <b>Электрокалькуляторы</b>", reply_markup=electric_menu(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "temperature")
async def cb_temperature(callback: CallbackQuery):
    await callback.message.edit_text("🌡 <b>Температура и Pt100</b>", reply_markup=temp_menu(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "diagnostics")
async def cb_diagnostics(callback: CallbackQuery):
    await callback.message.edit_text("🔧 <b>Диагностика</b>", reply_markup=diag_menu(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "multimeter")
async def cb_multimeter(callback: CallbackQuery):
    await callback.message.edit_text("🧪 <b>Мультиметр</b>", reply_markup=multimeter_menu(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "schemes")
async def cb_schemes(callback: CallbackQuery):
    await callback.message.edit_text("📐 <b>Схемы и подключения</b>", reply_markup=scheme_menu(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "devices")
async def cb_devices(callback: CallbackQuery):
    await callback.message.edit_text("🎛 <b>База приборов</b>", reply_markup=devices_menu(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "my_devices")
async def cb_my_devices(callback: CallbackQuery):
    await callback.message.edit_text("⭐ <b>Мои приборы</b>", reply_markup=my_devices_menu(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "journal")
async def cb_journal(callback: CallbackQuery):
    await callback.message.edit_text("📝 <b>Журнал работ</b>", reply_markup=journal_menu(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "learning")
async def cb_learning(callback: CallbackQuery):
    await callback.message.edit_text("🎓 <b>Обучение</b>", reply_markup=learning_menu(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "photo_menu")
async def cb_photo_menu(callback: CallbackQuery):
    await callback.message.edit_text("📷 <b>Фото-анализ</b>", reply_markup=photo_menu(), parse_mode="HTML")
    await callback.answer()


async def activate_mode(callback, mode, prompt, parent):
    uid = callback.from_user.id
    user_modes[uid] = mode
    user_data[uid] = {"back": parent}
    await callback.message.edit_text(prompt, reply_markup=back(parent), parse_mode="HTML")
    await callback.answer()


MODE_MAP = {
    "universal_scale": (
        "universal_scale",
        "🧮 <b>Универсальный пересчёт</b>\n\n"
        "Введи: <code>тип сигнал минимум максимум</code>\n"
        "Примеры:\n"
        "<code>4-20 12 0 10</code>\n"
        "<code>0-20 8 0 1.6</code>\n"
        "<code>0-10 5 0 100</code>\n"
        "<code>0-5 2.5 -50 150</code>",
        "signals"
    ),
    "ma_to_percent": ("ma_to_percent", "Введи ток 4–20 мА, например <code>11.5</code>", "signals"),
    "percent_to_ma": ("percent_to_ma", "Введи процент 0–100, например <code>50</code>", "signals"),
    "ma_to_value": ("ma_to_value", "Введи <code>ток минимум максимум</code>, например <code>11.5 0 1.6</code>", "signals"),
    "value_to_ma": ("value_to_ma", "Введи <code>значение минимум максимум</code>, например <code>0.75 0 1.6</code>", "signals"),
    "v_to_percent": ("v_to_percent", "Введи напряжение 0–10 В, например <code>6.2</code>", "signals"),
    "ma05_to_percent": ("ma05_to_percent", "Введи ток 0–5 мА, например <code>2.5</code>", "signals"),
    "percent_to_ma05": ("percent_to_ma05", "Введи процент, например <code>50</code>", "signals"),
    "ma010_to_percent": ("ma010_to_percent", "Введи ток 0–10 мА, например <code>5</code>", "signals"),
    "percent_to_ma010": ("percent_to_ma010", "Введи процент, например <code>50</code>", "signals"),
    "ma020_to_percent": ("ma020_to_percent", "Введи ток 0–20 мА, например <code>10</code>", "signals"),
    "percent_to_ma020": ("percent_to_ma020", "Введи процент, например <code>50</code>", "signals"),
    "calc_u": ("calc_u", "Введи <code>I R</code> (А и Ом), например <code>0.5 220</code>", "electric"),
    "calc_i": ("calc_i", "Введи <code>U R</code>, например <code>24 120</code>", "electric"),
    "calc_r": ("calc_r", "Введи <code>U I</code>, например <code>24 0.02</code>", "electric"),
    "calc_p": ("calc_p", "Введи <code>U I</code>, например <code>220 2.5</code>", "electric"),
    "series_r": ("series_r", "Введи сопротивления через пробел, например <code>100 220 330</code>", "electric"),
    "parallel_r": ("parallel_r", "Введи сопротивления через пробел, например <code>100 220</code>", "electric"),
    "divider": ("divider", "Введи <code>Vin R1 R2</code>, например <code>24 1000 1000</code>", "electric"),
    "pt100_r_to_t": ("pt100_r_to_t", "Введи сопротивление Pt100 в Ом, например <code>138.5</code>", "temperature"),
    "pt100_t_to_r": ("pt100_t_to_r", "Введи температуру °C, например <code>100</code>", "temperature"),
    "journal_add": ("journal_add", "Напиши запись в журнал. Например:\n<code>Заменил датчик давления поз. 4-17</code>", "journal"),
    "mydev_add": (
        "mydev_add",
        "Добавь прибор в формате:\n"
        "<code>Название | диапазон | сигнал | питание | примечание</code>\n\n"
        "Пример:\n<code>Давление 4-17 | 0-1.6 МПа | 4-20 мА | 24 В | цех 4</code>",
        "my_devices"
    ),
    "docs_search": (
        "docs_search",
        "🔎 Введи точную модель прибора. Я попробую найти/собрать информацию и подсказать, где искать паспорт.\n"
        "Пример: <code>Rosemount 3051</code>",
        "menu"
    ),
}


@dp.callback_query(F.data.in_(list(MODE_MAP.keys())))
async def generic_mode(callback: CallbackQuery):
    mode, prompt, parent = MODE_MAP[callback.data]
    await activate_mode(callback, mode, prompt, parent)


@dp.callback_query(F.data == "signal_info")
async def signal_info(callback: CallbackQuery):
    await callback.message.edit_text(
        "📚 <b>Сигналы</b>\n\n"
        "• 4–20 мА — «живой ноль»: 4 мА = 0%, 20 мА = 100%.\n"
        "• 0–20 мА — 0 мА = 0%, 20 мА = 100%.\n"
        "• 0–10 мА — 0 мА = 0%, 10 мА = 100%.\n"
        "• 0–5 мА — 0 мА = 0%, 5 мА = 100%.\n"
        "• 0–10 В — напряженческий сигнал; на длинных линиях сильнее влияет падение напряжения и помехи.",
        reply_markup=back("signals"),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "thermocouples")
async def thermocouples(callback: CallbackQuery):
    await callback.message.edit_text(
        "🌡 <b>Термопары</b>\n\n"
        "K (ХА) и L (ХК) — распространённые типы. Термопара выдаёт милливольты, "
        "зависящие от температуры и холодного спая. Для точной проверки нужна таблица ЭДС конкретного типа.",
        reply_markup=back("temperature"),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "pt100_check")
async def pt100_check(callback: CallbackQuery):
    await callback.message.edit_text(
        "🔧 <b>Проверка Pt100</b>\n\n"
        "1. Обесточь цепь и отсоедини датчик.\n"
        "2. Переключи мультиметр в Ω.\n"
        "3. Ориентир: ~100 Ω при 0°C, ~138.5 Ω при 100°C.\n"
        "4. ∞ Ω — вероятен обрыв; почти 0 Ω — вероятно КЗ.\n"
        "5. В 3/4-проводной схеме учитывай компенсационные проводники.",
        reply_markup=back("temperature"),
        parse_mode="HTML"
    )
    await callback.answer()


MM_TEXTS = {
    "mm_voltage": (
        "🧪 <b>Измерение напряжения</b>\n\n"
        "Щупы: COM и VΩ. Режим: V⎓ для DC или V~ для AC. "
        "Подключай параллельно участку. Начинай с подходящего высокого предела."
    ),
    "mm_current": (
        "🧪 <b>Измерение тока</b>\n\n"
        "Ток измеряют последовательно, разрывая цепь. "
        "Перед подключением проверь гнездо A/mA и предел. "
        "Никогда не ставь мультиметр в режиме тока параллельно источнику."
    ),
    "mm_resistance": (
        "🧪 <b>Сопротивление</b>\n\n"
        "Измеряй только на обесточенной цепи. Щупы COM и VΩ, режим Ω. "
        "Для точности по возможности отсоедини элемент от параллельных цепей."
    ),
    "mm_continuity": (
        "🧪 <b>Прозвонка</b>\n\n"
        "Обесточь цепь. Выбери режим 🔔. Малое сопротивление/звуковой сигнал обычно означает электрический контакт."
    ),
    "mm_420": (
        "🧪 <b>Проверка 4–20 мА</b>\n\n"
        "Мультиметр включается последовательно в петлю. "
        "4 мА ≈ 0%, 12 мА ≈ 50%, 20 мА ≈ 100%. "
        "Перед измерением проверь допустимый ток входа мультиметра и его предохранитель."
    ),
}


@dp.callback_query(F.data.in_(list(MM_TEXTS.keys())))
async def mm_info(callback: CallbackQuery):
    await callback.message.edit_text(MM_TEXTS[callback.data], reply_markup=back("multimeter"), parse_mode="HTML")
    await callback.answer()


SCHEME_TEXTS = {
    "scheme_contacts": "📐 <b>NO / NC</b>\n\nNO — нормально открытый, NC — нормально закрытый, COM — общий.",
    "scheme_relay": "📐 <b>Реле</b>\n\nКатушка часто A1/A2. При подаче питания контакты переключаются.",
    "scheme_power": "📐 <b>Питание</b>\n\nAC: L, N, PE. DC: часто +24V и 0V. Защитное заземление не заменяет рабочий ноль.",
    "scheme_2wire": "📐 <b>2-проводный датчик</b>\n\nПитание и сигнал идут по двум проводам; прибор включается последовательно в токовую петлю.",
    "scheme_3wire": "📐 <b>3-проводный датчик</b>\n\nОбычно +питание, 0V и сигнал. Точную распиновку смотри в паспорте.",
    "scheme_4wire": "📐 <b>4-проводный датчик</b>\n\nПитание и выходной сигнал могут быть раздельными парами. Точная схема зависит от модели.",
}


@dp.callback_query(F.data.in_(list(SCHEME_TEXTS.keys())))
async def scheme_info(callback: CallbackQuery):
    await callback.message.edit_text(SCHEME_TEXTS[callback.data], reply_markup=back("schemes"), parse_mode="HTML")
    await callback.answer()


DIAG_TEXTS = {
    "diag_0": "🔧 <b>0 мА</b>\n\nПроверь питание, предохранитель, обрыв, полярность, клеммы и напряжение непосредственно на датчике.",
    "diag_low": "🔧 <b><4 мА</b>\n\nВозможны аварийный ток, недопитание, плохой контакт, большая нагрузка петли или неисправность преобразователя.",
    "diag_4": "🔧 <b>≈4 мА</b>\n\nМожет быть нормальный 0%. Если процесс не нулевой — проверь первичный элемент, импульсные линии и настройку диапазона.",
    "diag_20": "🔧 <b>≈20 мА</b>\n\nМожет быть нормальный 100%. Если процесс ниже — проверь диапазон, калибровку и первичный элемент.",
    "diag_high": "🔧 <b>>20 мА</b>\n\nЧасто это выход за диапазон или аварийный ток. Конкретное значение зависит от модели прибора.",
    "diag_jump": "🔧 <b>Скачет</b>\n\nПроверь клеммы, экран, заземление, питание, помехи, вибрацию, пульсации процесса и плохие контакты.",
}


@dp.callback_query(F.data.in_(list(DIAG_TEXTS.keys())))
async def diag_info(callback: CallbackQuery):
    await callback.message.edit_text(DIAG_TEXTS[callback.data], reply_markup=back("diagnostics"), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "diag_wizard")
async def diag_wizard(callback: CallbackQuery):
    user_data[callback.from_user.id] = {"diag": {}}
    await callback.message.edit_text(
        "🧭 <b>Пошаговая диагностика</b>\n\nЕсть питание на приборе?",
        reply_markup=kb([
            [b("✅ Да", "dw_power_yes"), b("❌ Нет", "dw_power_no")],
            [b("⬅️ Назад", "diagnostics")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "dw_power_no")
async def dw_power_no(callback: CallbackQuery):
    await callback.message.edit_text(
        "Сначала восстанови питание: проверь автомат/предохранитель, клеммы, полярность и источник. "
        "После этого повтори измерение.",
        reply_markup=back("diagnostics")
    )
    await callback.answer()


@dp.callback_query(F.data == "dw_power_yes")
async def dw_power_yes(callback: CallbackQuery):
    await callback.message.edit_text(
        "Какой ток в петле?",
        reply_markup=kb([
            [b("0 мА", "diag_0"), b("<4 мА", "diag_low")],
            [b("4–20 мА", "dw_current_normal"), b(">20 мА", "diag_high")],
            [b("Скачет", "diag_jump")],
            [b("⬅️ Назад", "diagnostics")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "dw_current_normal")
async def dw_current_normal(callback: CallbackQuery):
    await callback.message.edit_text(
        "Ток находится в рабочем диапазоне. Сравни его с реальным технологическим параметром. "
        "Если ток правильный, а на контроллере значение неверное — проверь масштабирование входа, клеммы и конфигурацию канала.",
        reply_markup=back("diagnostics")
    )
    await callback.answer()


@dp.callback_query(F.data.in_(list(BASE_DEVICES.keys())))
async def base_device(callback: CallbackQuery):
    name, text = BASE_DEVICES[callback.data]
    await callback.message.edit_text(
        f"🎛 <b>{escape(name)}</b>\n\n{escape(text)}",
        reply_markup=back("devices"),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "mydev_list")
async def mydev_list(callback: CallbackQuery):
    uid = callback.from_user.id
    conn = db()
    rows = conn.execute(
        "SELECT name, range_text, signal, power, note FROM devices WHERE user_id=? ORDER BY id DESC LIMIT 10",
        (uid,)
    ).fetchall()
    conn.close()
    if not rows:
        text = "⭐ Пока нет сохранённых приборов."
    else:
        blocks = []
        for i, row in enumerate(rows, 1):
            name, rng, signal, power, note = row
            blocks.append(
                f"{i}. <b>{escape(name)}</b>\n"
                f"Диапазон: {escape(rng or '—')}\n"
                f"Сигнал: {escape(signal or '—')}\n"
                f"Питание: {escape(power or '—')}\n"
                f"Примечание: {escape(note or '—')}"
            )
        text = "⭐ <b>Мои приборы</b>\n\n" + "\n\n".join(blocks)
    await callback.message.edit_text(text, reply_markup=back("my_devices"), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "journal_list")
async def journal_list(callback: CallbackQuery):
    uid = callback.from_user.id
    conn = db()
    rows = conn.execute(
        "SELECT created_at,note FROM journal WHERE user_id=? ORDER BY id DESC LIMIT 10",
        (uid,)
    ).fetchall()
    conn.close()
    if not rows:
        text = "📝 Журнал пока пуст."
    else:
        text = "📝 <b>Последние записи</b>\n\n" + "\n\n".join(
            f"<b>{escape(dt)}</b>\n{escape(note)}" for dt, note in rows
        )
    await callback.message.edit_text(text, reply_markup=back("journal"), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.in_(list(LESSONS.keys())))
async def lesson(callback: CallbackQuery):
    xp = add_xp(callback.from_user.id, 5)
    await callback.message.edit_text(
        LESSONS[callback.data] + f"\n\n+5 XP · теперь {xp} XP",
        reply_markup=back("learning"),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    xp = get_xp(callback.from_user.id)
    await callback.message.edit_text(
        f"🏆 <b>Твой уровень</b>\n\n{level_name(xp)}\nXP: {xp}",
        reply_markup=back("learning"),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "quiz")
async def quiz_start(callback: CallbackQuery):
    uid = callback.from_user.id
    quiz_state[uid] = {
        "score": 0,
        "n": 0,
        "order": random.sample(range(len(QUIZ)), k=min(10, len(QUIZ)))
    }
    await send_quiz_question(callback.message, uid, edit=True)
    await callback.answer()


async def send_quiz_question(message, uid, edit=False):
    st = quiz_state[uid]
    if st["n"] >= len(st["order"]):
        gained = st["score"] * 3
        xp = add_xp(uid, gained)
        text = (
            f"🧠 <b>Тест завершён</b>\n\n"
            f"Результат: <b>{st['score']}/{len(st['order'])}</b>\n"
            f"+{gained} XP · всего {xp} XP"
        )
        if edit:
            await message.edit_text(text, reply_markup=back("learning"), parse_mode="HTML")
        else:
            await message.answer(text, reply_markup=back("learning"), parse_mode="HTML")
        return

    qidx = st["order"][st["n"]]
    q, answers, correct = QUIZ[qidx]
    rows = [[b(a, f"qa:{i}:{qidx}")] for i, a in enumerate(answers)]
    rows.append([b("⬅️ Завершить", "learning")])
    text = f"🧠 <b>Вопрос {st['n']+1}/{len(st['order'])}</b>\n\n{q}"
    if edit:
        await message.edit_text(text, reply_markup=kb(rows), parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=kb(rows), parse_mode="HTML")


@dp.callback_query(F.data.startswith("qa:"))
async def quiz_answer(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in quiz_state:
        await callback.answer("Тест завершён")
        return
    _, ans, qidx = callback.data.split(":")
    ans, qidx = int(ans), int(qidx)
    correct = QUIZ[qidx][2]
    st = quiz_state[uid]
    if ans == correct:
        st["score"] += 1
        await callback.answer("✅ Верно")
    else:
        await callback.answer("❌ Неверно")
    st["n"] += 1
    await send_quiz_question(callback.message, uid, edit=True)


@dp.callback_query(F.data == "ai")
async def ai_mode(callback: CallbackQuery):
    uid = callback.from_user.id
    user_modes[uid] = "ai"
    text = (
        "🤖 <b>ИИ-КИПовец</b>\n\n"
        "Пиши обычным текстом. Я помню последние сообщения этого диалога и последнее разобранное фото."
        if GEMINI_API_KEY else
        "Добавь GEMINI_API_KEY в Render."
    )
    await callback.message.edit_text(text, reply_markup=back("menu"), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.in_(["vision", "photo_label", "photo_scheme", "photo_resistor"]))
async def visual_mode(callback: CallbackQuery):
    user_modes[callback.from_user.id] = callback.data
    prompts = {
        "vision": "📟 Отправь фото прибора целиком или шильдик.",
        "photo_label": "🏷 Отправь крупное фото шильдика.",
        "photo_scheme": "📐 Отправь фото электрической/КИП-схемы.",
        "photo_resistor": "🎨 Отправь резкое фото резистора с видимыми полосами.",
    }
    await callback.message.edit_text(prompts[callback.data], reply_markup=back("photo_menu"))
    await callback.answer()


@dp.callback_query(F.data == "voice_help")
async def voice_help(callback: CallbackQuery):
    await callback.message.edit_text(
        "🎙 <b>Голосовой вопрос</b>\n\n"
        "Отправь боту голосовое сообщение. Gemini распознает смысл и ответит по КИПиА.",
        reply_markup=back("menu"),
        parse_mode="HTML"
    )
    await callback.answer()


def format_resistance(v):
    if v >= 1_000_000:
        return f"{v/1_000_000:g} МОм"
    if v >= 1000:
        return f"{v/1000:g} кОм"
    return f"{v:g} Ом"


def signal_fraction(kind, signal):
    kind = kind.lower().replace("ма", "").replace(" ", "")
    if kind in ("4-20", "4–20"):
        return (signal - 4.0) / 16.0
    if kind in ("0-20", "0–20"):
        return signal / 20.0
    if kind in ("0-10", "0–10"):
        return signal / 10.0
    if kind in ("0-5", "0–5"):
        return signal / 5.0
    raise ValueError("Неизвестный тип сигнала")


def memory_context(uid):
    history = dialog_memory.get(uid, [])[-6:]
    parts = []
    for role, text in history:
        parts.append(f"{role}: {text}")
    if uid in last_visual_context:
        parts.append("Последний разобранный объект/фото: " + last_visual_context[uid][:1500])
    return "\n".join(parts)


def remember(uid, role, text):
    dialog_memory.setdefault(uid, []).append((role, text))
    dialog_memory[uid] = dialog_memory[uid][-8:]


async def gemini_generate(contents, use_search=False):
    from google import genai
    from google.genai import types
    from google.genai.errors import ServerError

    def run_once():
        client = genai.Client(api_key=GEMINI_API_KEY)
        kwargs = {"model": GEMINI_MODEL, "contents": contents}
        if use_search:
            try:
                kwargs["config"] = types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())]
                )
            except Exception:
                pass
        response = client.models.generate_content(**kwargs)
        return response.text or "Gemini не вернул текстовый ответ."

    delays = [2, 4, 7]
    last = None
    for attempt in range(4):
        try:
            return await asyncio.to_thread(run_once)
        except ServerError as e:
            last = e
            if "503" not in str(e) and "UNAVAILABLE" not in str(e):
                raise
            if attempt < 3:
                await asyncio.sleep(delays[attempt])
    raise last


async def ai_text(uid, prompt, search=False):
    context = memory_context(uid)
    system = (
        "Ты практичный помощник слесаря КИПиА. Отвечай по-русски, понятно и по делу. "
        "Помогай с 4–20/0–20/0–10/0–5 мА, Pt100, термопарами, датчиками, мультиметром, "
        "схемами, диагностикой и расчётами. Не выдумывай характеристики конкретной модели. "
        "Если работа опасна, напоминай об отключении питания, проверке отсутствия напряжения "
        "и соблюдении инструкций предприятия. "
        "Если пользователь ссылается на 'этот прибор' или 'его', используй контекст диалога.\n\n"
    )
    full = system
    if context:
        full += "Контекст:\n" + context + "\n\n"
    full += "Вопрос пользователя: " + prompt
    answer = await gemini_generate(full, use_search=search)
    remember(uid, "Пользователь", prompt)
    remember(uid, "Ассистент", answer)
    return answer


async def ai_image(uid, data, mime, mode, caption=""):
    from google.genai import types

    image = types.Part.from_bytes(data=data, mime_type=mime)
    prompts = {
        "vision": (
            "Проанализируй фото прибора КИП/электрики. Укажи: что это предположительно, назначение, "
            "что реально читается на маркировке, видимые диапазон/сигнал/питание и как обычно проверить. "
            "Не выдумывай нечитаемые данные."
        ),
        "photo_label": (
            "Разбери шильдик максимально внимательно. Выпиши только реально читаемые: производитель, модель, "
            "серийный номер если виден, питание, вход, выход, диапазон, единицы, степень защиты и клеммы. "
            "Затем кратко объясни назначение. Нечитаемое пометь как 'не читается'."
        ),
        "photo_scheme": (
            "Разбери схему как помощник КИПиА: выдели питание, клеммы, датчики, реле, NO/NC, сигнальные цепи, "
            "предполагаемый путь сигнала. Если обозначения размыты — не выдумывай. Объясни пошагово."
        ),
        "photo_resistor": (
            "Определи цветовые полосы резистора и рассчитай номинал и допуск. "
            "Если цвета неоднозначны из-за света/качества фото — перечисли возможные варианты и попроси фото лучше."
        ),
    }
    prompt = prompts.get(mode, prompts["vision"]) + f"\nКомментарий пользователя: {caption}"
    answer = await gemini_generate([image, prompt])
    last_visual_context[uid] = answer
    remember(uid, "Ассистент по фото", answer)
    return answer


async def ai_audio(uid, data, mime):
    from google.genai import types
    audio = types.Part.from_bytes(data=data, mime_type=mime)
    prompt = (
        "Прослушай голосовое сообщение пользователя. Сначала пойми его вопрос, затем ответь по-русски "
        "как практичный помощник слесаря КИПиА. Если в речи есть числа и единицы — аккуратно используй их."
    )
    answer = await gemini_generate([audio, prompt])
    remember(uid, "Голосовой вопрос", "(аудио)")
    remember(uid, "Ассистент", answer)
    return answer


@dp.message(F.photo)
async def photo_handler(message: Message):
    uid = message.from_user.id
    mode = user_modes.get(uid)
    if mode not in ("vision", "photo_label", "photo_scheme", "photo_resistor"):
        await message.answer("Открой /start → 📷 Фото-анализ и выбери режим.")
        return
    if not GEMINI_API_KEY:
        await message.answer("Нужен GEMINI_API_KEY в Render.")
        return
    try:
        p = message.photo[-1]
        file = await bot.get_file(p.file_id)
        bio = await bot.download_file(file.file_path)
        await message.answer("🔎 Анализирую…")
        answer = await ai_image(uid, bio.read(), "image/jpeg", mode, message.caption or "")
        await message.answer(answer, reply_markup=back("photo_menu"))
    except Exception as e:
        print(f"GEMINI PHOTO ERROR: {type(e).__name__}: {e}", flush=True)
        await message.answer("Не удалось разобрать фото. Попробуй ещё раз или отправь более чёткий снимок.")


@dp.message(F.voice)
async def voice_handler(message: Message):
    uid = message.from_user.id
    if not GEMINI_API_KEY:
        await message.answer("Для голосовых вопросов нужен GEMINI_API_KEY.")
        return
    try:
        file = await bot.get_file(message.voice.file_id)
        bio = await bot.download_file(file.file_path)
        await message.answer("🎙 Слушаю и разбираю…")
        answer = await ai_audio(uid, bio.read(), message.voice.mime_type or "audio/ogg")
        await message.answer(answer, reply_markup=back("menu"))
    except Exception as e:
        print(f"GEMINI AUDIO ERROR: {type(e).__name__}: {e}", flush=True)
        await message.answer("Не удалось обработать голосовое. Попробуй ещё раз.")


@dp.message()
async def handle_text(message: Message):
    uid = message.from_user.id
    mode = user_modes.get(uid)
    raw_text = (message.text or "").strip()
    raw = raw_text.replace(",", ".")

    if mode == "ai":
        if not GEMINI_API_KEY:
            await message.answer("Добавь GEMINI_API_KEY в Render.")
            return
        try:
            await message.answer("🤖 Думаю…")
            answer = await ai_text(uid, raw_text)
            await message.answer(answer, reply_markup=back("menu"))
        except Exception as e:
            print(f"GEMINI ERROR: {type(e).__name__}: {e}", flush=True)
            await message.answer("Gemini временно недоступен. Я уже сделал несколько попыток — повтори через минуту.")
        return

    if mode == "docs_search":
        if not GEMINI_API_KEY:
            await message.answer("Для поиска нужен GEMINI_API_KEY.")
            return
        try:
            await message.answer("🔎 Ищу информацию…")
            q = (
                f"Найди официальную документацию или надёжные сведения по прибору: {raw_text}. "
                "Дай точное название модели, производителя, назначение и что искать в паспорте. "
                "Если уверен в официальной странице/руководстве — укажи название документа/сайта. "
                "Не выдумывай ссылку."
            )
            answer = await ai_text(uid, q, search=True)
            await message.answer(answer, reply_markup=back("menu"))
        except Exception as e:
            print(f"DOC SEARCH ERROR: {type(e).__name__}: {e}", flush=True)
            await message.answer("Не удалось выполнить поиск. Попробуй указать модель точнее.")
        return

    if mode == "journal_add":
        if not raw_text:
            await message.answer("Запись пустая.")
            return
        conn = db()
        dt = datetime.now().strftime("%d.%m.%Y %H:%M")
        conn.execute("INSERT INTO journal(user_id,created_at,note) VALUES(?,?,?)", (uid, dt, raw_text))
        conn.commit()
        conn.close()
        xp = add_xp(uid, 2)
        user_modes.pop(uid, None)
        await message.answer(f"✅ Записал в журнал. +2 XP · всего {xp} XP", reply_markup=back("journal"))
        return

    if mode == "mydev_add":
        parts = [x.strip() for x in raw_text.split("|")]
        if len(parts) < 4:
            await message.answer("Нужно минимум 4 поля через | : название | диапазон | сигнал | питание | примечание")
            return
        while len(parts) < 5:
            parts.append("")
        conn = db()
        conn.execute(
            "INSERT INTO devices(user_id,name,range_text,signal,power,note,created_at) VALUES(?,?,?,?,?,?,?)",
            (uid, parts[0], parts[1], parts[2], parts[3], parts[4], datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        xp = add_xp(uid, 3)
        user_modes.pop(uid, None)
        await message.answer(f"✅ Прибор сохранён. +3 XP · всего {xp} XP", reply_markup=back("my_devices"))
        return

    if mode == "universal_scale":
        try:
            parts = raw.split()
            kind = parts[0]
            sig, vmin, vmax = map(float, parts[1:4])
            frac = signal_fraction(kind, sig)
            val = vmin + frac * (vmax - vmin)
            await message.answer(
                f"🧮 <b>{escape(kind)}</b>\n"
                f"Сигнал: <b>{sig:g} мА</b>\n"
                f"Процент: <b>{frac*100:.2f}%</b>\n"
                f"Значение: <b>{val:.5g}</b>",
                parse_mode="HTML",
                reply_markup=back("signals")
            )
        except Exception:
            await message.answer("Формат: тип сигнал минимум максимум. Пример: 4-20 12 0 10")
        return

    if not mode:
        await message.answer("Нажми /start и выбери раздел.")
        return

    try:
        nums = [float(x) for x in raw.split()]

        if mode == "ma_to_percent":
            ma = nums[0]
            text = f"📈 <b>{ma:g} мА = {(ma-4)/16*100:.2f}%</b>"
        elif mode == "percent_to_ma":
            p = nums[0]
            text = f"📈 <b>{p:g}% = {4+p/100*16:.3f} мА</b>"
        elif mode == "ma_to_value":
            ma, vmin, vmax = nums
            frac = (ma-4)/16
            text = f"📈 <b>{ma:g} мА = {frac*100:.2f}% = {vmin+frac*(vmax-vmin):.5g}</b>"
        elif mode == "value_to_ma":
            val, vmin, vmax = nums
            frac = (val-vmin)/(vmax-vmin)
            text = f"📈 <b>{val:g} = {frac*100:.2f}% = {4+frac*16:.3f} мА</b>"
        elif mode == "v_to_percent":
            v = nums[0]
            text = f"📈 <b>{v:g} В = {v/10*100:.2f}%</b>"
        elif mode == "ma05_to_percent":
            ma = nums[0]
            text = f"📈 <b>{ma:g} мА (0–5) = {ma/5*100:.2f}%</b>"
        elif mode == "percent_to_ma05":
            p = nums[0]
            text = f"📈 <b>{p:g}% = {p/100*5:.3f} мА (0–5)</b>"
        elif mode == "ma010_to_percent":
            ma = nums[0]
            text = f"📈 <b>{ma:g} мА (0–10) = {ma/10*100:.2f}%</b>"
        elif mode == "percent_to_ma010":
            p = nums[0]
            text = f"📈 <b>{p:g}% = {p/100*10:.3f} мА (0–10)</b>"
        elif mode == "ma020_to_percent":
            ma = nums[0]
            text = f"📈 <b>{ma:g} мА (0–20) = {ma/20*100:.2f}%</b>"
        elif mode == "percent_to_ma020":
            p = nums[0]
            text = f"📈 <b>{p:g}% = {p/100*20:.3f} мА (0–20)</b>"
        elif mode == "calc_u":
            i, r = nums
            text = f"⚡ <b>U = {i*r:.5g} В</b>"
        elif mode == "calc_i":
            u, r = nums
            text = f"⚡ <b>I = {u/r:.6g} А</b>"
        elif mode == "calc_r":
            u, i = nums
            text = f"⚡ <b>R = {format_resistance(u/i)}</b>"
        elif mode == "calc_p":
            u, i = nums
            text = f"🔌 <b>P = {u*i:.5g} Вт</b>"
        elif mode == "series_r":
            text = f"📐 <b>RΣ = {format_resistance(sum(nums))}</b>"
        elif mode == "parallel_r":
            total = 1/sum(1/x for x in nums)
            text = f"📐 <b>Rэкв = {format_resistance(total)}</b>"
        elif mode == "divider":
            vin, r1, r2 = nums
            text = f"📐 <b>Vout = {vin*r2/(r1+r2):.5g} В</b>"
        elif mode == "pt100_r_to_t":
            r = nums[0]
            t = (r/100-1)/0.00385
            text = f"🌡 <b>≈ {t:.1f} °C</b>\nПриближённо; для точности используй таблицу Pt100."
        elif mode == "pt100_t_to_r":
            t = nums[0]
            r = 100*(1+0.00385*t)
            text = f"🌡 <b>≈ {r:.2f} Ω</b>\nПриближённый расчёт."
        else:
            await message.answer("Нажми /start и выбери раздел.")
            return

        parent = user_data.get(uid, {}).get("back", "menu")
        await message.answer(text, reply_markup=back(parent), parse_mode="HTML")

    except (ValueError, ZeroDivisionError, IndexError):
        parent = user_data.get(uid, {}).get("back", "menu")
        await message.answer("Не понял ввод. Проверь числа и формат.", reply_markup=back(parent))


@asynccontextmanager
async def lifespan(app: FastAPI):
    db().close()
    if BASE_URL:
        await bot.set_webhook(
            url=f"{BASE_URL}/webhook",
            secret_token=WEBHOOK_SECRET,
            drop_pending_updates=True
        )
    yield
    await bot.session.close()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def health():
    return {"status": "ok", "bot": "KIP Helper MAX"}


@app.post("/webhook")
async def webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}