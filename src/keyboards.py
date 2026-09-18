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


def inline_categories_menu() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=category, callback_data=f"category:{category}")] for category in CATEGORIES]
    rows.append([InlineKeyboardButton(text=CATEGORY_ALL, callback_data="category:all")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def create_inline_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=BTN_SELL, callback_data="create:sell")],
            [InlineKeyboardButton(text=BTN_BUY, callback_data="create:buy")],
        ]
    )


def sell_photo_inline_menu(has_photos: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if has_photos:
        rows.append([InlineKeyboardButton(text="Добавить описание", callback_data="sell_photos:description")])
    else:
        rows.append([InlineKeyboardButton(text=BTN_SKIP_PHOTOS, callback_data="sell_photos:skip")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sell_categories_inline_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=category, callback_data=f"sell_category:{category}")]
            for category in CATEGORIES
        ]
        + [[InlineKeyboardButton(text=BTN_BACK, callback_data="sell_back:photos")]]
    )


def wizard_back_keyboard(target: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=BTN_BACK, callback_data=f"sell_back:{target}")]]
    )


def sell_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подтвердить", callback_data="sell_confirm:yes")],
            [InlineKeyboardButton(text="Сбросить", callback_data="sell_confirm:reset")],
        ]
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
