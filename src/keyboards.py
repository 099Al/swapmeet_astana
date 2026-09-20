from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

CATEGORIES = ("Дом(быт/ремонт)", "Другое", "Одежда", "Животные", "Книги", "Детские")
CATEGORY_ALL = "Все"

BTN_CREATE = "Разместить объявление"
BTN_BACK = "Назад"
BTN_SELL = "Продать"
BTN_BUY = "Купить"
BTN_SKIP_PHOTOS = "Перейти к описанию без фото"
BTN_RESERVE = "Забронировать"
BTN_RELEASE_RESERVE = "Снять Бронь"
BTN_REMOVE_AD = "Снять объявление"
BTN_EDIT_AD = "Редактировать"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CREATE)],
            [KeyboardButton(text=BTN_REMOVE_AD)],
            [KeyboardButton(text=BTN_EDIT_AD)],
        ],
        resize_keyboard=True,
    )


def categories_menu(include_all: bool = True, placeholder: str | None = None) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=CATEGORIES[index]), KeyboardButton(text=CATEGORIES[index + 1])]
        for index in range(0, len(CATEGORIES), 2)
    ]
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
        rows.append([InlineKeyboardButton(text="Перейти к описанию", callback_data="sell_photos:description")])
    else:
        rows.append([InlineKeyboardButton(text=BTN_SKIP_PHOTOS, callback_data="sell_photos:skip")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sell_categories_inline_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=category, callback_data=f"sell_category:{category}")]
            for category in CATEGORIES
        ]
        + [[InlineKeyboardButton(text=BTN_BACK, callback_data="sell_back:create")]]
    )


def wizard_back_keyboard(target: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=BTN_BACK, callback_data=f"sell_back:{target}")]]
    )


def sell_confirm_keyboard(callback_prefix: str = "sell_confirm") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подтвердить", callback_data=f"{callback_prefix}:yes")],
            [InlineKeyboardButton(text="Отменить", callback_data=f"{callback_prefix}:reset")],
        ]
    )


def edit_next_finish_keyboard(next_target: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Далее", callback_data=f"edit_next:{next_target}")],
            [InlineKeyboardButton(text="Завершить", callback_data="edit_finish")],
        ]
    )


def edit_finish_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Завершить", callback_data="edit_finish")]]
    )


def edit_photo_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Удалить", callback_data="edit_photo:delete")],
            [InlineKeyboardButton(text="Добавить фото", callback_data="edit_photo:add")],
            [InlineKeyboardButton(text="Далее", callback_data="edit_next:price")],
            [InlineKeyboardButton(text="Завершить", callback_data="edit_finish")],
        ]
    )


def edit_photo_delete_keyboard(photo_count: int, selected: set[int]) -> InlineKeyboardMarkup:
    rows = []
    for index in range(photo_count):
        mark = "☑" if index in selected else "☐"
        rows.append([InlineKeyboardButton(text=f"{mark} {index + 1}", callback_data=f"edit_photo_toggle:{index}")])
    rows.append([InlineKeyboardButton(text="Удалить выбранные", callback_data="edit_photo_apply_delete")])
    rows.append([InlineKeyboardButton(text=BTN_BACK, callback_data="edit_photo:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
