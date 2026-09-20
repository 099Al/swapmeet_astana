from __future__ import annotations

import asyncio
import html
import logging
from dataclasses import dataclass
from typing import Union

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, CallbackQuery, InputMediaPhoto, Message
from aiogram.utils.markdown import hbold

from config import Settings, load_settings
from db import Ad, Database
from images import dhash
from keyboards import (
    BTN_BACK,
    BTN_BUY,
    BTN_CREATE,
    BTN_EDIT_AD,
    BTN_RELEASE_RESERVE,
    BTN_REMOVE_AD,
    BTN_RESERVE,
    BTN_SELL,
    BTN_SKIP_PHOTOS,
    CATEGORIES,
    CATEGORY_ALL,
    categories_menu,
    create_inline_menu,
    edit_next_finish_keyboard,
    edit_finish_keyboard,
    edit_photo_delete_keyboard,
    edit_photo_menu,
    main_menu,
    remove_reason_keyboard,
    sell_categories_inline_menu,
    sell_confirm_keyboard,
    sell_photo_inline_menu,
    wizard_back_keyboard,
)

MAX_BUY_DESCRIPTION = 500
MAX_SELL_PHOTOS = 6
PUBLIC_NUMBER_OFFSET = 99999
ChatId = Union[int, str]


class CreateAd(StatesGroup):
    buy_description = State()
    buy_category = State()
    buy_photos = State()
    buy_confirm = State()
    sell_category = State()
    sell_description = State()
    sell_price = State()
    sell_address = State()
    sell_photos = State()
    sell_confirm = State()
    reserve_number = State()
    release_reserve_number = State()
    remove_ad_number = State()
    edit_number = State()
    edit_description = State()
    edit_photo_menu = State()
    edit_add_photo = State()
    edit_delete_photo = State()
    edit_price = State()
    edit_address = State()


@dataclass
class AppContext:
    settings: Settings
    db: Database


def build_router(ctx: AppContext) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def start(message: Message, state: FSMContext) -> None:
        await state.clear()
        ctx.db.cleanup_old_ads(ctx.settings.retention_period_days)
        await message.answer("Выберите действие в меню.", reply_markup=main_menu())

    @router.message(F.text == BTN_BACK)
    async def back(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Выберите действие в меню.", reply_markup=main_menu())

    @router.message(F.text.in_((*CATEGORIES, CATEGORY_ALL)))
    async def filter_category(message: Message, state: FSMContext) -> None:
        current_state = await state.get_state()
        if current_state == CreateAd.buy_category.state:
            if message.text not in CATEGORIES:
                await message.answer("Выберите категорию из меню.")
                return
            await state.update_data(category=message.text)
            await ask_buy_photos(message, state)
            return
        if current_state == CreateAd.sell_category.state:
            if message.text not in CATEGORIES:
                await message.answer("Выберите категорию из меню.")
                return
            await state.update_data(category=message.text)
            await ask_sell_photos(message, state)
            return

        await message.answer("Категории используются только при создании объявления.", reply_markup=main_menu())

    @router.message(Command("place", "create", "post"))
    @router.message(F.text == BTN_CREATE)
    async def create(message: Message) -> None:
        await message.answer("Что хотите сделать?", reply_markup=create_inline_menu())

    @router.callback_query(F.data == "create:buy")
    async def buy_start_inline(callback: CallbackQuery, state: FSMContext) -> None:
        if await is_daily_limit_exceeded_callback(callback, ctx, ad_type="buy", limit=ctx.settings.buy_daily_limit):
            await callback.answer("Превышен суточный лимит объявлений на покупку.", show_alert=True)
            return
        if await is_daily_limit_exceeded_callback(callback, ctx, ad_type=None, limit=ctx.settings.user_daily_ad_limit):
            await callback.answer("Превышен суточный лимит объявлений.", show_alert=True)
            return
        await state.set_data({"photos": [], "wizard_message_ids": [], "wizard_user_message_ids": []})
        await state.set_state(CreateAd.buy_category)
        await safe_delete(callback.message)
        await callback.message.answer("Укажите категорию:", reply_markup=categories_menu(include_all=False))
        await callback.answer()

    @router.callback_query(F.data == "create:sell")
    async def sell_start_inline(callback: CallbackQuery, state: FSMContext) -> None:
        if await is_daily_limit_exceeded_callback(callback, ctx, ad_type=None, limit=ctx.settings.user_daily_ad_limit):
            await callback.answer("Превышен суточный лимит объявлений.", show_alert=True)
            return
        await state.set_data({"photos": [], "wizard_message_ids": [], "wizard_user_message_ids": []})
        await ask_sell_category(callback.message, state)
        await callback.answer()

    @router.message(F.text == BTN_BUY)
    async def buy_start(message: Message, state: FSMContext) -> None:
        if await is_daily_limit_exceeded(message, ctx, ad_type="buy", limit=ctx.settings.buy_daily_limit):
            await message.answer("Превышен суточный лимит объявлений на покупку.")
            return
        if await is_daily_limit_exceeded(message, ctx, ad_type=None, limit=ctx.settings.user_daily_ad_limit):
            await message.answer("Превышен суточный лимит объявлений.")
            return
        await state.set_data({"photos": [], "wizard_message_ids": [], "wizard_user_message_ids": []})
        await state.set_state(CreateAd.buy_category)
        await message.answer("Укажите категорию:", reply_markup=categories_menu(include_all=False))

    @router.message(CreateAd.buy_description)
    async def buy_description(message: Message, state: FSMContext) -> None:
        if is_forwarded(message):
            await message.answer("Пересланные объявления внутри бота не допускаются.")
            return
        text = (message.text or "").strip()
        if not text:
            await message.answer("Отправьте описание текстом.")
            return
        if len(text) > MAX_BUY_DESCRIPTION:
            await message.answer("Описание должно быть не больше 500 символов.")
            return
        await state.update_data(description=text)
        await state.set_state(CreateAd.buy_confirm)
        await send_wizard_message(
            message,
            state,
            "Опубликовать?",
            reply_markup=sell_confirm_keyboard(callback_prefix="buy_confirm"),
        )

    @router.message(CreateAd.buy_photos, F.photo)
    async def buy_photo(message: Message, state: FSMContext, bot: Bot) -> None:
        if is_forwarded(message):
            await message.answer("Пересланные объявления внутри бота не допускаются.")
            return
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        stream = await bot.download_file(file.file_path)
        if stream is None:
            await message.answer("Не удалось скачать фото, попробуйте другое.")
            return
        image_hash = dhash(stream.read())
        data = await state.get_data()
        photos: list[tuple[str, str, str]] = data.get("photos", [])
        if len(photos) >= MAX_SELL_PHOTOS:
            await ask_buy_description(message, state)
            return
        photos.append((photo.file_id, photo.file_unique_id, image_hash))
        await remember_wizard_user_message(state, message.message_id)
        await state.update_data(photos=photos)
        if len(photos) >= MAX_SELL_PHOTOS:
            await ask_buy_description(message, state)
            return
        await send_wizard_message(
            message,
            state,
            render_sell_photo_prompt(len(photos)),
            reply_markup=sell_photo_inline_menu(has_photos=True),
        )

    @router.message(CreateAd.buy_photos, F.text == BTN_SKIP_PHOTOS)
    async def finish_buy_photos(message: Message, state: FSMContext) -> None:
        await ask_buy_description(message, state)

    @router.message(F.text == BTN_SELL)
    async def sell_start(message: Message, state: FSMContext) -> None:
        if await is_daily_limit_exceeded(message, ctx, ad_type=None, limit=ctx.settings.user_daily_ad_limit):
            await message.answer("Превышен суточный лимит объявлений.")
            return
        await state.set_data({"photos": [], "wizard_message_ids": [], "wizard_user_message_ids": []})
        await ask_sell_category(message, state)

    @router.message(CreateAd.sell_description)
    async def sell_description(message: Message, state: FSMContext) -> None:
        if is_forwarded(message):
            await message.answer("Пересланные объявления внутри бота не допускаются.")
            return
        text = (message.text or "").strip()
        if not text:
            await message.answer("Отправьте описание текстом.")
            return
        await remember_wizard_user_message(state, message.message_id)
        await state.update_data(description=text)
        await state.set_state(CreateAd.sell_price)
        await send_wizard_message(
            message,
            state,
            "Укажите цену",
            reply_markup=wizard_back_keyboard("description"),
        )

    @router.message(CreateAd.sell_price)
    async def sell_price(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if not text:
            await message.answer("Цена обязательна. Укажите цену, бесплатно или обмен.")
            return
        await remember_wizard_user_message(state, message.message_id)
        await state.update_data(price=text)
        await state.set_state(CreateAd.sell_address)
        await send_wizard_message(
            message,
            state,
            "Укажите Адресс",
            reply_markup=wizard_back_keyboard("price"),
        )

    @router.message(CreateAd.sell_address)
    async def finish_sell(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if not text:
            await message.answer("Адрес обязателен.")
            return
        await remember_wizard_user_message(state, message.message_id)
        await state.update_data(address=text)
        await state.set_state(CreateAd.sell_confirm)
        await send_wizard_message(
            message,
            state,
            "Опубликовать?",
            reply_markup=sell_confirm_keyboard(),
        )

    @router.message(CreateAd.sell_photos, F.photo)
    async def sell_photo(message: Message, state: FSMContext, bot: Bot) -> None:
        if is_forwarded(message):
            await message.answer("Пересланные объявления внутри бота не допускаются.")
            return
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        stream = await bot.download_file(file.file_path)
        if stream is None:
            await message.answer("Не удалось скачать фото, попробуйте другое.")
            return
        image_hash = dhash(stream.read())
        data = await state.get_data()
        photos: list[tuple[str, str, str]] = data.get("photos", [])
        if len(photos) >= MAX_SELL_PHOTOS:
            await ask_sell_description_from_state(message, state)
            return
        photos.append((photo.file_id, photo.file_unique_id, image_hash))
        await remember_wizard_user_message(state, message.message_id)
        await state.update_data(photos=photos)
        if len(photos) >= MAX_SELL_PHOTOS:
            await ask_sell_description_from_state(message, state)
            return
        await send_wizard_message(
            message,
            state,
            render_sell_photo_prompt(len(photos)),
            reply_markup=sell_photo_inline_menu(has_photos=True),
        )

    @router.message(CreateAd.sell_photos, F.text == BTN_SKIP_PHOTOS)
    async def finish_sell_photos(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        photos: list[tuple[str, str, str]] = data.get("photos", [])
        if has_duplicate_in_batch([item[2] for item in photos]):
            await state.clear()
            await message.answer(
                "Создание отклонено: среди загруженных фото есть повтор.",
                reply_markup=main_menu(),
            )
            return
        duplicate_ad_id = ctx.db.find_duplicate_hash(
            message.from_user.id,
            [item[2] for item in photos],
            ctx.settings.duplicate_photo_days,
        )
        if duplicate_ad_id is not None:
            await state.clear()
            await message.answer(
                f"Создание отклонено: похожее фото уже было в объявлении #{duplicate_ad_id} за последние "
                f"{ctx.settings.duplicate_photo_days} дней.",
                reply_markup=main_menu(),
            )
            return
        await ask_sell_description_from_state(message, state)

    @router.callback_query(F.data.startswith("sell_photos:"))
    async def finish_sell_photos_inline(callback: CallbackQuery, state: FSMContext) -> None:
        action = callback.data.split(":", 1)[1]
        current_state = await state.get_state()
        data = await state.get_data()
        photos: list[tuple[str, str, str]] = data.get("photos", [])
        if action == "skip":
            photos = []
            await state.update_data(photos=photos)
        if action == "description" and not photos:
            await callback.answer("Сначала добавьте фото или перейдите к описанию без фото.", show_alert=True)
            return
        if has_duplicate_in_batch([item[2] for item in photos]):
            await reset_sell_wizard(callback.bot, callback.message.chat.id, state)
            await callback.message.answer(
                "Создание отклонено: среди загруженных фото есть повтор.",
                reply_markup=main_menu(),
            )
            await callback.answer()
            return
        duplicate_ad_id = ctx.db.find_duplicate_hash(
            callback.from_user.id,
            [item[2] for item in photos],
            ctx.settings.duplicate_photo_days,
        )
        if duplicate_ad_id is not None:
            await reset_sell_wizard(callback.bot, callback.message.chat.id, state)
            await callback.message.answer(
                f"Создание отклонено: похожее фото уже было в объявлении #{duplicate_ad_id} за последние "
                f"{ctx.settings.duplicate_photo_days} дней.",
                reply_markup=main_menu(),
            )
            await callback.answer()
            return
        if current_state == CreateAd.buy_photos.state:
            await ask_buy_description(callback.message, state)
        else:
            await ask_sell_description_from_state(callback.message, state)
        await callback.answer()

    @router.callback_query(F.data.startswith("sell_category:"))
    async def sell_category_inline(callback: CallbackQuery, state: FSMContext) -> None:
        category = callback.data.split(":", 1)[1]
        await state.update_data(category=category)
        await ask_sell_photos(callback.message, state)
        await callback.answer()

    @router.callback_query(F.data.startswith("sell_back:"))
    async def sell_back(callback: CallbackQuery, state: FSMContext) -> None:
        target = callback.data.split(":", 1)[1]
        data = await state.get_data()
        if target == "create":
            await reset_sell_wizard(callback.bot, callback.message.chat.id, state)
            await callback.message.answer("Создание отменено.", reply_markup=main_menu())
        elif target == "photos":
            await state.set_state(CreateAd.sell_photos)
            await send_wizard_message(
                callback.message,
                state,
                render_sell_photo_prompt(len(data.get("photos", []))),
                reply_markup=sell_photo_inline_menu(has_photos=bool(data.get("photos", []))),
            )
        elif target == "buy_photos":
            await ask_buy_photos(callback.message, state)
        elif target == "description":
            category = data.get("category", "Другое")
            await state.set_state(CreateAd.sell_description)
            await ask_sell_description(callback.message, state, category)
        elif target == "price":
            await state.set_state(CreateAd.sell_price)
            await send_wizard_message(
                callback.message,
                state,
                "Укажите цену",
                reply_markup=wizard_back_keyboard("description"),
            )
        elif target == "address":
            await state.set_state(CreateAd.sell_address)
            await send_wizard_message(
                callback.message,
                state,
                "Укажите Адресс",
                reply_markup=wizard_back_keyboard("price"),
            )
        await callback.answer()

    @router.callback_query(F.data.startswith("sell_confirm:"))
    async def sell_confirm(callback: CallbackQuery, state: FSMContext) -> None:
        action = callback.data.split(":", 1)[1]
        if action == "reset":
            await reset_sell_wizard(callback.bot, callback.message.chat.id, state)
            await callback.answer("Создание отменено")
            return
        data = await state.get_data()
        photos: list[tuple[str, str, str]] = data.get("photos", [])
        required_fields = ("category", "description", "price", "address")
        if any(not data.get(field) for field in required_fields):
            await callback.answer("Не все поля заполнены", show_alert=True)
            return
        duplicate_ad_id = ctx.db.find_duplicate_hash(
            callback.from_user.id,
            [item[2] for item in photos],
            ctx.settings.duplicate_photo_days,
        )
        if duplicate_ad_id is not None:
            await reset_sell_wizard(callback.bot, callback.message.chat.id, state)
            await callback.message.answer(
                f"Создание отклонено: похожее фото уже было в объявлении #{duplicate_ad_id} за последние "
                f"{ctx.settings.duplicate_photo_days} дней.",
                reply_markup=main_menu(),
            )
            await callback.answer()
            return
        ad_id = ctx.db.create_ad(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            ad_type="sell",
            category=data["category"],
            description=data["description"],
            price=data["price"],
            address=data["address"],
            photos=photos,
        )
        await reset_sell_wizard(callback.bot, callback.message.chat.id, state)
        await publish_created_ad(callback.bot, callback.message, ctx, ad_id)
        await callback.answer()

    @router.callback_query(F.data.startswith("buy_confirm:"))
    async def buy_confirm(callback: CallbackQuery, state: FSMContext) -> None:
        action = callback.data.split(":", 1)[1]
        if action == "reset":
            await reset_sell_wizard(callback.bot, callback.message.chat.id, state)
            await callback.answer("Создание отменено")
            return
        data = await state.get_data()
        if not data.get("category") or not data.get("description"):
            await callback.answer("Не все поля заполнены", show_alert=True)
            return
        photos: list[tuple[str, str, str]] = data.get("photos", [])
        if has_duplicate_in_batch([item[2] for item in photos]):
            await reset_sell_wizard(callback.bot, callback.message.chat.id, state)
            await callback.message.answer(
                "Создание отклонено: среди загруженных фото есть повтор.",
                reply_markup=main_menu(),
            )
            await callback.answer()
            return
        ad_id = ctx.db.create_ad(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            ad_type="buy",
            category=data["category"],
            description=data["description"],
            photos=photos,
        )
        await reset_sell_wizard(callback.bot, callback.message.chat.id, state)
        await publish_created_ad(callback.bot, callback.message, ctx, ad_id)
        await callback.answer()

    @router.message(F.text == BTN_RESERVE)
    async def reserve_by_number_start(message: Message, state: FSMContext) -> None:
        await state.set_state(CreateAd.reserve_number)
        await message.answer("Введите номер объявления.")

    @router.message(F.text == BTN_RELEASE_RESERVE)
    async def release_by_number_start(message: Message, state: FSMContext) -> None:
        await state.set_state(CreateAd.release_reserve_number)
        await message.answer("Введите номер объявления.")

    @router.message(Command("remove"))
    @router.message(F.text == BTN_REMOVE_AD)
    async def remove_by_number_start(message: Message, state: FSMContext) -> None:
        await state.set_state(CreateAd.remove_ad_number)
        await message.answer("Введите номер объявления.")

    @router.message(Command("edit"))
    @router.message(F.text == BTN_EDIT_AD)
    async def edit_by_number_start(message: Message, state: FSMContext) -> None:
        await state.set_state(CreateAd.edit_number)
        await message.answer("Укажите номер объявления.")

    @router.message(CreateAd.reserve_number)
    async def reserve_by_number(message: Message, state: FSMContext) -> None:
        ad = ad_from_number_text(ctx, message.text or "")
        await state.clear()
        if ad is None:
            await message.answer("Объявление с таким номером не найдено.", reply_markup=main_menu())
            return
        await reserve_ad(message, ctx, ad)

    @router.message(CreateAd.release_reserve_number)
    async def release_by_number(message: Message, state: FSMContext) -> None:
        ad = ad_from_number_text(ctx, message.text or "")
        await state.clear()
        if ad is None:
            await message.answer("Объявление с таким номером не найдено.", reply_markup=main_menu())
            return
        await release_reserve_ad(message, ctx, ad)

    @router.message(CreateAd.remove_ad_number)
    async def remove_by_number(message: Message, state: FSMContext) -> None:
        ad = ad_from_number_text(ctx, message.text or "")
        await state.clear()
        if ad is None or ad.status != "active":
            await message.answer("Объявление с таким номером не найдено.", reply_markup=main_menu())
            return
        if not can_remove_ad(ctx, message.from_user.id, ad):
            await message.answer("Снять объявление может только автор или админ.", reply_markup=main_menu())
            return
        await message.answer("Укажите причину:", reply_markup=remove_reason_keyboard(ad.id, ad.ad_type))

    @router.message(CreateAd.edit_number)
    async def edit_by_number(message: Message, state: FSMContext) -> None:
        ad = ad_from_number_text(ctx, message.text or "")
        if ad is None or ad.status != "active":
            await state.clear()
            await message.answer("Объявление с таким номером не найдено.", reply_markup=main_menu())
            return
        if not can_remove_ad(ctx, message.from_user.id, ad):
            await state.clear()
            await message.answer("Редактировать объявление может только автор или админ.", reply_markup=main_menu())
            return
        await state.update_data(edit_ad_id=ad.id)
        await state.set_state(CreateAd.edit_description)
        await message.answer(
            f"Текущее описание:\n{ad.description}\n\nВведите новое описание.",
            reply_markup=edit_next_finish_keyboard("photo"),
        )

    @router.message(CreateAd.edit_description)
    async def edit_description(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if not text:
            await message.answer("Отправьте новое описание текстом.")
            return
        data = await state.get_data()
        ad_id = int(data["edit_ad_id"])
        ctx.db.update_ad_description(ad_id, text)
        await refresh_known_messages(message.bot, ctx, ad_id)
        await message.answer("Описание обновлено.", reply_markup=edit_next_finish_keyboard("photo"))

    @router.callback_query(F.data == "edit_finish")
    async def edit_finish(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await callback.message.answer("Изменения внесены.", reply_markup=main_menu())
        await callback.answer()

    @router.callback_query(F.data.startswith("edit_next:"))
    async def edit_next(callback: CallbackQuery, state: FSMContext) -> None:
        target = callback.data.split(":", 1)[1]
        if target == "photo":
            await state.set_state(CreateAd.edit_photo_menu)
            await callback.message.answer("Изменить фото", reply_markup=edit_photo_menu())
        elif target == "price":
            data = await state.get_data()
            ad = ctx.db.get_ad(int(data["edit_ad_id"]))
            current = ad.price if ad and ad.price else ""
            await state.set_state(CreateAd.edit_price)
            await callback.message.answer(
                f"Текущая цена:\n{current}\n\nВведите новую цену.",
                reply_markup=edit_next_finish_keyboard("address"),
            )
        elif target == "address":
            data = await state.get_data()
            ad = ctx.db.get_ad(int(data["edit_ad_id"]))
            current = ad.address if ad and ad.address else ""
            await state.set_state(CreateAd.edit_address)
            await callback.message.answer(
                f"Текущий адрес:\n{current}\n\nВведите новый адрес.",
                reply_markup=edit_finish_keyboard(),
            )
        elif target == "finish":
            await state.clear()
            await callback.message.answer("Изменения внесены.", reply_markup=main_menu())
        await callback.answer()

    @router.callback_query(F.data.startswith("edit_photo:"))
    async def edit_photo_action(callback: CallbackQuery, state: FSMContext) -> None:
        action = callback.data.split(":", 1)[1]
        data = await state.get_data()
        ad_id = int(data["edit_ad_id"])
        photos = ctx.db.ad_photos(ad_id)
        if action == "menu":
            await state.set_state(CreateAd.edit_photo_menu)
            await callback.message.answer("Изменить фото", reply_markup=edit_photo_menu())
        elif action == "add":
            if len(photos) >= MAX_SELL_PHOTOS:
                await callback.answer(f"Уже добавлено {MAX_SELL_PHOTOS} фото.", show_alert=True)
                return
            await state.set_state(CreateAd.edit_add_photo)
            await callback.message.answer(f"Отправьте фото. Можно добавить еще {MAX_SELL_PHOTOS - len(photos)}.")
        elif action == "delete":
            if not photos:
                await callback.answer("Фото нет.", show_alert=True)
                return
            await state.set_state(CreateAd.edit_delete_photo)
            await state.update_data(edit_delete_selected=[])
            await callback.message.answer(
                "Выберите фото для удаления:",
                reply_markup=edit_photo_delete_keyboard(len(photos), set()),
            )
        await callback.answer()

    @router.message(CreateAd.edit_add_photo, F.photo)
    async def edit_add_photo(message: Message, state: FSMContext, bot: Bot) -> None:
        data = await state.get_data()
        ad_id = int(data["edit_ad_id"])
        photos = ctx.db.ad_photos(ad_id)
        if len(photos) >= MAX_SELL_PHOTOS:
            await state.set_state(CreateAd.edit_photo_menu)
            await message.answer("Достигнут лимит фото.", reply_markup=edit_photo_menu())
            return
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        stream = await bot.download_file(file.file_path)
        if stream is None:
            await message.answer("Не удалось скачать фото, попробуйте другое.")
            return
        image_hash = dhash(stream.read())
        duplicate_ad_id = ctx.db.find_duplicate_hash(message.from_user.id, [image_hash], ctx.settings.duplicate_photo_days)
        if duplicate_ad_id is not None:
            await message.answer("Похожее фото уже есть в вашем объявлении.")
            return
        ctx.db.add_ad_photo(ad_id, photo.file_id, photo.file_unique_id, image_hash)
        await republish_ad(message.bot, ctx, ad_id)
        await state.set_state(CreateAd.edit_photo_menu)
        await message.answer("Фото добавлено. Изменить фото", reply_markup=edit_photo_menu())

    @router.callback_query(F.data.startswith("edit_photo_toggle:"))
    async def edit_photo_toggle(callback: CallbackQuery, state: FSMContext) -> None:
        index = int(callback.data.split(":", 1)[1])
        data = await state.get_data()
        selected = set(data.get("edit_delete_selected", []))
        if index in selected:
            selected.remove(index)
        else:
            selected.add(index)
        await state.update_data(edit_delete_selected=sorted(selected))
        ad_id = int(data["edit_ad_id"])
        photo_count = len(ctx.db.ad_photos(ad_id))
        await callback.message.edit_reply_markup(reply_markup=edit_photo_delete_keyboard(photo_count, selected))
        await callback.answer()

    @router.callback_query(F.data == "edit_photo_apply_delete")
    async def edit_photo_apply_delete(callback: CallbackQuery, state: FSMContext) -> None:
        data = await state.get_data()
        ad_id = int(data["edit_ad_id"])
        selected = list(data.get("edit_delete_selected", []))
        if not selected:
            await callback.answer("Выберите фото.", show_alert=True)
            return
        ctx.db.delete_ad_photos_by_indexes(ad_id, selected)
        await republish_ad(callback.bot, ctx, ad_id)
        await state.set_state(CreateAd.edit_photo_menu)
        await callback.message.answer("Фото удалены. Изменить фото", reply_markup=edit_photo_menu())
        await callback.answer()

    @router.message(CreateAd.edit_price)
    async def edit_price(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if not text:
            await message.answer("Отправьте новую цену текстом.")
            return
        data = await state.get_data()
        ad_id = int(data["edit_ad_id"])
        ctx.db.update_ad_price(ad_id, text)
        await refresh_known_messages(message.bot, ctx, ad_id)
        await message.answer("Цена обновлена.", reply_markup=edit_next_finish_keyboard("address"))

    @router.message(CreateAd.edit_address)
    async def edit_address(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if not text:
            await message.answer("Отправьте новый адрес текстом.")
            return
        data = await state.get_data()
        ad_id = int(data["edit_ad_id"])
        ctx.db.update_ad_address(ad_id, text)
        await refresh_known_messages(message.bot, ctx, ad_id)
        await message.answer("Адрес обновлен.", reply_markup=edit_finish_keyboard())

    @router.callback_query(F.data.startswith("remove_start:"))
    async def remove_start(callback: CallbackQuery) -> None:
        ad_id = int(callback.data.split(":", 1)[1])
        ad = ctx.db.get_ad(ad_id)
        if ad is None or not can_remove_ad(ctx, callback.from_user.id, ad):
            await callback.answer("Это действие доступно только автору", show_alert=True)
            return
        await callback.message.answer("Укажите причину:", reply_markup=remove_reason_keyboard(ad_id, ad.ad_type))
        await callback.answer()

    @router.callback_query(F.data.startswith("remove_reason:"))
    async def remove_reason(callback: CallbackQuery) -> None:
        _, ad_id_text, reason = callback.data.split(":", 2)
        ad_id = int(ad_id_text)
        ad = ctx.db.get_ad(ad_id)
        if ad is None or not can_remove_ad(ctx, callback.from_user.id, ad):
            await callback.answer("Это действие доступно только автору", show_alert=True)
            return
        ctx.db.mark_deleted(ad_id, reason)
        await delete_known_messages(callback.bot, ctx, ad_id)
        await callback.message.delete()
        await callback.message.answer("Объявление снято.", reply_markup=main_menu())
        await callback.answer("Объявление снято")

    @router.message(F.reply_to_message)
    async def reply_command(message: Message) -> None:
        saved_message = ctx.db.ad_message_by_message_id(message.chat.id, message.reply_to_message.message_id)
        if saved_message is None:
            return
        ad = ctx.db.get_ad(saved_message.ad_id)
        if ad is None or ad.status != "active":
            await safe_delete(message)
            return

        command = normalize_command(message.text or "")
        if command in {"бронь", "забронировать"}:
            await reserve_ad(message, ctx, ad, delete_command_message=True)
            return
        if command in {"удалить", "снять", "снятьобъявление"}:
            if not can_remove_ad(ctx, message.from_user.id, ad):
                await message.answer("Удалить объявление может только автор или админ.")
                await safe_delete(message)
                return
            await message.answer("Укажите причину:", reply_markup=remove_reason_keyboard(ad.id, ad.ad_type))
            await safe_delete(message)
            return

    @router.message()
    async def fallback(message: Message) -> None:
        await message.answer("Выберите действие в меню.", reply_markup=main_menu())

    return router


async def finish_buy_ad(message: Message, state: FSMContext, ctx: AppContext) -> None:
    if await is_daily_limit_exceeded(message, ctx, ad_type="buy", limit=ctx.settings.buy_daily_limit):
        await state.clear()
        await message.answer("Превышен суточный лимит объявлений на покупку.", reply_markup=main_menu())
        return
    data = await state.get_data()
    if not data.get("category") or not data.get("description"):
        await message.answer("Не все поля заполнены.", reply_markup=main_menu())
        return
    photos: list[tuple[str, str, str]] = data.get("photos", [])
    if has_duplicate_in_batch([item[2] for item in photos]):
        await state.clear()
        await message.answer(
            "Создание отклонено: среди загруженных фото есть повтор.",
            reply_markup=main_menu(),
        )
        return
    ad_id = ctx.db.create_ad(
        user_id=message.from_user.id,
        username=message.from_user.username,
        ad_type="buy",
        category=data["category"],
        description=data["description"],
        photos=photos,
    )
    await state.clear()
    await publish_created_ad(message.bot, message, ctx, ad_id)


async def publish_created_ad(bot: Bot, message: Message, ctx: AppContext, ad_id: int) -> None:
    ad = ctx.db.get_ad(ad_id)
    if ad is None:
        await message.answer("Объявление создано, но не найдено для публикации.", reply_markup=main_menu())
        return
    try:
        await send_ad_to_chat(bot, ctx, ctx.settings.publication_chat_id, ad)
    except TelegramBadRequest:
        await message.answer(
            "Объявление создано, но не удалось опубликовать его в чат объявлений.",
            reply_markup=main_menu(),
        )
        return
    await message.answer("Объявление создано и опубликовано.", reply_markup=main_menu())


async def is_daily_limit_exceeded(message: Message, ctx: AppContext, ad_type: str | None, limit: int) -> bool:
    return ctx.db.count_user_ads_today(message.from_user.id, ad_type=ad_type) >= limit


async def is_daily_limit_exceeded_callback(
    callback: CallbackQuery,
    ctx: AppContext,
    ad_type: str | None,
    limit: int,
) -> bool:
    return ctx.db.count_user_ads_today(callback.from_user.id, ad_type=ad_type) >= limit


async def send_wizard_message(message: Message, state: FSMContext, text: str, reply_markup=None) -> Message:
    sent = await message.answer(text, reply_markup=reply_markup)
    data = await state.get_data()
    message_ids: list[int] = data.get("wizard_message_ids", [])
    message_ids.append(sent.message_id)
    await state.update_data(wizard_message_ids=message_ids)
    return sent


async def remember_wizard_user_message(state: FSMContext, message_id: int) -> None:
    data = await state.get_data()
    message_ids: list[int] = data.get("wizard_user_message_ids", [])
    message_ids.append(message_id)
    await state.update_data(wizard_user_message_ids=message_ids)


async def reset_sell_wizard(bot: Bot, chat_id: int, state: FSMContext) -> None:
    data = await state.get_data()
    for message_id in data.get("wizard_message_ids", []) + data.get("wizard_user_message_ids", []):
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except TelegramBadRequest:
            continue
    await state.clear()


async def ask_sell_category(message: Message, state: FSMContext) -> None:
    await state.set_state(CreateAd.sell_category)
    await send_wizard_message(
        message,
        state,
        "Укажите категорию",
        reply_markup=sell_categories_inline_menu(),
    )


async def ask_buy_photos(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    photos: list[tuple[str, str, str]] = data.get("photos", [])
    await state.set_state(CreateAd.buy_photos)
    await send_wizard_message(
        message,
        state,
        render_sell_photo_prompt(len(photos)),
        reply_markup=sell_photo_inline_menu(has_photos=bool(photos)),
    )


async def ask_buy_description(message: Message, state: FSMContext) -> None:
    await state.set_state(CreateAd.buy_description)
    await send_wizard_message(
        message,
        state,
        "Опишите, что вы хотите купить, принять даром, обменять",
        reply_markup=wizard_back_keyboard("buy_photos"),
    )


async def ask_sell_photos(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    photos: list[tuple[str, str, str]] = data.get("photos", [])
    await state.set_state(CreateAd.sell_photos)
    await send_wizard_message(
        message,
        state,
        render_sell_photo_prompt(len(photos)),
        reply_markup=sell_photo_inline_menu(has_photos=bool(photos)),
    )


async def ask_sell_description_from_state(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    category = data.get("category", "Другое")
    await state.set_state(CreateAd.sell_description)
    await ask_sell_description(message, state, category)


async def ask_sell_description(message: Message, state: FSMContext, category: str) -> None:
    extra = " Не забудьте указать размер." if category == "Одежда" else ""
    await send_wizard_message(
        message,
        state,
        f"Опишите объявление.{extra}",
        reply_markup=wizard_back_keyboard("photos"),
    )


def render_sell_photo_prompt(photo_count: int) -> str:
    remaining = max(MAX_SELL_PHOTOS - photo_count, 0)
    if photo_count == 0:
        return (
            f"Отправьте фото {remaining}/{MAX_SELL_PHOTOS}.\n"
            "Или перейдите к описанию."
        )
    return (
        f"Фото добавлено. {remaining}/{MAX_SELL_PHOTOS}.\n"
        "Отправьте еще фото или перейдите к описанию."
    )


async def show_feed(
    message: Message,
    ctx: AppContext,
    category: str | None = None,
    attach_main_menu: bool = False,
    empty_reply_markup=main_menu(),
) -> None:
    ads = ctx.db.active_ads(ctx.settings.retention_period_days, category=category)
    if not ads:
        sent = await message.answer("Активных объявлений пока нет.", reply_markup=empty_reply_markup)
        ctx.db.save_ui_message(chat_id=message.chat.id, message_id=sent.message_id, message_kind="empty_feed")
        return
    if attach_main_menu and len(ctx.db.ad_photos(ads[0].id)) > 1:
        sent = await message.answer("Лента объявлений:", reply_markup=main_menu())
        ctx.db.save_ui_message(chat_id=message.chat.id, message_id=sent.message_id, message_kind="feed_header")
        attach_main_menu = False
    for index, ad in enumerate(ads):
        await show_one_ad(message, ctx, ad, reply_markup=main_menu() if attach_main_menu and index == 0 else None)


async def show_one_ad(message: Message, ctx: AppContext, ad: Ad | None, reply_markup=None) -> None:
    if ad is None:
        return
    photos = ctx.db.ad_photos(ad.id)
    text = render_ad(ad)
    if len(photos) > 1:
        media = [
            InputMediaPhoto(media=file_id, caption=text if index == 0 else None, parse_mode=ParseMode.HTML)
            for index, file_id in enumerate(photos[:MAX_SELL_PHOTOS])
        ]
        sent_messages = await message.answer_media_group(media)
        for index, sent_message in enumerate(sent_messages):
            ctx.db.save_ad_message(
                ad_id=ad.id,
                chat_id=message.chat.id,
                message_id=sent_message.message_id,
                message_kind="photo",
                photo_index=index,
            )
    elif len(photos) == 1:
        sent = await message.answer_photo(photos[0], caption=text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        ctx.db.save_ad_message(
            ad_id=ad.id,
            chat_id=message.chat.id,
            message_id=sent.message_id,
            message_kind="photo",
            photo_index=0,
        )
    else:
        sent = await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        ctx.db.save_ad_message(
            ad_id=ad.id,
            chat_id=message.chat.id,
            message_id=sent.message_id,
            message_kind="text",
        )


async def send_ad_to_chat(bot: Bot, ctx: AppContext, chat_id: ChatId, ad: Ad) -> None:
    photos = ctx.db.ad_photos(ad.id)
    text = render_ad(ad)
    if len(photos) > 1:
        media = [
            InputMediaPhoto(media=file_id, caption=text if index == 0 else None, parse_mode=ParseMode.HTML)
            for index, file_id in enumerate(photos[:MAX_SELL_PHOTOS])
        ]
        sent_messages = await bot.send_media_group(chat_id=chat_id, media=media)
        for index, sent_message in enumerate(sent_messages):
            ctx.db.save_ad_message(
                ad_id=ad.id,
                chat_id=sent_message.chat.id,
                message_id=sent_message.message_id,
                message_kind="photo",
                photo_index=index,
            )
    elif len(photos) == 1:
        sent = await bot.send_photo(chat_id=chat_id, photo=photos[0], caption=text, parse_mode=ParseMode.HTML)
        ctx.db.save_ad_message(
            ad_id=ad.id,
            chat_id=sent.chat.id,
            message_id=sent.message_id,
            message_kind="photo",
            photo_index=0,
        )
    else:
        sent = await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
        ctx.db.save_ad_message(
            ad_id=ad.id,
            chat_id=sent.chat.id,
            message_id=sent.message_id,
            message_kind="text",
        )


async def republish_ad(bot: Bot, ctx: AppContext, ad_id: int) -> None:
    ad = ctx.db.get_ad(ad_id)
    if ad is None:
        return
    chat_ids = sorted({message.chat_id for message in ctx.db.ad_messages(ad_id)})
    await delete_known_messages(bot, ctx, ad_id)
    for chat_id in chat_ids:
        await send_ad_to_chat(bot, ctx, chat_id, ad)


def render_ad(ad: Ad) -> str:
    kind = "Куплю" if ad.ad_type == "buy" else "Продам"
    parts = [
        render_author(ad),
        f"#{format_public_ad_number(ad.id)}",
        hbold(kind),
        f"Категория: {html.escape(ad.category)}",
        "",
        html.escape(ad.description),
    ]
    if ad.price:
        parts.append(f"Цена: {html.escape(ad.price)}")
    if ad.address:
        parts.append(f"Адрес: {html.escape(ad.address)}")
    if ad.reserved_by is not None:
        parts.append("")
        parts.append(hbold("Забронировано"))
    return "\n".join(parts)


def render_author(ad: Ad) -> str:
    if ad.username:
        username = ad.username.lstrip("@")
        return f'Автор: <a href="https://t.me/{html.escape(username)}">@{html.escape(username)}</a>'
    return f'Автор: <a href="tg://user?id={ad.user_id}">профиль Telegram</a>'


async def refresh_known_messages(bot: Bot, ctx: AppContext, ad_id: int) -> None:
    ad = ctx.db.get_ad(ad_id)
    if ad is None:
        return
    for saved_message in ctx.db.ad_messages(ad_id):
        try:
            if saved_message.message_kind == "photo" and saved_message.photo_index == 0:
                await bot.edit_message_caption(
                    chat_id=saved_message.chat_id,
                    message_id=saved_message.message_id,
                    caption=render_ad(ad),
                    parse_mode=ParseMode.HTML,
                )
            elif saved_message.message_kind == "text":
                await bot.edit_message_text(
                    chat_id=saved_message.chat_id,
                    message_id=saved_message.message_id,
                    text=render_ad(ad),
                    parse_mode=ParseMode.HTML,
                )
        except TelegramBadRequest:
            continue


async def delete_known_messages(bot: Bot, ctx: AppContext, ad_id: int) -> None:
    for saved_message in ctx.db.ad_messages(ad_id):
        try:
            await bot.delete_message(chat_id=saved_message.chat_id, message_id=saved_message.message_id)
        except TelegramBadRequest:
            continue
    ctx.db.delete_ad_messages_for_ad(ad_id)


async def delete_chat_feed_messages(bot: Bot, ctx: AppContext, chat_id: int) -> None:
    for saved_message in ctx.db.ad_messages_for_chat(chat_id):
        try:
            await bot.delete_message(chat_id=chat_id, message_id=saved_message.message_id)
        except TelegramBadRequest:
            continue
    ctx.db.delete_ad_messages_for_chat(chat_id)
    await delete_ui_messages(bot, ctx, chat_id)


async def delete_ui_messages(bot: Bot, ctx: AppContext, chat_id: int) -> None:
    for saved_message in ctx.db.ui_messages_for_chat(chat_id):
        try:
            await bot.delete_message(chat_id=chat_id, message_id=saved_message.message_id)
        except TelegramBadRequest:
            continue
    ctx.db.delete_ui_messages_for_chat(chat_id)


def is_forwarded(message: Message) -> bool:
    return getattr(message, "forward_origin", None) is not None or getattr(message, "forward_date", None) is not None


def has_duplicate_in_batch(hashes: list[str], max_distance: int = 8) -> bool:
    for index, left in enumerate(hashes):
        for right in hashes[index + 1 :]:
            if (int(left, 16) ^ int(right, 16)).bit_count() <= max_distance:
                return True
    return False


def public_ad_number(ad_id: int) -> int:
    return ad_id + PUBLIC_NUMBER_OFFSET


def format_public_ad_number(ad_id: int) -> str:
    return f"{public_ad_number(ad_id):,}".replace(",", " ")


def ad_from_number_text(ctx: AppContext, text: str) -> Ad | None:
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    return ctx.db.get_ad_by_public_number(int(digits))


def normalize_command(text: str) -> str:
    return "".join(ch.lower() for ch in text if ch.isalpha())


def can_remove_ad(ctx: AppContext, user_id: int, ad: Ad) -> bool:
    return ad.user_id == user_id or ctx.db.is_admin(user_id)


async def reserve_ad(message: Message, ctx: AppContext, ad: Ad, delete_command_message: bool = False) -> None:
    if ad.status != "active":
        if not delete_command_message:
            await message.answer("Объявление уже недоступно.", reply_markup=main_menu())
        if delete_command_message:
            await safe_delete(message)
        return
    if ad.reserved_by is not None:
        if not delete_command_message:
            await message.answer("Объявление уже забронировано.", reply_markup=main_menu())
        if delete_command_message:
            await safe_delete(message)
        return
    if ctx.db.reserve(ad.id, message.from_user.id):
        await refresh_known_messages(message.bot, ctx, ad.id)
        if not delete_command_message:
            await message.answer("Объявление забронировано.", reply_markup=main_menu())
    else:
        if not delete_command_message:
            await message.answer("Объявление уже забронировано.", reply_markup=main_menu())
    if delete_command_message:
        await safe_delete(message)


async def release_reserve_ad(message: Message, ctx: AppContext, ad: Ad) -> None:
    if ad.reserved_by is None:
        await message.answer("У объявления нет брони.", reply_markup=main_menu())
        return
    if ad.user_id != message.from_user.id and ad.reserved_by != message.from_user.id:
        await message.answer("Снять бронь может автор брони или автор объявления.", reply_markup=main_menu())
        return
    if ctx.db.release_reserve(ad.id, message.from_user.id):
        await refresh_known_messages(message.bot, ctx, ad.id)
        await message.answer("Бронь снята.", reply_markup=main_menu())
    else:
        await message.answer("Не удалось снять бронь.", reply_markup=main_menu())


async def safe_delete(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        return


async def replace_user_command_with_reply_markup(message: Message, text: str, reply_markup) -> None:
    await safe_delete(message)
    await message.answer(text, reply_markup=reply_markup)


async def run() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    db = Database(settings.database_path)
    db.init()
    for admin_id in settings.admin_ids:
        db.upsert_admin(admin_id)
    db.cleanup_old_ads(settings.retention_period_days)

    bot = Bot(settings.bot_token)
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Открыть меню"),
            BotCommand(command="place", description="Разместить объявление"),
            BotCommand(command="remove", description="Снять объявление"),
            BotCommand(command="edit", description="Редактировать объявление"),
        ]
    )
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(build_router(AppContext(settings=settings, db=db)))
    await dispatcher.start_polling(bot)




if __name__ == "__main__":
    asyncio.run(run())
