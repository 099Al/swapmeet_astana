from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from images import dhash
from keyboards import (
    BTN_BUY,
    BTN_CREATE,
    BTN_SELL,
    BTN_SKIP_PHOTOS,
    buy_categories_inline_menu,
    create_inline_menu,
    sell_confirm_keyboard,
    sell_photo_inline_menu,
    wizard_back_keyboard,
)


def register_create_handlers(router: Router, ctx, deps) -> None:
    CreateAd = deps.CreateAd

    @router.message(Command("place", "create", "post"))
    @router.message(F.text == BTN_CREATE)
    async def create(message: Message) -> None:
        if message.chat.type != "private":
            return
        await message.answer("Что хотите сделать?", reply_markup=create_inline_menu())

    @router.callback_query(F.data == "create:buy")
    async def buy_start_inline(callback: CallbackQuery, state: FSMContext) -> None:
        if not await deps.ensure_private_callback(callback):
            return
        if await deps.is_hourly_limit_exceeded_callback(callback, ctx):
            await callback.answer(deps.hourly_limit_message(ctx), show_alert=True)
            return
        if await deps.is_daily_limit_exceeded_callback(callback, ctx, ad_type="buy", limit=ctx.settings.buy_daily_limit):
            await callback.answer("Превышен суточный лимит объявлений на покупку.", show_alert=True)
            return
        if await deps.is_daily_limit_exceeded_callback(callback, ctx, ad_type=None, limit=ctx.settings.user_daily_ad_limit):
            await callback.answer("Превышен суточный лимит объявлений.", show_alert=True)
            return
        await state.set_data({"photos": [], "wizard_message_ids": [], "wizard_user_message_ids": []})
        await state.set_state(CreateAd.buy_category)
        await deps.safe_delete(callback.message)
        await callback.message.answer("Укажите категорию:", reply_markup=buy_categories_inline_menu())
        await callback.answer()

    @router.callback_query(F.data == "create:sell")
    async def sell_start_inline(callback: CallbackQuery, state: FSMContext) -> None:
        if not await deps.ensure_private_callback(callback):
            return
        if await deps.is_hourly_limit_exceeded_callback(callback, ctx):
            await callback.answer(deps.hourly_limit_message(ctx), show_alert=True)
            return
        if await deps.is_daily_limit_exceeded_callback(callback, ctx, ad_type=None, limit=ctx.settings.user_daily_ad_limit):
            await callback.answer("Превышен суточный лимит объявлений.", show_alert=True)
            return
        await state.set_data({"photos": [], "wizard_message_ids": [], "wizard_user_message_ids": []})
        await deps.ask_sell_category(callback.message, state)
        await callback.answer()

    @router.message(F.text == BTN_BUY)
    async def buy_start(message: Message, state: FSMContext) -> None:
        if message.chat.type != "private":
            return
        if await deps.is_hourly_limit_exceeded(message, ctx):
            await message.answer(deps.hourly_limit_message(ctx))
            return
        if await deps.is_daily_limit_exceeded(message, ctx, ad_type="buy", limit=ctx.settings.buy_daily_limit):
            await message.answer("Превышен суточный лимит объявлений на покупку.")
            return
        if await deps.is_daily_limit_exceeded(message, ctx, ad_type=None, limit=ctx.settings.user_daily_ad_limit):
            await message.answer("Превышен суточный лимит объявлений.")
            return
        await state.set_data({"photos": [], "wizard_message_ids": [], "wizard_user_message_ids": []})
        await state.set_state(CreateAd.buy_category)
        await message.answer("Укажите категорию:", reply_markup=buy_categories_inline_menu())

    @router.message(StateFilter(CreateAd.buy_description))
    async def buy_description(message: Message, state: FSMContext) -> None:
        if deps.is_forwarded(message):
            await message.answer("Пересланные объявления внутри бота не допускаются.")
            return
        text = (message.text or "").strip()
        if not text:
            await message.answer("Отправьте описание текстом.")
            return
        if len(text) > deps.MAX_BUY_DESCRIPTION:
            await message.answer("Описание должно быть не больше 500 символов.")
            return
        await state.update_data(description=text)
        await state.set_state(CreateAd.buy_confirm)
        await deps.send_wizard_message(
            message,
            state,
            "Опубликовать?",
            reply_markup=sell_confirm_keyboard(callback_prefix="buy_confirm"),
        )

    @router.message(StateFilter(CreateAd.buy_photos), F.photo)
    async def buy_photo(message: Message, state: FSMContext, bot: Bot) -> None:
        if deps.is_forwarded(message):
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
        if len(photos) >= deps.MAX_SELL_PHOTOS:
            await deps.ask_buy_description(message, state)
            return
        photos.append((photo.file_id, photo.file_unique_id, image_hash))
        await deps.remember_wizard_user_message(state, message.message_id)
        await state.update_data(photos=photos)
        if len(photos) >= deps.MAX_SELL_PHOTOS:
            await deps.ask_buy_description(message, state)
            return
        await deps.send_wizard_message(
            message,
            state,
            deps.render_sell_photo_prompt(len(photos)),
            reply_markup=sell_photo_inline_menu(has_photos=True),
        )

    @router.message(StateFilter(CreateAd.buy_photos), F.text == BTN_SKIP_PHOTOS)
    async def finish_buy_photos(message: Message, state: FSMContext) -> None:
        await deps.ask_buy_description(message, state)

    @router.message(F.text == BTN_SELL)
    async def sell_start(message: Message, state: FSMContext) -> None:
        if message.chat.type != "private":
            return
        if await deps.is_hourly_limit_exceeded(message, ctx):
            await message.answer(deps.hourly_limit_message(ctx))
            return
        if await deps.is_daily_limit_exceeded(message, ctx, ad_type=None, limit=ctx.settings.user_daily_ad_limit):
            await message.answer("Превышен суточный лимит объявлений.")
            return
        await state.set_data({"photos": [], "wizard_message_ids": [], "wizard_user_message_ids": []})
        await deps.ask_sell_category(message, state)

    @router.message(StateFilter(CreateAd.sell_description))
    async def sell_description(message: Message, state: FSMContext) -> None:
        if deps.is_forwarded(message):
            await message.answer("Пересланные объявления внутри бота не допускаются.")
            return
        text = (message.text or "").strip()
        if not text:
            await message.answer("Отправьте описание текстом.")
            return
        await deps.remember_wizard_user_message(state, message.message_id)
        await state.update_data(description=text)
        await state.set_state(CreateAd.sell_price)
        await deps.send_wizard_message(
            message,
            state,
            "Укажите цену",
            reply_markup=wizard_back_keyboard("description"),
        )

    @router.message(StateFilter(CreateAd.sell_price))
    async def sell_price(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if not text:
            await message.answer("Цена обязательна. Укажите цену, бесплатно или обмен.")
            return
        await deps.remember_wizard_user_message(state, message.message_id)
        await state.update_data(price=text)
        await state.set_state(CreateAd.sell_address)
        await deps.send_wizard_message(
            message,
            state,
            "Укажите Адресс",
            reply_markup=wizard_back_keyboard("price"),
        )

    @router.message(StateFilter(CreateAd.sell_address))
    async def finish_sell(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if not text:
            await message.answer("Адрес обязателен.")
            return
        await deps.remember_wizard_user_message(state, message.message_id)
        await state.update_data(address=text)
        await state.set_state(CreateAd.sell_confirm)
        await deps.send_wizard_message(message, state, "Опубликовать?", reply_markup=sell_confirm_keyboard())

    @router.message(StateFilter(CreateAd.sell_photos), F.photo)
    async def sell_photo(message: Message, state: FSMContext, bot: Bot) -> None:
        if deps.is_forwarded(message):
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
        if len(photos) >= deps.MAX_SELL_PHOTOS:
            await deps.ask_sell_description_from_state(message, state)
            return
        photos.append((photo.file_id, photo.file_unique_id, image_hash))
        await deps.remember_wizard_user_message(state, message.message_id)
        await state.update_data(photos=photos)
        if len(photos) >= deps.MAX_SELL_PHOTOS:
            await deps.ask_sell_description_from_state(message, state)
            return
        await deps.send_wizard_message(
            message,
            state,
            deps.render_sell_photo_prompt(len(photos)),
            reply_markup=sell_photo_inline_menu(has_photos=True),
        )

    @router.message(StateFilter(CreateAd.sell_photos), F.text == BTN_SKIP_PHOTOS)
    async def finish_sell_photos(message: Message, state: FSMContext) -> None:
        await _finish_sell_photos(message, state)

    @router.message(StateFilter(CreateAd.sell_photos), F.text)
    async def sell_description_without_button(message: Message, state: FSMContext) -> None:
        if deps.is_forwarded(message):
            await message.answer("Пересланные объявления внутри бота не допускаются.")
            return
        text = (message.text or "").strip()
        if not text:
            await message.answer("Отправьте описание текстом.")
            return
        if not await _validate_sell_photos(message, state):
            return
        await deps.remember_wizard_user_message(state, message.message_id)
        await state.update_data(description=text)
        await state.set_state(CreateAd.sell_price)
        await deps.send_wizard_message(message, state, "Укажите цену", reply_markup=wizard_back_keyboard("description"))

    @router.callback_query(F.data.startswith("sell_photos:"))
    async def finish_sell_photos_inline(callback: CallbackQuery, state: FSMContext) -> None:
        if not await deps.ensure_private_callback(callback):
            return
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
        if not await _validate_sell_photos(callback.message, state, callback=callback):
            return
        if current_state == CreateAd.buy_photos.state:
            await deps.ask_buy_description(callback.message, state)
        else:
            await deps.ask_sell_description_from_state(callback.message, state)
        await callback.answer()

    @router.callback_query(F.data.startswith("sell_category:"))
    async def sell_category_inline(callback: CallbackQuery, state: FSMContext) -> None:
        if not await deps.ensure_private_callback(callback):
            return
        category = callback.data.split(":", 1)[1]
        await state.update_data(category=category)
        await deps.ask_sell_photos(callback.message, state)
        await callback.answer()

    @router.callback_query(F.data.startswith("buy_category:"))
    async def buy_category_inline(callback: CallbackQuery, state: FSMContext) -> None:
        if not await deps.ensure_private_callback(callback):
            return
        category = callback.data.split(":", 1)[1]
        await state.update_data(category=category)
        await deps.ask_buy_photos(callback.message, state)
        await callback.answer()

    @router.callback_query(F.data.startswith("sell_back:"))
    async def sell_back(callback: CallbackQuery, state: FSMContext) -> None:
        if not await deps.ensure_private_callback(callback):
            return
        target = callback.data.split(":", 1)[1]
        data = await state.get_data()
        if target == "create":
            await deps.reset_sell_wizard(callback.bot, callback.message.chat.id, state)
            await callback.message.answer("Создание отменено.", reply_markup=deps.private_main_menu(callback.message))
        elif target == "photos":
            await state.set_state(CreateAd.sell_photos)
            await deps.send_wizard_message(
                callback.message,
                state,
                deps.render_sell_photo_prompt(len(data.get("photos", []))),
                reply_markup=sell_photo_inline_menu(has_photos=bool(data.get("photos", []))),
            )
        elif target == "buy_photos":
            await deps.ask_buy_photos(callback.message, state)
        elif target == "description":
            category = data.get("category", "Другое")
            await state.set_state(CreateAd.sell_description)
            await deps.ask_sell_description(callback.message, state, category)
        elif target == "price":
            await state.set_state(CreateAd.sell_price)
            await deps.send_wizard_message(callback.message, state, "Укажите цену", reply_markup=wizard_back_keyboard("description"))
        elif target == "address":
            await state.set_state(CreateAd.sell_address)
            await deps.send_wizard_message(callback.message, state, "Укажите Адресс", reply_markup=wizard_back_keyboard("price"))
        await callback.answer()

    @router.callback_query(F.data.startswith("sell_confirm:"))
    async def sell_confirm(callback: CallbackQuery, state: FSMContext) -> None:
        if not await deps.ensure_private_callback(callback):
            return
        action = callback.data.split(":", 1)[1]
        if action == "reset":
            await deps.reset_sell_wizard(callback.bot, callback.message.chat.id, state)
            await callback.answer("Создание отменено")
            return
        data = await state.get_data()
        photos: list[tuple[str, str, str]] = data.get("photos", [])
        required_fields = ("category", "description", "price", "address")
        if any(not data.get(field) for field in required_fields):
            await callback.answer("Не все поля заполнены", show_alert=True)
            return
        if await deps.is_hourly_limit_exceeded_callback(callback, ctx):
            await callback.answer(deps.hourly_limit_message(ctx), show_alert=True)
            return
        duplicate_ad_id = ctx.db.find_duplicate_hash(callback.from_user.id, [item[2] for item in photos], ctx.settings.duplicate_photo_days)
        if duplicate_ad_id is not None:
            await deps.reset_sell_wizard(callback.bot, callback.message.chat.id, state)
            await callback.message.answer(
                f"Создание отклонено: похожее фото уже было в объявлении #{duplicate_ad_id} за последние "
                f"{ctx.settings.duplicate_photo_days} дней.",
                reply_markup=deps.private_main_menu(callback.message),
            )
            await callback.answer()
            return
        ad_id = ctx.db.create_ad(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            author_name=deps.telegram_display_name(callback.from_user.full_name),
            ad_type="sell",
            category=data["category"],
            description=data["description"],
            price=data["price"],
            address=data["address"],
            photos=photos,
        )
        await deps.reset_sell_wizard(callback.bot, callback.message.chat.id, state)
        await deps.publish_created_ad(callback.bot, callback.message, ctx, ad_id)
        await callback.answer()

    @router.callback_query(F.data.startswith("buy_confirm:"))
    async def buy_confirm(callback: CallbackQuery, state: FSMContext) -> None:
        if not await deps.ensure_private_callback(callback):
            return
        action = callback.data.split(":", 1)[1]
        if action == "reset":
            await deps.reset_sell_wizard(callback.bot, callback.message.chat.id, state)
            await callback.answer("Создание отменено")
            return
        data = await state.get_data()
        if not data.get("category") or not data.get("description"):
            await callback.answer("Не все поля заполнены", show_alert=True)
            return
        if await deps.is_hourly_limit_exceeded_callback(callback, ctx):
            await callback.answer(deps.hourly_limit_message(ctx), show_alert=True)
            return
        photos: list[tuple[str, str, str]] = data.get("photos", [])
        if deps.has_duplicate_in_batch([item[2] for item in photos]):
            await deps.reset_sell_wizard(callback.bot, callback.message.chat.id, state)
            await callback.message.answer(
                "Создание отклонено: среди загруженных фото есть повтор.",
                reply_markup=deps.private_main_menu(callback.message),
            )
            await callback.answer()
            return
        ad_id = ctx.db.create_ad(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            author_name=deps.telegram_display_name(callback.from_user.full_name),
            ad_type="buy",
            category=data["category"],
            description=data["description"],
            photos=photos,
        )
        await deps.reset_sell_wizard(callback.bot, callback.message.chat.id, state)
        await deps.publish_created_ad(callback.bot, callback.message, ctx, ad_id)
        await callback.answer()

    async def finish_buy_ad(message: Message, state: FSMContext) -> None:
        if await deps.is_hourly_limit_exceeded(message, ctx):
            await state.clear()
            await message.answer(deps.hourly_limit_message(ctx), reply_markup=deps.private_main_menu(message))
            return
        if await deps.is_daily_limit_exceeded(message, ctx, ad_type="buy", limit=ctx.settings.buy_daily_limit):
            await state.clear()
            await message.answer(
                "Превышен суточный лимит объявлений на покупку.",
                reply_markup=deps.private_main_menu(message),
            )
            return
        data = await state.get_data()
        if not data.get("category") or not data.get("description"):
            await message.answer("Не все поля заполнены.", reply_markup=deps.private_main_menu(message))
            return
        photos: list[tuple[str, str, str]] = data.get("photos", [])
        if deps.has_duplicate_in_batch([item[2] for item in photos]):
            await state.clear()
            await message.answer(
                "Создание отклонено: среди загруженных фото есть повтор.",
                reply_markup=deps.private_main_menu(message),
            )
            return
        ad_id = ctx.db.create_ad(
            user_id=message.from_user.id,
            username=message.from_user.username,
            author_name=deps.telegram_display_name(message.from_user.full_name),
            ad_type="buy",
            category=data["category"],
            description=data["description"],
            photos=photos,
        )
        await state.clear()
        await deps.publish_created_ad(message.bot, message, ctx, ad_id)

    async def _finish_sell_photos(message: Message, state: FSMContext) -> None:
        if not await _validate_sell_photos(message, state):
            return
        await deps.ask_sell_description_from_state(message, state)

    async def _validate_sell_photos(message: Message, state: FSMContext, callback: CallbackQuery | None = None) -> bool:
        data = await state.get_data()
        photos: list[tuple[str, str, str]] = data.get("photos", [])
        if deps.has_duplicate_in_batch([item[2] for item in photos]):
            if callback is None:
                await state.clear()
                await message.answer(
                    "Создание отклонено: среди загруженных фото есть повтор.",
                    reply_markup=deps.private_main_menu(message),
                )
            else:
                await deps.reset_sell_wizard(callback.bot, callback.message.chat.id, state)
                await callback.message.answer(
                    "Создание отклонено: среди загруженных фото есть повтор.",
                    reply_markup=deps.private_main_menu(callback.message),
                )
                await callback.answer()
            return False
        user_id = callback.from_user.id if callback is not None else message.from_user.id
        duplicate_ad_id = ctx.db.find_duplicate_hash(user_id, [item[2] for item in photos], ctx.settings.duplicate_photo_days)
        if duplicate_ad_id is None:
            return True
        text = (
            f"Создание отклонено: похожее фото уже было в объявлении #{duplicate_ad_id} за последние "
            f"{ctx.settings.duplicate_photo_days} дней."
        )
        if callback is None:
            await state.clear()
            await message.answer(text, reply_markup=deps.private_main_menu(message))
        else:
            await deps.reset_sell_wizard(callback.bot, callback.message.chat.id, state)
            await callback.message.answer(text, reply_markup=deps.private_main_menu(callback.message))
            await callback.answer()
        return False

    deps.sell_description_handler = sell_description
    deps.sell_price_handler = sell_price
    deps.finish_sell_handler = finish_sell
    deps.finish_buy_ad = finish_buy_ad
