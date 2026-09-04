import os
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

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

user_modes: dict[int, str] = {}


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 4–20 мА", callback_data="ma_menu")],
        [InlineKeyboardButton(text="⚡ Закон Ома", callback_data="ohm")],
        [InlineKeyboardButton(text="🔌 Мощность", callback_data="power")],
        [InlineKeyboardButton(text="🎨 Резисторы", callback_data="resistors")],
        [InlineKeyboardButton(text="🔧 Мультиметр", callback_data="multimeter")],
        [InlineKeyboardButton(text="📚 Шпаргалка КИПиА", callback_data="cheatsheet")],
    ])


def back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]
    ])


def ma_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="мА → %", callback_data="ma_to_percent")],
        [InlineKeyboardButton(text="% → мА", callback_data="percent_to_ma")],
        [InlineKeyboardButton(text="мА → значение прибора", callback_data="ma_to_value")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")],
    ])


@dp.message(CommandStart())
async def start(message: Message):
    user_modes.pop(message.from_user.id, None)
    await message.answer(
        "⚙️ <b>КИП Помощник</b>\n\nВыбери, что нужно:",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "menu")
async def menu(callback: CallbackQuery):
    user_modes.pop(callback.from_user.id, None)
    await callback.message.edit_text(
        "⚙️ <b>КИП Помощник</b>\n\nВыбери, что нужно:",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(F.data == "ma_menu")
async def open_ma(callback: CallbackQuery):
    await callback.message.edit_text(
        "📈 <b>4–20 мА</b>\n\nВыбери расчёт:",
        reply_markup=ma_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(F.data == "ma_to_percent")
async def ma_to_percent_mode(callback: CallbackQuery):
    user_modes[callback.from_user.id] = "ma_to_percent"
    await callback.message.edit_text(
        "Введи ток в мА, например: <code>11.5</code>",
        reply_markup=back_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(F.data == "percent_to_ma")
async def percent_to_ma_mode(callback: CallbackQuery):
    user_modes[callback.from_user.id] = "percent_to_ma"
    await callback.message.edit_text(
        "Введи процент от 0 до 100, например: <code>50</code>",
        reply_markup=back_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(F.data == "ma_to_value")
async def ma_to_value_mode(callback: CallbackQuery):
    user_modes[callback.from_user.id] = "ma_to_value"
    await callback.message.edit_text(
        "Введи через пробел:\n"
        "<code>ток минимум максимум</code>\n\n"
        "Например для датчика 0–1.6 МПа при 11.5 мА:\n"
        "<code>11.5 0 1.6</code>",
        reply_markup=back_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(F.data == "ohm")
async def ohm(callback: CallbackQuery):
    text = (
        "⚡ <b>Закон Ома</b>\n\n"
        "U = I × R\n"
        "I = U / R\n"
        "R = U / I\n\n"
        "U — напряжение, В\n"
        "I — ток, А\n"
        "R — сопротивление, Ом"
    )
    await callback.message.edit_text(text, reply_markup=back_menu(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "power")
async def power(callback: CallbackQuery):
    text = (
        "🔌 <b>Мощность</b>\n\n"
        "P = U × I\n"
        "I = P / U\n"
        "U = P / I\n\n"
        "P — Вт, U — В, I — А"
    )
    await callback.message.edit_text(text, reply_markup=back_menu(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "resistors")
async def resistors(callback: CallbackQuery):
    text = (
        "🎨 <b>Цвета резисторов</b>\n\n"
        "Чёрный — 0\n"
        "Коричневый — 1\n"
        "Красный — 2\n"
        "Оранжевый — 3\n"
        "Жёлтый — 4\n"
        "Зелёный — 5\n"
        "Синий — 6\n"
        "Фиолетовый — 7\n"
        "Серый — 8\n"
        "Белый — 9\n\n"
        "Золото: ±5%\n"
        "Серебро: ±10%"
    )
    await callback.message.edit_text(text, reply_markup=back_menu(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "multimeter")
async def multimeter(callback: CallbackQuery):
    text = (
        "🔧 <b>Мультиметр — кратко</b>\n\n"
        "V⎓ — постоянное напряжение\n"
        "V~ — переменное напряжение\n"
        "Ω — сопротивление\n"
        "A/mA — ток\n"
        "🔔 — прозвонка\n\n"
        "⚠️ Напряжение измеряют параллельно, ток — последовательно."
    )
    await callback.message.edit_text(text, reply_markup=back_menu(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "cheatsheet")
async def cheatsheet(callback: CallbackQuery):
    text = (
        "📚 <b>Шпаргалка КИПиА</b>\n\n"
        "4 мА = 0%\n"
        "12 мА = 50%\n"
        "20 мА = 100%\n\n"
        "NO — нормально открытый контакт\n"
        "NC — нормально закрытый контакт\n"
        "0–5 мА — унифицированный токовый сигнал старого типа\n"
        "4–20 мА — распространённый промышленный токовый сигнал"
    )
    await callback.message.edit_text(text, reply_markup=back_menu(), parse_mode="HTML")
    await callback.answer()


@dp.message()
async def calculations(message: Message):
    mode = user_modes.get(message.from_user.id)
    if not mode:
        await message.answer("Нажми /start и выбери нужный раздел.")
        return

    raw = (message.text or "").replace(",", ".").strip()

    try:
        if mode == "ma_to_percent":
            ma = float(raw)
            percent = (ma - 4) / 16 * 100
            await message.answer(
                f"📈 {ma:g} мА = <b>{percent:.1f}%</b>",
                parse_mode="HTML",
                reply_markup=ma_menu(),
            )

        elif mode == "percent_to_ma":
            percent = float(raw)
            ma = 4 + (percent / 100) * 16
            await message.answer(
                f"📈 {percent:g}% = <b>{ma:.2f} мА</b>",
                parse_mode="HTML",
                reply_markup=ma_menu(),
            )

        elif mode == "ma_to_value":
            parts = raw.split()
            if len(parts) != 3:
                raise ValueError

            ma, vmin, vmax = map(float, parts)
            fraction = (ma - 4) / 16
            percent = fraction * 100
            value = vmin + fraction * (vmax - vmin)

            await message.answer(
                f"📈 Ток: <b>{ma:g} мА</b>\n"
                f"Диапазон: <b>{vmin:g} … {vmax:g}</b>\n\n"
                f"Процент: <b>{percent:.1f}%</b>\n"
                f"Значение: <b>{value:.3f}</b>",
                parse_mode="HTML",
                reply_markup=ma_menu(),
            )

    except ValueError:
        await message.answer(
            "Не понял число. Попробуй ещё раз в указанном формате.",
            reply_markup=back_menu(),
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    if BASE_URL:
        await bot.set_webhook(
            url=f"{BASE_URL}/webhook",
            secret_token=WEBHOOK_SECRET,
            drop_pending_updates=True,
        )
    yield
    await bot.session.close()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def health():
    return {"status": "ok", "bot": "KIP Helper"}


@app.post("/webhook")
async def webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}