"""Бот записи для салона/барбершопа: услуги, цены, заявка, уведомление админу.

Запуск:
    python bot.py

Перед запуском заполните .env (VK_TOKEN, ADMIN_ID) — см. README.
"""

import json
import os
import re
import time
from pathlib import Path

from vkbottle import Keyboard, KeyboardButtonColor, Text
from vkbottle.bot import Bot, Message


def _load_env():
    # Токен удобнее держать рядом с ботом, чем в переменных системы.
    path = Path(__file__).with_name(".env")
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
    except OSError:
        pass


_load_env()

TOKEN = os.environ.get("VK_TOKEN", "").strip()
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0") or 0)
DATA_FILE = Path(__file__).with_name("bookings.json")

SALON_NAME = os.environ.get("SALON_NAME", "Салон красоты")
SALON_CONTACTS = os.environ.get(
    "SALON_CONTACTS",
    "Адрес: ул. Примерная, 1\nТелефон: +7 900 000-00-00\nРаботаем ежедневно 10:00–21:00",
)

SERVICES = {
    "Стрижка": "1 500 ₽ · 40 мин",
    "Стрижка + борода": "2 200 ₽ · 60 мин",
    "Борода": "900 ₽ · 25 мин",
    "Окрашивание": "4 500 ₽ · 120 мин",
}

bot = Bot(TOKEN)
# peer_id -> {"step": ..., "name": ..., "phone": ..., "service": ...}
pending = {}


def load_bookings():
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def save_booking(entry):
    rows = load_bookings()
    rows.append(entry)
    DATA_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def main_keyboard():
    kb = Keyboard(one_time=False, inline=False)
    kb.add(Text("Записаться"), color=KeyboardButtonColor.PRIMARY)
    kb.row()
    kb.add(Text("Услуги и цены"))
    kb.row()
    kb.add(Text("Контакты"))
    return kb


def services_keyboard():
    kb = Keyboard(one_time=True, inline=False)
    for name in SERVICES:
        kb.add(Text(name))
        kb.row()
    kb.add(Text("Назад"))
    return kb


@bot.on.message(text=["Начать", "начать", "Привет", "привет", "/start"])
async def hello(message: Message):
    pending.pop(message.peer_id, None)
    await message.answer(
        f"Здравствуйте! Это {SALON_NAME}.\n"
        "Записаться можно за минуту — выберите, что нужно.",
        keyboard=main_keyboard(),
    )


@bot.on.message(text=["Услуги и цены", "Услуги", "Цены"])
async def prices(message: Message):
    lines = [f"• {name} — {info}" for name, info in SERVICES.items()]
    await message.answer("Услуги и цены:\n" + "\n".join(lines), keyboard=main_keyboard())


@bot.on.message(text=["Контакты"])
async def contacts(message: Message):
    await message.answer(SALON_CONTACTS, keyboard=main_keyboard())


@bot.on.message(text=["Назад"])
async def back(message: Message):
    pending.pop(message.peer_id, None)
    await message.answer("Что вас интересует?", keyboard=main_keyboard())


@bot.on.message(text=["Записаться"])
async def book_start(message: Message):
    pending[message.peer_id] = {"step": "service"}
    await message.answer("Что будем делать?", keyboard=services_keyboard())


@bot.on.message()
async def fallback(message: Message):
    state = pending.get(message.peer_id)
    text = (message.text or "").strip()

    if state is None:
        await message.answer("Выберите пункт меню.", keyboard=main_keyboard())
        return

    if state["step"] == "service":
        if text not in SERVICES:
            await message.answer("Выберите услугу кнопкой ниже.", keyboard=services_keyboard())
            return
        state.update(step="name", service=text)
        await message.answer(f"{text} — записал. Как вас зовут?")
        return

    if state["step"] == "name":
        if len(text) < 2:
            await message.answer("Напишите имя, пожалуйста.")
            return
        state.update(step="phone", name=text[:60])
        await message.answer(
            "Оставьте номер телефона для связи.\n\n"
            "Отправляя номер, вы соглашаетесь на обработку персональных данных "
            "для записи и связи по ней (152-ФЗ). Данные не передаются третьим лицам."
        )
        return

    if state["step"] == "phone":
        digits = re.sub(r"\D", "", text)
        if len(digits) < 10:
            await message.answer("Похоже, в номере ошибка. Напишите в формате +7 900 000-00-00.")
            return
        # Согласие получено до записи — фиксируем его в самой заявке.
        entry = {
            "ts": int(time.time()),
            "user_id": message.from_id,
            "name": state["name"],
            "phone": text[:30],
            "service": state["service"],
            "consent_152fz": True,
        }
        save_booking(entry)
        pending.pop(message.peer_id, None)
        await message.answer(
            f"Записал: {entry['service']}\n"
            f"Имя: {entry['name']}\nТелефон: {entry['phone']}\n\n"
            "Администратор свяжется, чтобы подтвердить время.",
            keyboard=main_keyboard(),
        )
        if ADMIN_ID:
            try:
                await bot.api.messages.send(
                    user_id=ADMIN_ID,
                    random_id=int(time.time() * 1000),
                    message=(
                        f"Новая заявка\n{entry['service']}\n"
                        f"{entry['name']}, {entry['phone']}\n"
                        f"vk.com/id{entry['user_id']}"
                    ),
                )
            except Exception:
                pass
        return


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Не задан VK_TOKEN — заполните .env")
    bot.run_forever()
