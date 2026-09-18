from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

CATEGORIES = ("Одежда", "Детские вещи", "Дом(ремонт/быт)", "Другое")
CATEGORY_ALL = "Все"

BTN_CATEGORIES = "Категории"
BTN_CREATE = "Подать объявление"
BTN_BACK = "Назад"
BTN_SELL = "Продать"
BTN_BUY = "Купить"
BTN_DONE = "Готово"
BTN_SKIP_PHOTOS = "Без фото"
BTN_RESERVE = "Забронировать"
BTN_RELEASE_RESERVE = "Снять Бронь"
BTN_REMOVE_AD = "Снять объявление"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CATEGORIES), KeyboardButton(text=BTN_CREATE)],
            [KeyboardButton(text=BTN_RESERVE), KeyboardButton(text=BTN_RELEASE_RESERVE)],
            [KeyboardButton(text=BTN_REMOVE_AD)],
        ],
        resize_keyboard=True,
    )


def categories_menu(include_all: bool = True, placeholder: str | None = None) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=CATEGORIES[0]), KeyboardButton(text=CATEGORIES[1])]]
    rows.append([KeyboardButton(text=CATEGORIES[2]), KeyboardButton(text=CATEGORIES[3])])
    if include_all:
        rows.append([KeyboardButton(text=CATEGORY_ALL), KeyboardButton(text=BTN_BACK)])
    else:
        rows.append([KeyboardButton(text=BTN_BACK)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, input_field_placeholder=placeholder)


def create_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_SELL), KeyboardButton(text=BTN_BUY)], [KeyboardButton(text=BTN_BACK)]],
        resize_keyboard=True,
    )


def photo_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_DONE), KeyboardButton(text=BTN_SKIP_PHOTOS)], [KeyboardButton(text=BTN_BACK)]],
        resize_keyboard=True,
    )


def remove_reason_keyboard(ad_id: int, ad_type: str) -> InlineKeyboardMarkup:
    if ad_type == "sell":
        reasons = ("Куплено", "Обменяно", "Другое")
    else:
        reasons = ("Куплено", "Обменяно", "Не актуально")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=reason, callback_data=f"remove_reason:{ad_id}:{reason}")]
            for reason in reasons
        ]
    )
