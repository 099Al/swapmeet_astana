from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InputMediaPhoto, Message
from aiogram.utils.markdown import hbold

from config import Settings, load_settings
from db import Ad, Database
from images import dhash
from keyboards import (
    BTN_BACK,
    BTN_BUY,
    BTN_CATEGORIES,
    BTN_CREATE,
    BTN_DONE,
    BTN_SELL,
    BTN_SKIP_PHOTOS,
    CATEGORIES,
    CATEGORY_ALL,
    ad_keyboard,
    categories_menu,
    confirm_reserve_keyboard,
    create_menu,
    main_menu,
    photo_menu,
    remove_reason_keyboard,
)

MAX_BUY_DESCRIPTION = 500
MAX_SELL_PHOTOS = 5


class CreateAd(StatesGroup):
    buy_description = State()
    buy_category = State()
    sell_category = State()
    sell_description = State()
    sell_price = State()
    sell_address = State()
    sell_photos = State()


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
        await message.answer("Меню открыто. Лента объявлений:", reply_markup=main_menu())
        await show_feed(message, ctx)

    @router.message(F.text == BTN_BACK)
    async def back(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Главное меню", reply_markup=main_menu())
        await show_feed(message, ctx)

    @router.message(F.text == BTN_CATEGORIES)
    async def categories(message: Message) -> None:
        await message.answer("Выберите категорию:", reply_markup=categories_menu(include_all=True))

    @router.message(F.text.in_((*CATEGORIES, CATEGORY_ALL)))
    async def filter_category(message: Message, state: FSMContext) -> None:
        current_state = await state.get_state()
        if current_state == CreateAd.buy_category.state:
            await finish_buy_ad(message, state, ctx)
            return
        if current_state == CreateAd.sell_category.state:
            if message.text not in CATEGORIES:
                await message.answer("Выберите категорию из меню.")
                return
            await state.update_data(category=message.text)
            extra = " Не забудьте указать размер." if message.text == "Одежда" else ""
            await state.set_state(CreateAd.sell_description)
            await message.answer(f"Опишите объявление.{extra}", reply_markup=main_menu())
            return

        category = None if message.text == CATEGORY_ALL else message.text
        await delete_chat_feed_messages(message.bot, ctx, message.chat.id)
        await message.answer("Лента объявлений:", reply_markup=main_menu())
        await show_feed(message, ctx, category=category)

    @router.message(F.text == BTN_CREATE)
    async def create(message: Message) -> None:
        await message.answer("Что хотите сделать?", reply_markup=create_menu())

    @router.message(F.text == BTN_BUY)
    async def buy_start(message: Message, state: FSMContext) -> None:
        if await is_daily_limit_exceeded(message, ctx, ad_type="buy", limit=ctx.settings.buy_daily_limit):
            await message.answer("Превышен суточный лимит объявлений на покупку.")
            return
        if await is_daily_limit_exceeded(message, ctx, ad_type=None, limit=ctx.settings.user_daily_ad_limit):
            await message.answer("Превышен суточный лимит объявлений.")
            return
        await state.set_state(CreateAd.buy_description)
        await message.answer("Опишите, что вы хотите купить, принять даром, обменять")

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
        await state.set_state(CreateAd.buy_category)
        await message.answer("Укажите категорию:", reply_markup=categories_menu(include_all=False))

    @router.message(F.text == BTN_SELL)
    async def sell_start(message: Message, state: FSMContext) -> None:
        if await is_daily_limit_exceeded(message, ctx, ad_type=None, limit=ctx.settings.user_daily_ad_limit):
            await message.answer("Превышен суточный лимит объявлений.")
            return
        await state.update_data(photos=[])
        await state.set_state(CreateAd.sell_photos)
        await message.answer(
            f"Добавьте фото объявления. Можно отправить до {MAX_SELL_PHOTOS} фото. Когда закончите, нажмите «Готово».",
            reply_markup=photo_menu(),
        )

    @router.message(CreateAd.sell_description)
    async def sell_description(message: Message, state: FSMContext) -> None:
        if is_forwarded(message):
            await message.answer("Пересланные объявления внутри бота не допускаются.")
            return
        text = (message.text or "").strip()
        if not text:
            await message.answer("Отправьте описание текстом.")
            return
        await state.update_data(description=text)
        await state.set_state(CreateAd.sell_price)
        await message.answer("Укажите цену: цена/бесплатно/обмен")

    @router.message(CreateAd.sell_price)
    async def sell_price(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if not text:
            await message.answer("Цена обязательна. Укажите цену, бесплатно или обмен.")
            return
        await state.update_data(price=text)
        await state.set_state(CreateAd.sell_address)
        await message.answer("Укажите адрес")

    @router.message(CreateAd.sell_address)
    async def finish_sell(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if not text:
            await message.answer("Адрес обязателен.")
            return
        await state.update_data(address=text)
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
        ad_id = ctx.db.create_ad(
            user_id=message.from_user.id,
            username=message.from_user.username,
            ad_type="sell",
            category=data["category"],
            description=data["description"],
            price=data["price"],
            address=text,
            photos=photos,
        )
        await state.clear()
        await message.answer("Объявление создано.", reply_markup=main_menu())
        await show_one_ad(message, ctx, ctx.db.get_ad(ad_id))

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
            await message.answer(f"Можно добавить не больше {MAX_SELL_PHOTOS} фото.")
            return
        photos.append((photo.file_id, photo.file_unique_id, image_hash))
        await state.update_data(photos=photos)
        await message.answer(f"Фото добавлено: {len(photos)}/{MAX_SELL_PHOTOS}.")

    @router.message(CreateAd.sell_photos, F.text.in_((BTN_DONE, BTN_SKIP_PHOTOS)))
    async def finish_sell_photos(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        photos: list[tuple[str, str, str]] = data.get("photos", [])
        if message.text == BTN_DONE and not photos:
            await message.answer("Добавьте хотя бы одно фото или нажмите «Без фото».")
            return
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
        await state.set_state(CreateAd.sell_category)
        await message.answer("Укажите категорию:", reply_markup=categories_menu(include_all=False))

    @router.callback_query(F.data.startswith("photo:"))
    async def switch_photo(callback: CallbackQuery) -> None:
        _, ad_id_text, index_text = callback.data.split(":", 2)
        ad_id = int(ad_id_text)
        photo_index = int(index_text)
        ad = ctx.db.get_ad(ad_id)
        photos = ctx.db.ad_photos(ad_id)
        if ad is None or ad.status != "active" or not photos:
            await callback.answer("Объявление недоступно", show_alert=True)
            return
        photo_index %= len(photos)
        keyboard = ad_keyboard(
            ad.id,
            is_author=callback.from_user.id == ad.user_id,
            is_reserved=ad.reserved_by is not None,
            photo_count=len(photos),
            photo_index=photo_index,
        )
        await callback.message.edit_media(
            InputMediaPhoto(media=photos[photo_index], caption=render_ad(ad), parse_mode=ParseMode.HTML),
            reply_markup=keyboard,
        )
        ctx.db.update_ad_message_photo_index(ad_id, callback.message.chat.id, callback.message.message_id, photo_index)
        await callback.answer()

    @router.callback_query(F.data.startswith("photo_noop:"))
    async def photo_noop(callback: CallbackQuery) -> None:
        await callback.answer()

    @router.callback_query(F.data.startswith("reserve_start:"))
    async def reserve_start(callback: CallbackQuery) -> None:
        ad_id = int(callback.data.split(":", 1)[1])
        await callback.message.answer("Подтвердить бронь:", reply_markup=confirm_reserve_keyboard(ad_id))
        await callback.answer()

    @router.callback_query(F.data.startswith("reserve_no:"))
    async def reserve_no(callback: CallbackQuery) -> None:
        await callback.message.delete()
        await callback.answer("Отменено")

    @router.callback_query(F.data.startswith("reserve_yes:"))
    async def reserve_yes(callback: CallbackQuery) -> None:
        ad_id = int(callback.data.split(":", 1)[1])
        ad = ctx.db.get_ad(ad_id)
        if ad is None or ad.status != "active":
            await callback.answer("Объявление уже недоступно", show_alert=True)
            return
        if ad.reserved_by is not None:
            await callback.answer("Объявление уже в броне", show_alert=True)
            return
        if ctx.db.reserve(ad_id, callback.from_user.id):
            await callback.answer("Забронировано")
            await refresh_known_messages(callback.bot, ctx, ad_id)
            await callback.message.delete()
        else:
            await callback.answer("Объявление уже в броне", show_alert=True)

    @router.callback_query(F.data.startswith("reserve_release:"))
    async def reserve_release(callback: CallbackQuery) -> None:
        ad_id = int(callback.data.split(":", 1)[1])
        if ctx.db.release_reserve(ad_id, callback.from_user.id):
            await callback.answer("Бронь снята")
            await refresh_known_messages(callback.bot, ctx, ad_id)
        else:
            await callback.answer("Не удалось снять бронь", show_alert=True)

    @router.callback_query(F.data.startswith("remove_start:"))
    async def remove_start(callback: CallbackQuery) -> None:
        ad_id = int(callback.data.split(":", 1)[1])
        ad = ctx.db.get_ad(ad_id)
        if ad is None or ad.user_id != callback.from_user.id:
            await callback.answer("Это действие доступно только автору", show_alert=True)
            return
        await callback.message.answer("Укажите причину:", reply_markup=remove_reason_keyboard(ad_id, ad.ad_type))
        await callback.answer()

    @router.callback_query(F.data.startswith("remove_reason:"))
    async def remove_reason(callback: CallbackQuery) -> None:
        _, ad_id_text, reason = callback.data.split(":", 2)
        ad_id = int(ad_id_text)
        ad = ctx.db.get_ad(ad_id)
        if ad is None or ad.user_id != callback.from_user.id:
            await callback.answer("Это действие доступно только автору", show_alert=True)
            return
        ctx.db.mark_deleted(ad_id, reason)
        await delete_known_messages(callback.bot, ctx, ad_id)
        await callback.message.delete()
        await callback.answer("Объявление снято")

    @router.message()
    async def fallback(message: Message) -> None:
        await message.answer("Выберите действие в меню.", reply_markup=main_menu())

    return router


async def finish_buy_ad(message: Message, state: FSMContext, ctx: AppContext) -> None:
    if message.text not in CATEGORIES:
        await message.answer("Выберите категорию из меню.")
        return
    if await is_daily_limit_exceeded(message, ctx, ad_type="buy", limit=ctx.settings.buy_daily_limit):
        await state.clear()
        await message.answer("Превышен суточный лимит объявлений на покупку.", reply_markup=main_menu())
        return
    data = await state.get_data()
    ad_id = ctx.db.create_ad(
        user_id=message.from_user.id,
        username=message.from_user.username,
        ad_type="buy",
        category=message.text,
        description=data["description"],
    )
    await state.clear()
    await message.answer("Объявление создано.", reply_markup=main_menu())
    await show_one_ad(message, ctx, ctx.db.get_ad(ad_id))


async def is_daily_limit_exceeded(message: Message, ctx: AppContext, ad_type: str | None, limit: int) -> bool:
    return ctx.db.count_user_ads_today(message.from_user.id, ad_type=ad_type) >= limit


async def show_feed(message: Message, ctx: AppContext, category: str | None = None) -> None:
    ads = ctx.db.active_ads(ctx.settings.retention_period_days, category=category)
    if not ads:
        await message.answer("Активных объявлений пока нет.", reply_markup=main_menu())
        return
    for ad in ads:
        await show_one_ad(message, ctx, ad)


async def show_one_ad(message: Message, ctx: AppContext, ad: Ad | None) -> None:
    if ad is None:
        return
    photos = ctx.db.ad_photos(ad.id)
    text = render_ad(ad)
    keyboard = ad_keyboard(
        ad.id,
        is_author=message.from_user.id == ad.user_id,
        is_reserved=ad.reserved_by is not None,
        photo_count=len(photos),
        photo_index=0,
    )
    if photos:
        sent = await message.answer_photo(
            photos[0],
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
        ctx.db.save_ad_message(
            ad_id=ad.id,
            chat_id=message.chat.id,
            message_id=sent.message_id,
            message_kind="photo",
            photo_index=0,
        )
    else:
        sent = await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        ctx.db.save_ad_message(
            ad_id=ad.id,
            chat_id=message.chat.id,
            message_id=sent.message_id,
            message_kind="text",
        )


def render_ad(ad: Ad) -> str:
    kind = "Куплю" if ad.ad_type == "buy" else "Продам"
    parts = [
        f"{hbold(kind)} #{ad.id}",
        f"Категория: {ad.category}",
        "",
        ad.description,
    ]
    if ad.price:
        parts.append(f"Цена: {ad.price}")
    if ad.address:
        parts.append(f"Адрес: {ad.address}")
    if ad.reserved_by is not None:
        parts.append("")
        parts.append(hbold("! Забронировано"))
    return "\n".join(parts)


async def refresh_known_messages(bot: Bot, ctx: AppContext, ad_id: int) -> None:
    ad = ctx.db.get_ad(ad_id)
    if ad is None:
        return
    photos = ctx.db.ad_photos(ad_id)
    for saved_message in ctx.db.ad_messages(ad_id):
        photo_index = saved_message.photo_index % len(photos) if photos else 0
        keyboard = ad_keyboard(
            ad.id,
            is_author=saved_message.chat_id == ad.user_id,
            is_reserved=ad.reserved_by is not None,
            photo_count=len(photos),
            photo_index=photo_index,
        )
        try:
            if saved_message.message_kind == "photo" and photos:
                await bot.edit_message_media(
                    chat_id=saved_message.chat_id,
                    message_id=saved_message.message_id,
                    media=InputMediaPhoto(
                        media=photos[photo_index],
                        caption=render_ad(ad),
                        parse_mode=ParseMode.HTML,
                    ),
                    reply_markup=keyboard,
                )
            else:
                await bot.edit_message_text(
                    chat_id=saved_message.chat_id,
                    message_id=saved_message.message_id,
                    text=render_ad(ad),
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
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


def is_forwarded(message: Message) -> bool:
    return getattr(message, "forward_origin", None) is not None or getattr(message, "forward_date", None) is not None


def has_duplicate_in_batch(hashes: list[str], max_distance: int = 8) -> bool:
    for index, left in enumerate(hashes):
        for right in hashes[index + 1 :]:
            if (int(left, 16) ^ int(right, 16)).bit_count() <= max_distance:
                return True
    return False


async def run() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    db = Database(settings.database_path)
    db.init()
    db.cleanup_old_ads(settings.retention_period_days)

    bot = Bot(settings.bot_token)
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(build_router(AppContext(settings=settings, db=db)))
    await dispatcher.start_polling(bot)




if __name__ == "__main__":
    asyncio.run(run())
