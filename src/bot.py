from __future__ import annotations

import asyncio
import html
import logging
from contextlib import suppress
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from typing import Union

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, CallbackQuery, InputMediaPhoto, Message
from aiogram.utils.markdown import hbold

from config import load_settings
from context import AppContext, CreateAd
from db import Ad, Database
from handlers import register_reply_menu_handlers
from keyboards import (
    BTN_BACK,
    CATEGORIES,
    CATEGORY_ALL,
    main_menu,
    sell_categories_inline_menu,
    sell_photo_inline_menu,
    wizard_back_keyboard,
)

MAX_BUY_DESCRIPTION = 500
MAX_SELL_PHOTOS = 6
RETENTION_CLEANUP_JOB = "retention_cleanup"
RETENTION_CLEANUP_TIME = time(hour=1)
ChatId = Union[int, str]


def private_main_menu(message: Message):
    return main_menu() if message.chat.type == "private" else None


async def ensure_private_callback(callback: CallbackQuery) -> bool:
    if callback.message.chat.type == "private":
        return True
    await callback.answer("Откройте бота в личных сообщениях.", show_alert=True)
    return False


def build_router(ctx: AppContext) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def start(message: Message, state: FSMContext) -> None:
        if message.chat.type != "private":
            return
        await state.clear()
        await message.answer("Выберите действие в меню.", reply_markup=private_main_menu(message))

    @router.message(F.text == BTN_BACK)
    async def back(message: Message, state: FSMContext) -> None:
        if message.chat.type != "private":
            return
        await state.clear()
        await message.answer("Выберите действие в меню.", reply_markup=private_main_menu(message))

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

        await message.answer(
            "Категории используются только при создании объявления.",
            reply_markup=private_main_menu(message),
        )

    deps = SimpleNamespace(
        CreateAd=CreateAd,
        MAX_BUY_DESCRIPTION=MAX_BUY_DESCRIPTION,
        MAX_SELL_PHOTOS=MAX_SELL_PHOTOS,
        ad_from_number_text=ad_from_number_text,
        apply_pending_edit_photos=apply_pending_edit_photos,
        ask_buy_description=ask_buy_description,
        ask_buy_photos=ask_buy_photos,
        ask_sell_category=ask_sell_category,
        ask_sell_description=ask_sell_description,
        ask_sell_description_from_state=ask_sell_description_from_state,
        ask_sell_photos=ask_sell_photos,
        can_remove_ad=can_remove_ad,
        delete_known_messages=delete_known_messages,
        ensure_private_callback=ensure_private_callback,
        has_duplicate_in_batch=has_duplicate_in_batch,
        hourly_limit_message=hourly_limit_message,
        is_daily_limit_exceeded=is_daily_limit_exceeded,
        is_daily_limit_exceeded_callback=is_daily_limit_exceeded_callback,
        is_forwarded=is_forwarded,
        is_hourly_limit_exceeded=is_hourly_limit_exceeded,
        is_hourly_limit_exceeded_callback=is_hourly_limit_exceeded_callback,
        private_main_menu=private_main_menu,
        publish_created_ad=publish_created_ad,
        replace_published_ad_photo=replace_published_ad_photo,
        refresh_known_messages=refresh_known_messages,
        release_reserve_ad=release_reserve_ad,
        remember_wizard_user_message=remember_wizard_user_message,
        render_sell_photo_prompt=render_sell_photo_prompt,
        republish_ad=republish_ad,
        reserve_ad=reserve_ad,
        reset_sell_wizard=reset_sell_wizard,
        safe_delete=safe_delete,
        send_wizard_message=send_wizard_message,
        telegram_display_name=telegram_display_name,
    )
    register_reply_menu_handlers(router, ctx, deps)

    @router.message(F.reply_to_message)
    async def reply_command(message: Message) -> None:
        saved_message = ctx.db.ad_message_by_message_id(message.chat.id, message.reply_to_message.message_id)
        if saved_message is None:
            if is_publication_chat(message, ctx):
                await handle_publication_chat_message(message, ctx)
            return
        if message.from_user is not None and ctx.db.is_admin(message.from_user.id):
            return
        if message.from_user is not None and ctx.db.is_user_blocked(message.from_user.id):
            await safe_delete(message)
            return
        ad = ctx.db.get_ad(saved_message.ad_id)
        if ad is None or ad.status != "active":
            await send_chat_rules(message.bot, message, ctx)
            await safe_delete(message)
            return

        command = normalize_command(message.text or "")
        if command in {"бронь", "забронировать"}:
            await reserve_ad(message, ctx, ad, delete_command_message=True)
            return
        await send_chat_rules(message.bot, message, ctx)
        await safe_delete(message)

    @router.message()
    async def fallback(message: Message, state: FSMContext) -> None:
        if message.chat.type == "private":
            current_state = await state.get_state()
            if current_state == CreateAd.sell_description.state:
                await deps.sell_description_handler(message, state)
                return
            if current_state == CreateAd.sell_price.state:
                await deps.sell_price_handler(message, state)
                return
            if current_state == CreateAd.sell_address.state:
                await deps.finish_sell_handler(message, state)
                return
            if current_state is not None:
                await message.answer("Завершите текущий шаг или нажмите «Назад».")
                return
            await message.answer("Выберите действие в меню.", reply_markup=private_main_menu(message))
            return
        if is_publication_chat(message, ctx):
            await handle_publication_chat_message(message, ctx)

    return router


async def publish_created_ad(bot: Bot, message: Message, ctx: AppContext, ad_id: int) -> None:
    ad = ctx.db.get_ad(ad_id)
    if ad is None:
        await message.answer(
            "Объявление создано, но не найдено для публикации.",
            reply_markup=private_main_menu(message),
        )
        return
    try:
        await send_ad_to_chat(bot, ctx, ctx.settings.publication_chat_id, ad)
    except TelegramBadRequest:
        await message.answer(
            "Объявление создано, но не удалось опубликовать его в чат объявлений.",
            reply_markup=private_main_menu(message),
        )
        return
    await message.answer("Объявление создано и опубликовано.", reply_markup=private_main_menu(message))


async def is_daily_limit_exceeded(message: Message, ctx: AppContext, ad_type: str | None, limit: int) -> bool:
    return ctx.db.count_user_ads_today(message.from_user.id, ad_type=ad_type) >= limit


async def is_hourly_limit_exceeded(message: Message, ctx: AppContext) -> bool:
    return ctx.db.count_user_ads_last_hour(message.from_user.id) >= ctx.settings.user_hourly_ad_limit


async def is_daily_limit_exceeded_callback(
    callback: CallbackQuery,
    ctx: AppContext,
    ad_type: str | None,
    limit: int,
) -> bool:
    return ctx.db.count_user_ads_today(callback.from_user.id, ad_type=ad_type) >= limit


async def is_hourly_limit_exceeded_callback(callback: CallbackQuery, ctx: AppContext) -> bool:
    return ctx.db.count_user_ads_last_hour(callback.from_user.id) >= ctx.settings.user_hourly_ad_limit


def hourly_limit_message(ctx: AppContext) -> str:
    return f"Превышен лимит: не больше {ctx.settings.user_hourly_ad_limit} объявлений в час."


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


async def apply_pending_edit_photos(bot: Bot, ctx: AppContext, state: FSMContext) -> None:
    data = await state.get_data()
    ad_id = data.get("edit_ad_id")
    pending_photos: list[tuple[str, str, str]] = data.get("edit_added_photos", [])
    if ad_id is None or not pending_photos:
        return
    ad_id = int(ad_id)
    for file_id, file_unique_id, image_hash in pending_photos:
        ctx.db.add_ad_photo(ad_id, file_id, file_unique_id, image_hash)
    await state.update_data(edit_added_photos=[])
    await republish_ad(bot, ctx, ad_id)


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
    empty_reply_markup=None,
) -> None:
    ads = ctx.db.active_ads(ctx.settings.retention_period_days, category=category)
    if not ads:
        sent = await message.answer("Активных объявлений пока нет.", reply_markup=empty_reply_markup)
        ctx.db.save_ui_message(chat_id=message.chat.id, message_id=sent.message_id, message_kind="empty_feed")
        return
    if attach_main_menu and len(ctx.db.ad_photos(ads[0].id)) > 1:
        sent = await message.answer("Лента объявлений:", reply_markup=private_main_menu(message))
        ctx.db.save_ui_message(chat_id=message.chat.id, message_id=sent.message_id, message_kind="feed_header")
        attach_main_menu = False
    for index, ad in enumerate(ads):
        await show_one_ad(
            message,
            ctx,
            ad,
            reply_markup=private_main_menu(message) if attach_main_menu and index == 0 else None,
        )


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
        sent = await message.answer(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
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
        sent = await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
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
    if ad.author_name:
        author_name = html.escape(ad.author_name)
        return f'Автор: <a href="tg://user?id={ad.user_id}">{author_name}</a>'
    if ad.username:
        username = ad.username.lstrip("@")
        escaped_username = html.escape(username)
        return f'Автор: <a href="https://t.me/{escaped_username}">@{escaped_username}</a>'
    return "Автор: username не указан"


async def refresh_known_messages(bot: Bot, ctx: AppContext, ad_id: int) -> None:
    ad = ctx.db.get_ad(ad_id)
    if ad is None:
        return
    has_failed_update = False
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
                    disable_web_page_preview=True,
                )
        except TelegramBadRequest:
            has_failed_update = True
    if has_failed_update:
        await republish_ad(bot, ctx, ad_id)


async def replace_published_ad_photo(bot: Bot, ctx: AppContext, ad_id: int, photo_index: int) -> bool:
    ad = ctx.db.get_ad(ad_id)
    if ad is None:
        return False
    photos = ctx.db.ad_photos(ad_id)
    if photo_index < 0 or photo_index >= len(photos):
        return False
    updated = False
    for saved_message in ctx.db.ad_messages(ad_id):
        if saved_message.message_kind != "photo" or saved_message.photo_index != photo_index:
            continue
        try:
            await bot.edit_message_media(
                chat_id=saved_message.chat_id,
                message_id=saved_message.message_id,
                media=InputMediaPhoto(
                    media=photos[photo_index],
                    caption=render_ad(ad) if photo_index == 0 else None,
                    parse_mode=ParseMode.HTML if photo_index == 0 else None,
                ),
            )
            updated = True
        except TelegramBadRequest:
            continue
    return updated


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


def format_public_ad_number(ad_id: int) -> str:
    return str(ad_id)


def ad_from_number_text(ctx: AppContext, text: str) -> Ad | None:
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    return ctx.db.get_ad(int(digits))


def normalize_command(text: str) -> str:
    return "".join(ch.lower() for ch in text if ch.isalpha())


def can_remove_ad(ctx: AppContext, user_id: int, ad: Ad) -> bool:
    return ad.user_id == user_id or ctx.db.is_admin(user_id)


def telegram_display_name(full_name: str | None) -> str | None:
    full_name = (full_name or "").strip()
    return full_name or None


def is_publication_chat(message: Message, ctx: AppContext) -> bool:
    publication_chat_id = ctx.settings.publication_chat_id
    if isinstance(publication_chat_id, int):
        return message.chat.id == publication_chat_id
    publication_username = publication_chat_id.lstrip("@").lower()
    chat_username = (message.chat.username or "").lower()
    return bool(publication_username and chat_username == publication_username)


def is_communication_topic_message(message: Message, ctx: AppContext) -> bool:
    topic_id = ctx.settings.communication_topic_id
    return topic_id is not None and getattr(message, "message_thread_id", None) == topic_id


async def handle_publication_chat_message(message: Message, ctx: AppContext) -> None:
    if message.from_user is None or message.from_user.is_bot:
        await safe_delete(message)
        return
    if ctx.db.is_admin(message.from_user.id):
        return
    if ctx.db.is_user_blocked(message.from_user.id):
        await safe_delete(message)
        return
    if not is_communication_topic_message(message, ctx):
        await send_chat_rules(message.bot, message, ctx)
        await safe_delete(message)
        return
    if ctx.db.count_user_communication_messages_today(message.from_user.id) >= ctx.settings.communication_daily_message_limit:
        await safe_delete(message)
        return
    ctx.db.save_communication_message(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        message_id=message.message_id,
        message_thread_id=message.message_thread_id,
    )


async def send_chat_rules(bot: Bot, message: Message, ctx: AppContext) -> None:
    if message.from_user is None:
        return
    try:
        await bot.send_message(
            chat_id=message.from_user.id,
            text=(
                "Правила чата:\n\n"
                "1. Размещайте объявления через бота: /place или кнопка «Разместить объявление».\n"
                "2. Для редактирования используйте /edit или кнопку «Редактировать».\n"
                "3. Для снятия объявления используйте /remove или кнопку «Снять объявление».\n"
                "4. Бронь ставится ответом на объявление словом «Бронь» или через кнопку «Забронировать».\n"
                "5. Общение пользователей разрешено только в теме «Общение».\n"
                "6. Лимиты: не больше 5 объявлений в час, общий суточный лимит объявлений и до 20 сообщений "
                "в теме «Общение» в сутки."
            ),
        )
    except TelegramForbiddenError:
        ctx.db.block_user(
            message.from_user.id,
            "Пользователь запретил боту отправлять личные сообщения",
            duration_days=30,
        )
    except TelegramBadRequest:
        return


async def reserve_ad(message: Message, ctx: AppContext, ad: Ad, delete_command_message: bool = False) -> None:
    if ad.status != "active":
        if not delete_command_message:
            await message.answer("Объявление уже недоступно.", reply_markup=private_main_menu(message))
        if delete_command_message:
            await safe_delete(message)
        return
    if ad.reserved_by is not None:
        if not delete_command_message:
            await message.answer("Объявление уже забронировано.", reply_markup=private_main_menu(message))
        if delete_command_message:
            await safe_delete(message)
        return
    if ctx.db.reserve(ad.id, message.from_user.id):
        await refresh_known_messages(message.bot, ctx, ad.id)
        if not delete_command_message:
            await message.answer("Объявление забронировано.", reply_markup=private_main_menu(message))
    else:
        if not delete_command_message:
            await message.answer("Объявление уже забронировано.", reply_markup=private_main_menu(message))
    if delete_command_message:
        await safe_delete(message)


async def release_reserve_ad(message: Message, ctx: AppContext, ad: Ad) -> None:
    if ad.reserved_by is None:
        await message.answer("У объявления нет брони.", reply_markup=private_main_menu(message))
        return
    if ad.user_id != message.from_user.id and ad.reserved_by != message.from_user.id:
        await message.answer(
            "Снять бронь может автор брони или автор объявления.",
            reply_markup=private_main_menu(message),
        )
        return
    if ctx.db.release_reserve(ad.id, message.from_user.id):
        await refresh_known_messages(message.bot, ctx, ad.id)
        await message.answer("Бронь снята.", reply_markup=private_main_menu(message))
    else:
        await message.answer("Не удалось снять бронь.", reply_markup=private_main_menu(message))


async def safe_delete(message: Message) -> None:
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError):
        return


async def replace_user_command_with_reply_markup(message: Message, text: str, reply_markup) -> None:
    await safe_delete(message)
    await message.answer(text, reply_markup=reply_markup)


def next_retention_cleanup_at(now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    next_run = datetime.combine(now.date(), RETENTION_CLEANUP_TIME)
    if next_run <= now:
        next_run += timedelta(days=1)
    return next_run


async def run_retention_cleanup(bot: Bot, ctx: AppContext) -> None:
    for ad_id in ctx.db.expired_active_ad_ids(ctx.settings.retention_period_days):
        await delete_known_messages(bot, ctx, ad_id)
    ctx.db.cleanup_old_ads(ctx.settings.retention_period_days)


async def retention_cleanup_scheduler(bot: Bot, ctx: AppContext) -> None:
    next_run = next_retention_cleanup_at()
    ctx.db.upsert_scheduled_job(
        RETENTION_CLEANUP_JOB,
        last_run_at=None,
        next_run_at=next_run.isoformat(timespec="seconds"),
    )
    while True:
        await asyncio.sleep(max((next_run - datetime.now()).total_seconds(), 0))
        await run_retention_cleanup(bot, ctx)
        last_run = datetime.now()
        next_run = next_retention_cleanup_at(last_run)
        ctx.db.upsert_scheduled_job(
            RETENTION_CLEANUP_JOB,
            last_run_at=last_run.isoformat(timespec="seconds"),
            next_run_at=next_run.isoformat(timespec="seconds"),
        )


async def run() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    db = Database(settings.database_path)
    db.init()
    for admin_id in settings.admin_ids:
        db.upsert_admin(admin_id)

    bot = Bot(settings.bot_token)
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Открыть меню"),
            BotCommand(command="place", description="Разместить объявление"),
            BotCommand(command="reserve", description="Забронировать объявление"),
            BotCommand(command="remove", description="Снять объявление"),
            BotCommand(command="edit", description="Редактировать объявление"),
        ]
    )
    dispatcher = Dispatcher(storage=MemoryStorage())
    ctx = AppContext(settings=settings, db=db)
    await run_retention_cleanup(bot, ctx)
    cleanup_started_at = datetime.now()
    db.upsert_scheduled_job(
        RETENTION_CLEANUP_JOB,
        last_run_at=cleanup_started_at.isoformat(timespec="seconds"),
        next_run_at=next_retention_cleanup_at(cleanup_started_at).isoformat(timespec="seconds"),
    )
    cleanup_task = asyncio.create_task(retention_cleanup_scheduler(bot, ctx))
    dispatcher.include_router(build_router(ctx))
    try:
        await dispatcher.start_polling(bot)
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task




if __name__ == "__main__":
    asyncio.run(run())
