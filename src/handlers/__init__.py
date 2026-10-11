from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from .create import register_create_handlers
from .edit import register_edit_handlers
from .my_ads import register_my_ads_handlers
from .release_reserve import register_release_reserve_handlers
from .remove import register_remove_handlers
from .reserve import register_reserve_handlers
from keyboards import BTN_EDIT_AD, BTN_REMOVE_AD, BTN_RESERVE


def register_reply_menu_handlers(router: Router, ctx, deps) -> None:
    CreateAd = deps.CreateAd

    @router.message(F.text.in_({BTN_REMOVE_AD, BTN_EDIT_AD, BTN_RESERVE}))
    async def interrupt_with_menu_action(message: Message, state: FSMContext) -> None:
        if message.chat.type != "private":
            return
        await deps.reset_sell_wizard(message.bot, message.chat.id, state)
        if message.text == BTN_REMOVE_AD:
            await state.set_state(CreateAd.remove_ad_number)
            await message.answer("Введите номер объявления.")
        elif message.text == BTN_EDIT_AD:
            await state.set_state(CreateAd.edit_number)
            await message.answer("Укажите номер объявления.")
        elif message.text == BTN_RESERVE:
            await state.set_state(CreateAd.reserve_number)
            await message.answer("Введите номер объявления.")

    register_my_ads_handlers(router, ctx, deps)
    register_create_handlers(router, ctx, deps)
    register_reserve_handlers(router, ctx, deps)
    register_release_reserve_handlers(router, ctx, deps)
    register_remove_handlers(router, ctx, deps)
    register_edit_handlers(router, ctx, deps)
