from __future__ import annotations

from aiogram import Router

from .create import register_create_handlers
from .edit import register_edit_handlers
from .release_reserve import register_release_reserve_handlers
from .remove import register_remove_handlers
from .reserve import register_reserve_handlers


def register_reply_menu_handlers(router: Router, ctx, deps) -> None:
    register_create_handlers(router, ctx, deps)
    register_reserve_handlers(router, ctx, deps)
    register_release_reserve_handlers(router, ctx, deps)
    register_remove_handlers(router, ctx, deps)
    register_edit_handlers(router, ctx, deps)
