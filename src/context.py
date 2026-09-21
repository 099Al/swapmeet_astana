from __future__ import annotations

from dataclasses import dataclass

from aiogram.fsm.state import State, StatesGroup

from config import Settings
from db import Database


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
