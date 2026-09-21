from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from keyboards import BTN_RESERVE


def register_reserve_handlers(router: Router, ctx, deps) -> None:
    CreateAd = deps.CreateAd

    @router.message(Command("reserve"))
    @router.message(F.text == BTN_RESERVE)
    async def reserve_by_number_start(message: Message, state: FSMContext) -> None:
        if message.chat.type != "private":
            return
        await state.set_state(CreateAd.reserve_number)
        await message.answer("Введите номер объявления.")

    @router.message(StateFilter(CreateAd.reserve_number))
    async def reserve_by_number(message: Message, state: FSMContext) -> None:
        ad = deps.ad_from_number_text(ctx, message.text or "")
        await state.clear()
        if ad is None:
            await message.answer("Объявление с таким номером не найдено.", reply_markup=deps.private_main_menu(message))
            return
        await deps.reserve_ad(message, ctx, ad)
