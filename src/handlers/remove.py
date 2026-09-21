from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from keyboards import BTN_REMOVE_AD, remove_reason_keyboard


def register_remove_handlers(router: Router, ctx, deps) -> None:
    CreateAd = deps.CreateAd

    @router.message(Command("remove"))
    @router.message(F.text == BTN_REMOVE_AD)
    async def remove_by_number_start(message: Message, state: FSMContext) -> None:
        if message.chat.type != "private":
            return
        await state.set_state(CreateAd.remove_ad_number)
        await message.answer("Введите номер объявления.")

    @router.message(StateFilter(CreateAd.remove_ad_number))
    async def remove_by_number(message: Message, state: FSMContext) -> None:
        ad = deps.ad_from_number_text(ctx, message.text or "")
        await state.clear()
        if ad is None or ad.status != "active":
            await message.answer("Объявление с таким номером не найдено.", reply_markup=deps.private_main_menu(message))
            return
        if not deps.can_remove_ad(ctx, message.from_user.id, ad):
            await message.answer(
                "Снять объявление может только автор или админ.",
                reply_markup=deps.private_main_menu(message),
            )
            return
        await message.answer("Укажите причину:", reply_markup=remove_reason_keyboard(ad.id, ad.ad_type))

    @router.callback_query(F.data.startswith("remove_start:"))
    async def remove_start(callback: CallbackQuery) -> None:
        if not await deps.ensure_private_callback(callback):
            return
        ad_id = int(callback.data.split(":", 1)[1])
        ad = ctx.db.get_ad(ad_id)
        if ad is None or not deps.can_remove_ad(ctx, callback.from_user.id, ad):
            await callback.answer("Это действие доступно только автору", show_alert=True)
            return
        await callback.message.answer("Укажите причину:", reply_markup=remove_reason_keyboard(ad_id, ad.ad_type))
        await callback.answer()

    @router.callback_query(F.data.startswith("remove_reason:"))
    async def remove_reason(callback: CallbackQuery) -> None:
        if not await deps.ensure_private_callback(callback):
            return
        _, ad_id_text, reason = callback.data.split(":", 2)
        ad_id = int(ad_id_text)
        ad = ctx.db.get_ad(ad_id)
        if ad is None or not deps.can_remove_ad(ctx, callback.from_user.id, ad):
            await callback.answer("Это действие доступно только автору", show_alert=True)
            return
        await deps.delete_known_messages(callback.bot, ctx, ad_id)
        ctx.db.mark_deleted(ad_id, reason)
        await callback.message.delete()
        await callback.message.answer("Объявление снято.", reply_markup=deps.private_main_menu(callback.message))
        await callback.answer("Объявление снято")
