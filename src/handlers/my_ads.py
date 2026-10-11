from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db import Ad, HistAd
from keyboards import BTN_MY_ADS, repost_ad_keyboard


def register_my_ads_handlers(router: Router, ctx, deps) -> None:
    @router.message(F.text == BTN_MY_ADS)
    async def my_ads(message: Message, state: FSMContext) -> None:
        if message.chat.type != "private" or message.from_user is None:
            return
        await deps.reset_sell_wizard(message.bot, message.chat.id, state)
        await show_my_ads(message, message.from_user.id)

    @router.callback_query(F.data.startswith("my_ads:repost:"))
    async def repost_archived_ad(callback: CallbackQuery) -> None:
        if not await deps.ensure_private_callback(callback):
            return
        hist_ad_id = int(callback.data.rsplit(":", 1)[1])
        status, ad_id = ctx.db.repost_hist_ad(hist_ad_id, callback.from_user.id, ctx.settings.repost_limit)
        if status == "not_found":
            await callback.answer("Архивное объявление не найдено.", show_alert=True)
            return
        if status == "not_repostable":
            await callback.answer("Повторно публиковать можно только объявления из архива по сроку.", show_alert=True)
            return
        if status == "limit":
            await callback.answer(
                f"Лимит повторных публикаций исчерпан: {ctx.settings.repost_limit}.",
                show_alert=True,
            )
            return
        if ad_id is None:
            await callback.answer("Не удалось опубликовать объявление.", show_alert=True)
            return
        await deps.publish_created_ad(callback.bot, callback.message, ctx, ad_id)
        await callback.answer("Объявление повторно опубликовано")

    async def show_my_ads(message: Message, user_id: int) -> None:
        active_ads = ctx.db.user_active_ads(user_id)
        hist_ads = ctx.db.user_hist_ads(user_id)
        if not active_ads and not hist_ads:
            await message.answer("У вас пока нет объявлений.", reply_markup=deps.private_main_menu(message))
            return
        await message.answer("Мои объявления", reply_markup=deps.private_main_menu(message))
        if active_ads:
            await message.answer("Активные:")
            for ad in active_ads:
                await send_active_ad(message, ad)
        if hist_ads:
            await message.answer("Архив:")
            for ad in hist_ads:
                await send_hist_ad(message, ad)

    async def send_active_ad(message: Message, ad: Ad) -> None:
        url = ad_public_url(ad.id, message.chat.id)
        caption = render_my_ad_caption(ad.id, ad.description, ad.price, ad.address, url=url)
        await message.answer(caption, parse_mode=ParseMode.HTML, disable_web_page_preview=False)

    async def send_hist_ad(message: Message, ad: HistAd) -> None:
        photos = ctx.db.hist_ad_photos(ad.id)
        caption = render_my_ad_caption(ad.ad_id, ad.description, ad.price, ad.address)
        reply_markup = repost_ad_keyboard(ad.id) if ad.remove_reason == "retention" else None
        if photos:
            await message.answer_photo(
                photos[0],
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
            return
        await message.answer(caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

    def ad_public_url(ad_id: int, private_chat_id: int) -> str | None:
        messages = ctx.db.ad_messages(ad_id)
        if not messages:
            return None
        publication_chat_id = ctx.settings.publication_chat_id
        if isinstance(publication_chat_id, int):
            saved_message = next((item for item in messages if item.chat_id == publication_chat_id), None)
            if saved_message is None:
                return None
            if str(publication_chat_id).startswith("-100"):
                return f"https://t.me/c/{str(publication_chat_id)[4:]}/{saved_message.message_id}"
            return None
        if isinstance(publication_chat_id, str):
            saved_message = next((item for item in messages if item.chat_id != private_chat_id), None)
            if saved_message is None:
                return None
            username = publication_chat_id.lstrip("@")
            if username:
                return f"https://t.me/{username}/{saved_message.message_id}"
        return None


def render_my_ad_caption(
    ad_id: int,
    description: str,
    price: str | None,
    address: str | None,
    url: str | None = None,
) -> str:
    number = f"Номер объявления: #{ad_id}"
    if url:
        number += f" {html.escape(url)}"
    parts = [
        number,
        f"Описание: {html.escape(description)}",
    ]
    if price:
        parts.append(f"Цена: {html.escape(price)}")
    if address:
        parts.append(f"Адрес: {html.escape(address)}")
    return "\n".join(parts)
