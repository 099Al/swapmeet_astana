from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from images import dhash
from keyboards import (
    BTN_EDIT_AD,
    edit_finish_keyboard,
    edit_next_finish_keyboard,
    edit_photo_delete_keyboard,
    edit_photo_menu,
)


def register_edit_handlers(router: Router, ctx, deps) -> None:
    CreateAd = deps.CreateAd

    @router.message(Command("edit"))
    @router.message(F.text == BTN_EDIT_AD)
    async def edit_by_number_start(message: Message, state: FSMContext) -> None:
        if message.chat.type != "private":
            return
        await state.set_state(CreateAd.edit_number)
        await message.answer("Укажите номер объявления.")

    @router.message(StateFilter(CreateAd.edit_number))
    async def edit_by_number(message: Message, state: FSMContext) -> None:
        ad = deps.ad_from_number_text(ctx, message.text or "")
        if ad is None or ad.status != "active":
            await state.clear()
            await message.answer("Объявление с таким номером не найдено.", reply_markup=deps.private_main_menu(message))
            return
        if not deps.can_remove_ad(ctx, message.from_user.id, ad):
            await state.clear()
            await message.answer(
                "Редактировать объявление может только автор или админ.",
                reply_markup=deps.private_main_menu(message),
            )
            return
        await state.update_data(edit_ad_id=ad.id)
        await state.set_state(CreateAd.edit_description)
        await message.answer(
            f"Текущее описание:\n{ad.description}\n\nВведите новое описание.",
            reply_markup=edit_next_finish_keyboard("photo"),
        )

    @router.message(StateFilter(CreateAd.edit_description))
    async def edit_description(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if not text:
            await message.answer("Отправьте новое описание текстом.")
            return
        data = await state.get_data()
        ad_id = int(data["edit_ad_id"])
        ctx.db.update_ad_description(ad_id, text)
        await deps.refresh_known_messages(message.bot, ctx, ad_id)
        await message.answer("Описание обновлено.", reply_markup=edit_next_finish_keyboard("photo"))

    @router.callback_query(F.data == "edit_finish")
    async def edit_finish(callback: CallbackQuery, state: FSMContext) -> None:
        if not await deps.ensure_private_callback(callback):
            return
        await deps.apply_pending_edit_photos(callback.bot, ctx, state)
        await state.clear()
        await callback.message.answer("Изменения внесены.", reply_markup=deps.private_main_menu(callback.message))
        await callback.answer()

    @router.callback_query(F.data.startswith("edit_next:"))
    async def edit_next(callback: CallbackQuery, state: FSMContext) -> None:
        if not await deps.ensure_private_callback(callback):
            return
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
            await deps.apply_pending_edit_photos(callback.bot, ctx, state)
            await state.clear()
            await callback.message.answer("Изменения внесены.", reply_markup=deps.private_main_menu(callback.message))
        await callback.answer()

    @router.callback_query(F.data.startswith("edit_photo:"))
    async def edit_photo_action(callback: CallbackQuery, state: FSMContext) -> None:
        if not await deps.ensure_private_callback(callback):
            return
        action = callback.data.split(":", 1)[1]
        data = await state.get_data()
        ad_id = int(data["edit_ad_id"])
        photos = ctx.db.ad_photos(ad_id)
        pending_photos: list[tuple[str, str, str]] = data.get("edit_added_photos", [])
        if action == "menu":
            await state.set_state(CreateAd.edit_photo_menu)
            await callback.message.answer("Изменить фото", reply_markup=edit_photo_menu())
        elif action == "add":
            if len(photos) + len(pending_photos) >= deps.MAX_SELL_PHOTOS:
                await callback.answer(f"Уже добавлено {deps.MAX_SELL_PHOTOS} фото.", show_alert=True)
                return
            await state.set_state(CreateAd.edit_add_photo)
            remaining = deps.MAX_SELL_PHOTOS - len(photos) - len(pending_photos)
            await callback.message.answer(f"Отправьте фото. Можно добавить еще {remaining}.")
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

    @router.message(StateFilter(CreateAd.edit_add_photo), F.photo)
    async def edit_add_photo(message: Message, state: FSMContext, bot: Bot) -> None:
        data = await state.get_data()
        ad_id = int(data["edit_ad_id"])
        photos = ctx.db.ad_photos(ad_id)
        pending_photos: list[tuple[str, str, str]] = data.get("edit_added_photos", [])
        if len(photos) + len(pending_photos) >= deps.MAX_SELL_PHOTOS:
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
        if deps.has_duplicate_in_batch([item[2] for item in pending_photos] + [image_hash]):
            await message.answer("Похожее фото уже добавлено в этом редактировании.")
            return
        duplicate_ad_id = ctx.db.find_duplicate_hash(message.from_user.id, [image_hash], ctx.settings.duplicate_photo_days)
        if duplicate_ad_id is not None:
            await message.answer("Похожее фото уже есть в вашем объявлении.")
            return
        pending_photos.append((photo.file_id, photo.file_unique_id, image_hash))
        await state.update_data(edit_added_photos=pending_photos)
        await state.set_state(CreateAd.edit_photo_menu)
        await message.answer("Фото добавлено. Оно появится после завершения редактирования.", reply_markup=edit_photo_menu())

    @router.callback_query(F.data.startswith("edit_photo_toggle:"))
    async def edit_photo_toggle(callback: CallbackQuery, state: FSMContext) -> None:
        if not await deps.ensure_private_callback(callback):
            return
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
        if not await deps.ensure_private_callback(callback):
            return
        data = await state.get_data()
        ad_id = int(data["edit_ad_id"])
        selected = list(data.get("edit_delete_selected", []))
        if not selected:
            await callback.answer("Выберите фото.", show_alert=True)
            return
        ctx.db.delete_ad_photos_by_indexes(ad_id, selected)
        await deps.republish_ad(callback.bot, ctx, ad_id)
        await state.set_state(CreateAd.edit_photo_menu)
        await callback.message.answer("Фото удалены. Изменить фото", reply_markup=edit_photo_menu())
        await callback.answer()

    @router.message(StateFilter(CreateAd.edit_price))
    async def edit_price(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if not text:
            await message.answer("Отправьте новую цену текстом.")
            return
        data = await state.get_data()
        ad_id = int(data["edit_ad_id"])
        ctx.db.update_ad_price(ad_id, text)
        await deps.refresh_known_messages(message.bot, ctx, ad_id)
        await message.answer("Цена обновлена.", reply_markup=edit_next_finish_keyboard("address"))

    @router.message(StateFilter(CreateAd.edit_address))
    async def edit_address(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if not text:
            await message.answer("Отправьте новый адрес текстом.")
            return
        data = await state.get_data()
        ad_id = int(data["edit_ad_id"])
        ctx.db.update_ad_address(ad_id, text)
        await deps.refresh_known_messages(message.bot, ctx, ad_id)
        await message.answer("Адрес обновлен.", reply_markup=edit_finish_keyboard())
