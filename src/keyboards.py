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


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CATEGORIES), KeyboardButton(text=BTN_CREATE)],
        ],
        resize_keyboard=True,
    )


def categories_menu(include_all: bool = True) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=CATEGORIES[0]), KeyboardButton(text=CATEGORIES[1])]]
    rows.append([KeyboardButton(text=CATEGORIES[2]), KeyboardButton(text=CATEGORIES[3])])
    if include_all:
        rows.append([KeyboardButton(text=CATEGORY_ALL), KeyboardButton(text=BTN_BACK)])
    else:
        rows.append([KeyboardButton(text=BTN_BACK)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


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


def ad_keyboard(
    ad_id: int,
    is_author: bool,
    is_reserved: bool,
    photo_count: int = 0,
    photo_index: int = 0,
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    if photo_count > 1:
        prev_index = (photo_index - 1) % photo_count
        next_index = (photo_index + 1) % photo_count
        buttons.append(
            [
                InlineKeyboardButton(text="<-", callback_data=f"photo:{ad_id}:{prev_index}"),
                InlineKeyboardButton(text=f"{photo_index + 1}/{photo_count}", callback_data=f"photo_noop:{ad_id}"),
                InlineKeyboardButton(text="->", callback_data=f"photo:{ad_id}:{next_index}"),
            ]
        )
    if is_author:
        if is_reserved:
            buttons.append([InlineKeyboardButton(text="Снять бронь", callback_data=f"reserve_release:{ad_id}")])
        buttons.append([InlineKeyboardButton(text="Удалить", callback_data=f"remove_start:{ad_id}")])
    else:
        buttons.append([InlineKeyboardButton(text="Бронь", callback_data=f"reserve_start:{ad_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_reserve_keyboard(ad_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data=f"reserve_yes:{ad_id}"),
                InlineKeyboardButton(text="Нет", callback_data=f"reserve_no:{ad_id}"),
            ]
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
