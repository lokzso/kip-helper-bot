import os
import random
import base64
from contextlib import asynccontextmanager

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
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL", "gpt-5.6-luna")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

user_modes = {}
user_data = {}
quiz_state = {}

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
    ("При 0 мА в петле 4–20 мА первым делом проверяют:", ["Питание и обрыв", "Цвет корпуса", "Марку кабеля"], 0),
    ("Стабильно >20 мА может означать:", ["Выход за диапазон/аварию", "Всегда норму", "Отсутствие питания"], 0),
]


def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def b(text, data):
    return InlineKeyboardButton(text=text, callback_data=data)


def main_menu():
    return kb([
        [b("📈 Сигналы 4–20 мА", "signals")],
        [b("⚡ Электрокалькуляторы", "electric")],
        [b("🌡 Температура / Pt100", "temperature")],
        [b("🎛 Датчики КИП", "sensors")],
        [b("🔧 Диагностика", "diagnostics")],
        [b("🎨 Резисторы", "resistors")],
        [b("📐 Обозначения на схемах", "schemes")],
        [b("🧠 Обучение / тест", "quiz")],
        [b("🤖 ИИ-КИПовец", "ai")],
        [b("📷 Что за прибор?", "vision")],
    ])


def back(target="menu"):
    return kb([[b("⬅️ Назад", target)]])


def signals_menu():
    return kb([
        [b("мА → %", "ma_to_percent"), b("% → мА", "percent_to_ma")],
        [b("мА → значение", "ma_to_value")],
        [b("значение → мА", "value_to_ma")],
        [b("0–10 В → %", "v_to_percent")],
        [b("0–5 мА → %", "ma05_to_percent")],
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


def sensors_menu():
    return kb([
        [b("Давление", "sensor_pressure")],
        [b("Температура", "sensor_temp")],
        [b("Уровень", "sensor_level")],
        [b("Расход", "sensor_flow")],
        [b("⬅️ В меню", "menu")],
    ])


def diagnostics_menu():
    return kb([
        [b("0 мА", "diag_0")],
        [b("<4 мА", "diag_low")],
        [b("4 мА постоянно", "diag_4")],
        [b("20 мА постоянно", "diag_20")],
        [b(">20 мА", "diag_high")],
        [b("Показания скачут", "diag_jump")],
        [b("⬅️ В меню", "menu")],
    ])


def resistors_menu():
    return kb([
        [b("Цвета → сопротивление", "res_color")],
        [b("Сопротивление → цвета", "res_value")],
        [b("Шпаргалка цветов", "res_info")],
        [b("⬅️ В меню", "menu")],
    ])


def scheme_menu():
    return kb([
        [b("NO / NC", "scheme_contacts")],
        [b("Реле / катушка", "scheme_relay")],
        [b("Клеммы / питание", "scheme_power")],
        [b("Датчик 2-проводный", "scheme_2wire")],
        [b("Датчик 3-проводный", "scheme_3wire")],
        [b("⬅️ В меню", "menu")],
    ])


@dp.message(CommandStart())
async def start(message: Message):
    uid = message.from_user.id
    user_modes.pop(uid, None)
    user_data.pop(uid, None)
    await message.answer(
        "⚙️ <b>КИП Помощник PRO</b>\n\nВыбери раздел:",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "menu")
async def menu(callback: CallbackQuery):
    uid = callback.from_user.id
    user_modes.pop(uid, None)
    user_data.pop(uid, None)
    await callback.message.edit_text(
        "⚙️ <b>КИП Помощник PRO</b>\n\nВыбери раздел:",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "signals")
async def cb_signals(callback: CallbackQuery):
    await callback.message.edit_text("📈 <b>Сигналы</b>", reply_markup=signals_menu(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "electric")
async def cb_electric(callback: CallbackQuery):
    await callback.message.edit_text("⚡ <b>Электрокалькуляторы</b>", reply_markup=electric_menu(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "temperature")
async def cb_temp(callback: CallbackQuery):
    await callback.message.edit_text("🌡 <b>Температура и Pt100</b>", reply_markup=temp_menu(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "sensors")
async def cb_sensors(callback: CallbackQuery):
    await callback.message.edit_text("🎛 <b>Датчики КИП</b>", reply_markup=sensors_menu(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "diagnostics")
async def cb_diag(callback: CallbackQuery):
    await callback.message.edit_text(
        "🔧 <b>Диагностика петли 4–20 мА</b>\n\nЧто наблюдаешь?",
        reply_markup=diagnostics_menu(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "resistors")
async def cb_res(callback: CallbackQuery):
    await callback.message.edit_text("🎨 <b>Резисторы</b>", reply_markup=resistors_menu(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "schemes")
async def cb_schemes(callback: CallbackQuery):
    await callback.message.edit_text("📐 <b>Обозначения на схемах</b>", reply_markup=scheme_menu(), parse_mode="HTML")
    await callback.answer()


async def activate_mode(callback, mode, prompt, parent):
    uid = callback.from_user.id
    user_modes[uid] = mode
    user_data[uid] = {"back": parent}
    await callback.message.edit_text(prompt, reply_markup=back(parent), parse_mode="HTML")
    await callback.answer()


MODE_MAP = {
    "ma_to_percent": ("ma_to_percent", "Введи ток в мА, например <code>11.5</code>", "signals"),
    "percent_to_ma": ("percent_to_ma", "Введи процент 0–100, например <code>50</code>", "signals"),
    "ma_to_value": ("ma_to_value", "Введи <code>ток минимум максимум</code>\nПример: <code>11.5 0 1.6</code>", "signals"),
    "value_to_ma": ("value_to_ma", "Введи <code>значение минимум максимум</code>\nПример: <code>0.75 0 1.6</code>", "signals"),
    "v_to_percent": ("v_to_percent", "Введи напряжение 0–10 В, например <code>6.2</code>", "signals"),
    "ma05_to_percent": ("ma05_to_percent", "Введи ток 0–5 мА, например <code>2.5</code>", "signals"),
    "calc_u": ("calc_u", "Введи <code>I R</code> (А и Ом). Пример: <code>0.5 220</code>", "electric"),
    "calc_i": ("calc_i", "Введи <code>U R</code>. Пример: <code>24 120</code>", "electric"),
    "calc_r": ("calc_r", "Введи <code>U I</code>. Пример: <code>24 0.02</code>", "electric"),
    "calc_p": ("calc_p", "Введи <code>U I</code>. Пример: <code>220 2.5</code>", "electric"),
    "series_r": ("series_r", "Введи сопротивления через пробел. Пример: <code>100 220 330</code>", "electric"),
    "parallel_r": ("parallel_r", "Введи сопротивления через пробел. Пример: <code>100 220</code>", "electric"),
    "divider": ("divider", "Введи <code>Vin R1 R2</code>. Пример: <code>24 1000 1000</code>", "electric"),
    "pt100_r_to_t": ("pt100_r_to_t", "Введи сопротивление Pt100 в Ом, например <code>138.5</code>", "temperature"),
    "pt100_t_to_r": ("pt100_t_to_r", "Введи температуру °C, например <code>100</code>", "temperature"),
    "res_value": ("res_value", "Введи сопротивление в Ом. Пример: <code>4700</code>", "resistors"),
}


@dp.callback_query(F.data.in_(list(MODE_MAP.keys())))
async def generic_mode(callback: CallbackQuery):
    mode, prompt, parent = MODE_MAP[callback.data]
    await activate_mode(callback, mode, prompt, parent)


@dp.callback_query(F.data == "signal_info")
async def signal_info(callback: CallbackQuery):
    text = (
        "📚 <b>Сигналы КИП</b>\n\n"
        "• 4–20 мА: 4 мА = 0%, 20 мА = 100%.\n"
        "• 4 мА позволяет отличить рабочий ноль от обрыва.\n"
        "• 0–5 мА — старый унифицированный токовый сигнал.\n"
        "• 0–10 В удобен, но сильнее зависит от падения напряжения и помех.\n"
        "• Для длинных линий обычно удобнее токовая петля."
    )
    await callback.message.edit_text(text, reply_markup=back("signals"), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "thermocouples")
async def thermocouples(callback: CallbackQuery):
    text = (
        "🌡 <b>Термопары — кратко</b>\n\n"
        "• K (ХА, хромель-алюмель) — распространённая.\n"
        "• L (ХК, хромель-копель) — часто встречается в СНГ.\n"
        "• Термопара выдаёт милливольты, зависящие от разности температур.\n"
        "• Для точной проверки нужна таблица ЭДС конкретного типа и компенсация холодного спая."
    )
    await callback.message.edit_text(text, reply_markup=back("temperature"), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "pt100_check")
async def pt100_check(callback: CallbackQuery):
    text = (
        "🔧 <b>Как проверить Pt100</b>\n\n"
        "1. Обесточь цепь и отсоедини датчик.\n"
        "2. Измерь сопротивление.\n"
        "3. Ориентир: ~100 Ω при 0°C, ~138.5 Ω при 100°C.\n"
        "4. Бесконечность — вероятен обрыв; почти 0 Ω — вероятно КЗ.\n"
        "5. Для точной диагностики сверяйся со схемой и таблицей Pt100."
    )
    await callback.message.edit_text(text, reply_markup=back("temperature"), parse_mode="HTML")
    await callback.answer()


SENSOR_TEXTS = {
    "sensor_pressure": "🎛 <b>Датчик давления</b>\n\nПроверка: питание → ток петли → реальное давление → импульсные линии → проводка → вход контроллера.",
    "sensor_temp": "🌡 <b>Датчик температуры</b>\n\nПроверка: чувствительный элемент → сопротивление/мВ → преобразователь → питание → выход 4–20 мА.",
    "sensor_level": "📏 <b>Датчик уровня</b>\n\nТипы: гидростатический, радарный, ультразвуковой. Проверяй питание, реальный уровень, монтаж, загрязнение/пену и выходной сигнал.",
    "sensor_flow": "💨 <b>Датчик расхода</b>\n\nПроверяй наличие потока, заполненность трубы, направление, питание, первичный элемент и выходной сигнал.",
}


@dp.callback_query(F.data.in_(list(SENSOR_TEXTS.keys())))
async def sensor_info(callback: CallbackQuery):
    await callback.message.edit_text(SENSOR_TEXTS[callback.data], reply_markup=back("sensors"), parse_mode="HTML")
    await callback.answer()


DIAG_TEXTS = {
    "diag_0": "🔧 <b>0 мА</b>\n\n1. Проверь питание.\n2. Проверь предохранитель/автомат.\n3. Ищи обрыв и плохие клеммы.\n4. Проверь полярность.\n5. Измерь напряжение на датчике и ток последовательно.",
    "diag_low": "🔧 <b><4 мА</b>\n\nВозможны: аварийный ток, недопитание, плохой контакт, слишком большое сопротивление петли, неисправность преобразователя.",
    "diag_4": "🔧 <b>≈4 мА</b>\n\nЭто может быть реальный 0%. Если параметр не нулевой — проверь первичный элемент, импульсные линии и настройку диапазона.",
    "diag_20": "🔧 <b>≈20 мА</b>\n\nЭто может быть 100% диапазона. Если реальное значение ниже — проверь диапазон, калибровку и первичный элемент.",
    "diag_high": "🔧 <b>>20 мА</b>\n\nЧасто это выход за диапазон или аварийный ток. Точный смысл зависит от модели прибора — смотри паспорт.",
    "diag_jump": "🔧 <b>Показания скачут</b>\n\nПроверь клеммы, экран, заземление, питание, помехи, вибрацию, пульсации процесса и плохие контакты.",
}


@dp.callback_query(F.data.in_(list(DIAG_TEXTS.keys())))
async def diag_info(callback: CallbackQuery):
    await callback.message.edit_text(DIAG_TEXTS[callback.data], reply_markup=back("diagnostics"), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "res_info")
async def res_info(callback: CallbackQuery):
    text = (
        "🎨 <b>Цвета цифр</b>\n\n"
        "⚫ 0  🟤 1  🔴 2  🟠 3  🟡 4\n"
        "🟢 5  🔵 6  🟣 7  ⚪ 8  ⬜ 9\n\n"
        "4 полосы: две цифры → множитель → допуск."
    )
    await callback.message.edit_text(text, reply_markup=back("resistors"), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "res_color")
async def res_color(callback: CallbackQuery):
    uid = callback.from_user.id
    user_data[uid] = {}
    rows = [[b(v[0], f"rc1:{k}")] for k, v in COLORS.items()]
    rows.append([b("⬅️ Назад", "resistors")])
    await callback.message.edit_text("Выбери <b>1-ю полосу</b>:", reply_markup=kb(rows), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("rc1:"))
async def rc1(callback: CallbackQuery):
    uid = callback.from_user.id
    c = callback.data.split(":")[1]
    user_data.setdefault(uid, {})["d1"] = COLORS[c][1]
    rows = [[b(v[0], f"rc2:{k}")] for k, v in COLORS.items()]
    await callback.message.edit_text("Выбери <b>2-ю полосу</b>:", reply_markup=kb(rows), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("rc2:"))
async def rc2(callback: CallbackQuery):
    uid = callback.from_user.id
    c = callback.data.split(":")[1]
    user_data.setdefault(uid, {})["d2"] = COLORS[c][1]
    rows = [[b(v[0], f"rcm:{k}")] for k, v in COLORS.items()]
    await callback.message.edit_text("Выбери <b>множитель</b>:", reply_markup=kb(rows), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("rcm:"))
async def rcm(callback: CallbackQuery):
    uid = callback.from_user.id
    c = callback.data.split(":")[1]
    d = user_data.get(uid, {})
    value = (d.get("d1", 0) * 10 + d.get("d2", 0)) * (10 ** COLORS[c][1])
    await callback.message.edit_text(
        f"🎨 <b>{format_resistance(value)}</b>\n\n4-я полоса: золото ±5%, серебро ±10%.",
        reply_markup=back("resistors"),
        parse_mode="HTML"
    )
    await callback.answer()


SCHEME_TEXTS = {
    "scheme_contacts": "📐 <b>Контакты</b>\n\nNO — нормально открытый.\nNC — нормально закрытый.\nCOM — общий.",
    "scheme_relay": "📐 <b>Реле</b>\n\nКатушка часто A1/A2. При подаче питания состояние контактов меняется.",
    "scheme_power": "📐 <b>Питание</b>\n\nL — фаза, N — нейтраль, PE — защитное заземление. DC: часто +24V и 0V.",
    "scheme_2wire": "📐 <b>2-проводный датчик</b>\n\nПитание и сигнал идут по двум проводам. Датчик включается последовательно в токовую петлю.",
    "scheme_3wire": "📐 <b>3-проводный датчик</b>\n\nОбычно + питания, 0V и сигнал. Распиновку всегда сверяй по схеме конкретного прибора.",
}


@dp.callback_query(F.data.in_(list(SCHEME_TEXTS.keys())))
async def scheme_info(callback: CallbackQuery):
    await callback.message.edit_text(SCHEME_TEXTS[callback.data], reply_markup=back("schemes"), parse_mode="HTML")
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
        text = f"🧠 <b>Тест завершён</b>\n\nРезультат: <b>{st['score']}/{len(st['order'])}</b>"
        if edit:
            await message.edit_text(text, reply_markup=back("menu"), parse_mode="HTML")
        else:
            await message.answer(text, reply_markup=back("menu"), parse_mode="HTML")
        return

    qidx = st["order"][st["n"]]
    q, answers, correct = QUIZ[qidx]
    rows = [[b(a, f"qa:{i}:{qidx}")] for i, a in enumerate(answers)]
    rows.append([b("⬅️ Завершить", "menu")])
    text = f"🧠 <b>Вопрос {st['n']+1}/{len(st['order'])}</b>\n\n{q}"

    if edit:
        await message.edit_text(text, reply_markup=kb(rows), parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=kb(rows), parse_mode="HTML")


@dp.callback_query(F.data.startswith("qa:"))
async def quiz_answer(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in quiz_state:
        await callback.answer("Тест уже завершён")
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
    if OPENAI_API_KEY:
        text = "🤖 <b>ИИ-КИПовец</b>\n\nНапиши вопрос обычным текстом."
    else:
        text = "🤖 <b>ИИ-КИПовец</b>\n\nЧтобы включить ИИ, добавь <code>OPENAI_API_KEY</code> в Render. Остальные функции работают без него."
    await callback.message.edit_text(text, reply_markup=back("menu"), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "vision")
async def vision_mode(callback: CallbackQuery):
    uid = callback.from_user.id
    user_modes[uid] = "vision"
    if OPENAI_API_KEY:
        text = "📷 <b>Что за прибор?</b>\n\nОтправь фотографию прибора."
    else:
        text = "📷 <b>Распознавание прибора</b>\n\nДля анализа фото добавь <code>OPENAI_API_KEY</code> в Render."
    await callback.message.edit_text(text, reply_markup=back("menu"), parse_mode="HTML")
    await callback.answer()


def format_resistance(v):
    if v >= 1_000_000:
        return f"{v/1_000_000:g} МОм"
    if v >= 1000:
        return f"{v/1000:g} кОм"
    return f"{v:g} Ом"


def resistor_to_colors(value):
    if value <= 0:
        raise ValueError

    n = float(value)
    exp = 0
    while n >= 100 and exp < 9:
        n /= 10
        exp += 1

    digits = int(round(n))
    if digits >= 100:
        digits //= 10
        exp += 1

    d1, d2 = digits // 10, digits % 10
    rev = {v[1]: v[0] for v in COLORS.values()}
    if d1 not in rev or d2 not in rev or exp not in rev:
        raise ValueError
    return rev[d1], rev[d2], rev[exp]


async def ai_text(prompt):
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    resp = await client.responses.create(
        model=AI_MODEL,
        input=(
            "Ты помощник слесаря КИПиА. Отвечай по-русски, практично и кратко. "
            "Не выдумывай характеристики конкретного прибора без шильдика или документации. "
            "Если речь о работе под напряжением, напоминай о безопасном отключении и допуске.\n\n"
            f"Вопрос: {prompt}"
        )
    )
    return resp.output_text


async def ai_photo(file_bytes, caption=""):
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    b64 = base64.b64encode(file_bytes).decode("ascii")

    resp = await client.responses.create(
        model=AI_MODEL,
        input=[{
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        "Определи прибор КИП/электрики на фото. "
                        "Опиши назначение, что читается на шильдике и как обычно его проверяют. "
                        "Если модель не читается — не выдумывай. "
                        f"Комментарий пользователя: {caption}"
                    )
                },
                {
                    "type": "input_image",
                    "image_url": f"data:image/jpeg;base64,{b64}"
                }
            ]
        }]
    )
    return resp.output_text


@dp.message(F.photo)
async def photo_handler(message: Message):
    uid = message.from_user.id

    if user_modes.get(uid) != "vision":
        await message.answer("Для анализа фото открой раздел «📷 Что за прибор?»")
        return

    if not OPENAI_API_KEY:
        await message.answer("Нужно добавить OPENAI_API_KEY в Render.")
        return

    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        bio = await bot.download_file(file.file_path)
        data = bio.read()
        await message.answer("🔎 Анализирую фото…")
        answer = await ai_photo(data, message.caption or "")
        await message.answer(answer, reply_markup=back("menu"))
    except Exception as e:
        await message.answer(f"Не удалось проанализировать фото: {type(e).__name__}", reply_markup=back("menu"))


@dp.message()
async def handle_text(message: Message):
    uid = message.from_user.id
    mode = user_modes.get(uid)
    raw = (message.text or "").replace(",", ".").strip()

    if mode == "ai":
        if not OPENAI_API_KEY:
            await message.answer("Добавь OPENAI_API_KEY в Render, чтобы включить ИИ.")
            return
        try:
            await message.answer("🤖 Думаю…")
            answer = await ai_text(raw)
            await message.answer(answer, reply_markup=back("menu"))
        except Exception as e:
            await message.answer(f"Ошибка ИИ: {type(e).__name__}")
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
            text = f"📈 <b>{p:g}% = {4 + p/100*16:.3f} мА</b>"

        elif mode == "ma_to_value":
            ma, vmin, vmax = nums
            frac = (ma - 4) / 16
            val = vmin + frac * (vmax - vmin)
            text = f"📈 <b>{ma:g} мА = {frac*100:.2f}% = {val:.4g}</b>"

        elif mode == "value_to_ma":
            val, vmin, vmax = nums
            frac = (val - vmin) / (vmax - vmin)
            ma = 4 + frac * 16
            text = f"📈 <b>{val:g} = {frac*100:.2f}% = {ma:.3f} мА</b>"

        elif mode == "v_to_percent":
            v = nums[0]
            text = f"📈 <b>{v:g} В = {v/10*100:.2f}%</b>"

        elif mode == "ma05_to_percent":
            ma = nums[0]
            text = f"📈 <b>{ma:g} мА = {ma/5*100:.2f}%</b>"

        elif mode == "calc_u":
            i, r = nums
            text = f"⚡ <b>U = {i*r:.4g} В</b>"

        elif mode == "calc_i":
            u, r = nums
            text = f"⚡ <b>I = {u/r:.6g} А</b>"

        elif mode == "calc_r":
            u, i = nums
            text = f"⚡ <b>R = {format_resistance(u/i)}</b>"

        elif mode == "calc_p":
            u, i = nums
            text = f"🔌 <b>P = {u*i:.4g} Вт</b>"

        elif mode == "series_r":
            text = f"📐 <b>RΣ = {format_resistance(sum(nums))}</b>"

        elif mode == "parallel_r":
            if any(x == 0 for x in nums):
                raise ValueError
            total = 1 / sum(1/x for x in nums)
            text = f"📐 <b>Rэкв = {format_resistance(total)}</b>"

        elif mode == "divider":
            vin, r1, r2 = nums
            text = f"📐 <b>Vout = {vin*r2/(r1+r2):.4g} В</b>"

        elif mode == "pt100_r_to_t":
            r = nums[0]
            t = (r / 100 - 1) / 0.00385
            text = f"🌡 <b>≈ {t:.1f} °C</b>\n\nПриближённо, для точной калибровки используй таблицу Pt100."

        elif mode == "pt100_t_to_r":
            t = nums[0]
            r = 100 * (1 + 0.00385 * t)
            text = f"🌡 <b>≈ {r:.2f} Ω</b>\n\nПриближённый расчёт."

        elif mode == "res_value":
            val = nums[0]
            c1, c2, cm = resistor_to_colors(val)
            text = f"🎨 <b>{format_resistance(val)}</b>\n\n{c1} → {c2} → {cm}\n4-я полоса: золото ±5%."

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
    return {"status": "ok", "bot": "KIP Helper PRO"}


@app.post("/webhook")
async def webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}