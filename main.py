import flet as ft
import datetime
import asyncio
import json
import re
import inspect

PROJECT_ID = "ourshoppinglist-7e6c7"
API_KEY = "AIzaSyC5hpB-l_gLAAvH5hTDVobcHxu2x6Gju4I"
DB_URL = f"https://{PROJECT_ID}-default-rtdb.firebaseio.com"
AUTH_SIGNIN = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={API_KEY}"
AUTH_SIGNUP = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={API_KEY}"
AUTH_REFRESH = f"https://securetoken.googleapis.com/v1/token?key={API_KEY}"
_HTTP_CLIENT = None
_IS_WEB_RUNTIME = None
async def get_http_client():
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None or getattr(_HTTP_CLIENT, "is_closed", False):
        import httpx
        _HTTP_CLIENT = httpx.AsyncClient(
            headers={
                "Accept-Encoding": "identity",
                "Content-Type": "application/json"
            },
            timeout=20.0
        )
    return _HTTP_CLIENT
def is_web_runtime():
    global _IS_WEB_RUNTIME
    if _IS_WEB_RUNTIME is not None:
        return _IS_WEB_RUNTIME
    try:
        import pyodide  # noqa
        _IS_WEB_RUNTIME = True
    except Exception:
        _IS_WEB_RUNTIME = False
    return _IS_WEB_RUNTIME
async def request_json(method, url, payload=None):
    method = method.upper()
    if is_web_runtime():
        from pyodide.http import pyfetch
        headers = {
            "Content-Type": "application/json"
        }
        kwargs = {
            "method": method,
            "headers": headers
        }
        if payload is not None and method not in ["GET", "DELETE"]:
            kwargs["body"] = json.dumps(payload)
        response = await pyfetch(url, **kwargs)
        text = await response.string()
        if not text:
            return {}
        try:
            return json.loads(text)
        except Exception:
            return {
                "raw": text,
                "status": response.status
            }
    client = await get_http_client()
    if method == "GET":
        response = await client.get(url)
    elif method == "POST":
        response = await client.post(url, json=payload)
    elif method == "PUT":
        response = await client.put(url, json=payload)
    elif method == "PATCH":
        response = await client.patch(url, json=payload)
    elif method == "DELETE":
        response = await client.delete(url)
    else:
        raise ValueError(f"Unsupported method: {method}")
    if not response.text:
        return {}
    return response.json()
async def main(page: ft.Page):
    page.title = "荳比小窩購物清單"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.window_width = 720
    page.window_height = 850
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.scroll = ft.ScrollMode.AUTO
    page.padding = 0
    user_token = {"id": None, "refresh": None, "uid": None}
    prefs = ft.SharedPreferences()
    last_activity_at = {"value": datetime.datetime.now()}
    system_closed_by_idle = {"value": False}
    current_list = {"name": None}
    is_mobile_layout = {"value": False}

    # Extra top margin for mobile phones with notch / system status bar.
    # Increase this value if the top row is still covered.
    MOBILE_SAFE_TOP_PADDING = 56

    err_text = ft.Text(color="red", visible=False)
    email_in = ft.TextField(label="Email", width=300)
    pass_in = ft.TextField(label="密碼", password=True, width=300)
    login_button = ft.Button("登入", width=300)
    register_button = ft.Button("註冊", width=300)
    login_container = ft.Column(
        [
            ft.Text("荳比小窩購物清單", size=25, weight="bold"),
            email_in,
            pass_in,
            login_button,
            register_button,
            err_text
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        alignment=ft.MainAxisAlignment.CENTER
    )
    idle_container = ft.Column(
        visible=False,
        width=700,
        height=820,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        alignment=ft.MainAxisAlignment.CENTER,
        spacing=12,
        controls=[
            ft.Text("系統已進入省電休眠", size=24, weight="bold"),
            ft.Text("已停止自動同步與畫面更新，登入狀態仍保留。", size=15, color="grey"),
            ft.Button(
                "重新開啟",
                width=180,
                height=44,
                bgcolor="blue",
                color="white",
                on_click=lambda e: page.run_task(reopen_system_after_idle, e)
            )
        ]
    )
    page.add(login_container)
    page.add(idle_container)
    page.update()
    # Give mobile Flet/Flutter one frame to paint the login screen before preparing the rest.
    await asyncio.sleep(0.05)
    shopping_container = ft.Column(
        visible=False,
        width=700,
        height=820,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=8
    )
    home_list_view = ft.Column(
        scroll=ft.ScrollMode.AUTO,
        height=640,
        width=660,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=8
    )
    items_view = ft.Column(
        scroll=ft.ScrollMode.AUTO,
        height=650,
        width=340,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=6
    )
    list_name_input = ft.TextField(
        label="新清單名稱",
        width=300,
        hint_text="留空則使用今日日期"
    )
    current_selected_list_text = ft.Text(
        "請選擇清單",
        size=16,
        weight="bold",
        color="blue",
        text_align=ft.TextAlign.LEFT,
        max_lines=2,
        overflow=ft.TextOverflow.VISIBLE
    )
    # Keep the old Dropdown object for compatibility with existing cache/history code,
    # but use a TextField as the real desktop input because editable Dropdown
    # does not fire per-character events reliably in some Flet versions.
    item_dropdown = ft.Dropdown(
        label="輸入/選擇",
        width=200,
        height=50,
        menu_width=260,
        menu_height=260,
        editable=True,
        enable_filter=True,
        enable_search=True,
        text_style=ft.TextStyle(size=15, weight=ft.FontWeight.BOLD),
        label_style=ft.TextStyle(size=12),
        content_padding=ft.Padding.symmetric(horizontal=8, vertical=8),
        options=[],
    )
    desktop_item_input = ft.TextField(
        label="輸入/選擇",
        width=200,
        height=50,
        text_size=15,
        text_style=ft.TextStyle(weight=ft.FontWeight.BOLD),
        label_style=ft.TextStyle(size=12),
        content_padding=ft.Padding.symmetric(horizontal=8, vertical=8),
    )
    mobile_item_input = ft.TextField(
        label="輸入/選擇",
        width=200,
        height=50,
        text_size=15,
        text_style=ft.TextStyle(weight=ft.FontWeight.BOLD),
        label_style=ft.TextStyle(size=12),
        content_padding=ft.Padding.symmetric(horizontal=8, vertical=8),
        max_length=10,
    )
    mobile_item_button_label = ft.Text(
        "輸入/選擇",
        size=15,
        weight=ft.FontWeight.BOLD,
        color="grey",
        expand=True,
        max_lines=1,
        overflow=ft.TextOverflow.ELLIPSIS
    )
    mobile_item_button = ft.Container(
        width=200,
        height=50,
        padding=ft.Padding.symmetric(horizontal=10, vertical=8),
        border=ft.Border.all(1, "#BDBDBD"),
        border_radius=6,
        bgcolor="white",
        alignment=ft.Alignment.CENTER,
        on_click=lambda e: show_mobile_history_menu(e),
        content=ft.Row(
            [
                mobile_item_button_label,
                ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=20, color="grey")
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4
        )
    )
    history_suggestion_list = ft.Column(
        spacing=2,
        height=150,
        scroll=ft.ScrollMode.AUTO,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH
    )
    history_suggestion_panel = ft.Container(
        visible=False,
        width=200,
        height=158,
        padding=4,
        border=ft.Border.all(1, "#BDBDBD"),
        border_radius=8,
        bgcolor="white",
        content=history_suggestion_list
    )
    history_overlay_state = {"control": None}
    selected_item_text = ft.Text(
        "目前項目：\n尚未輸入",
        size=16,
        weight=ft.FontWeight.BOLD,
        text_align=ft.TextAlign.CENTER
    )

    def format_selected_item_text(item_name=None):
        item_name = str(item_name or "").strip()
        if item_name:
            return f"目前項目：\n{item_name}"
        return "目前項目：\n尚未輸入"
    def force_item_dropdown_menu_up():
        try:
            if hasattr(ft, "PopupMenuPosition") and hasattr(ft.PopupMenuPosition, "OVER"):
                item_dropdown.menu_position = ft.PopupMenuPosition.OVER
                return
        except Exception:
            pass
        for value in ["over", "above", "top"]:
            try:
                item_dropdown.menu_position = value
                return
            except Exception:
                pass
    main_qty_text = ft.Text(
        "1",
        size=18,
        weight="bold",
        width=32,
        text_align=ft.TextAlign.CENTER
    )
    quick_items = []
    history_name_set = set()
    history_names_cache = []
    item_input_source = {"from_quick": False, "suppress_change": False}
    list_names_cache = []
    list_items_cache = {}
    list_previews_cache = {}
    list_meta_cache = {}
    QUICK_ITEM_LIMIT = 100
    QUICK_NAME_MAX_LEN = 10
    ITEM_NAME_MAX_LEN = 10
    IDLE_CLOSE_SECONDS = 15 * 60
    HOME_CACHE_KEY = "shopping_home_cache_v3"
    HOME_SUMMARY_CACHE_KEY = "shopping_home_summary_cache_v1"
    ACTIVE_CURRENT_LIST_SYNC_SECONDS = 10
    ACTIVE_HOME_SYNC_SECONDS = 60
    ACTIVE_IDLE_CHECK_SECONDS = 60
    SLEEP_IDLE_CHECK_SECONDS = 300
    INPUT_LIMIT_CHECK_SECONDS = 0.25
    active_item_search_control = {"control": None}
    local_write_until = {"value": None}
    pending_deleted_local_items = set()
    manual_refreshing = {"value": False}
    current_list_auto_syncing = {"value": False}
    home_auto_syncing = {"value": False}
    quick_grid = ft.Column(
        width=235,
        height=260,
        scroll=ft.ScrollMode.AUTO,
        spacing=6,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER
    )
    quick_new_input = ft.TextField(
        label="新增快捷項目",
        width=200,
        height=54,
        text_size=16,
        label_style=ft.TextStyle(size=13),
        max_length=QUICK_NAME_MAX_LEN,
    )
    quick_edit_list = ft.Column(
        width=360,
        height=620,
        scroll=ft.ScrollMode.AUTO,
        spacing=4,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER
    )
    add_item_button = ft.Button(
        "➕ 加入",
        on_click=None,
        width=160,
        height=36,
        bgcolor="blue",
        color="white"
    )
    home_screen = None
    item_screen = None
    quick_edit_screen = None
    current_list_name_container = None
    item_qty_row_container = None
    item_input_container = None
    left_panel = None
    right_sidebar = None
    quick_section = None
    item_add_section = None
    main_ui_built = {"value": False}
    def make_option(text):
        return ft.dropdown.Option(text)
    def make_center_icon(icon, tooltip, on_click, width=32, height=32, icon_size=18, icon_color=None):
        return ft.IconButton(
            icon,
            tooltip=tooltip,
            width=width,
            height=height,
            icon_size=icon_size,
            icon_color=icon_color,
            style=ft.ButtonStyle(padding=ft.Padding(0, 0, 0, 0)),
            on_click=on_click
        )
    def set_error(message=""):
        err_text.value = message or ""
        err_text.visible = bool(err_text.value)

    def clear_error():
        set_error("")

    def update_error(message=""):
        set_error(message)
        page.update()

    def mark_user_activity(e=None):
        last_activity_at["value"] = datetime.datetime.now()

    def trim_item_name(value):
        return str(value or "").strip()[:ITEM_NAME_MAX_LEN]

    def limit_control_text(control, max_len=ITEM_NAME_MAX_LEN):
        """
        Hard limit TextField text while typing.
        If the user types or pastes more than max_len characters,
        the extra characters are removed immediately from the visible field.
        """
        if control is None:
            return False

        value = str(getattr(control, "value", "") or "")
        if len(value) <= max_len:
            return False

        control.value = value[:max_len]

        # Update this control immediately. page.update() alone may be too late
        # on some Flet mobile/web builds, so keep both fallbacks.
        try:
            control.update()
        except Exception:
            try:
                page.update()
            except Exception:
                pass

        return True

    def limit_item_dropdown_text(max_len=ITEM_NAME_MAX_LEN):
        """
        Hard limit the visible item input while typing.
        Desktop now uses desktop_item_input because Flet editable Dropdown
        may not report every keypress. The legacy Dropdown is still trimmed
        as a fallback.
        """
        changed = False

        if limit_control_text(desktop_item_input, max_len):
            changed = True

        # Legacy Dropdown fallback. Some Flet versions keep typed text in .text,
        # some in .value. These may only update on submit/blur, but trimming them
        # here keeps all internal values consistent.
        typed_text = str(getattr(item_dropdown, "text", "") or "")
        if len(typed_text) > max_len:
            try:
                item_dropdown.text = typed_text[:max_len]
                changed = True
            except Exception:
                pass

        selected_value = str(item_dropdown.value or "")
        if len(selected_value) > max_len:
            item_dropdown.value = selected_value[:max_len]
            changed = True

        if changed:
            try:
                item_dropdown.update()
            except Exception:
                pass

        return changed

    def limit_quick_new_input_now():
        return limit_control_text(quick_new_input, QUICK_NAME_MAX_LEN)

    def limit_active_search_input_now():
        control = active_item_search_control.get("control")
        if control is None:
            return False
        return limit_control_text(control, ITEM_NAME_MAX_LEN)

    def sync_all_item_input_values(value):
        value = trim_item_name(value)
        mobile_item_input.value = value
        desktop_item_input.value = value
        item_dropdown.value = value
        try:
            item_dropdown.text = value
        except Exception:
            pass
        update_mobile_item_button_label()
        return value

    def limit_all_typing_fields_now():
        # This is a safety net for controls whose on_change does not fire
        # on every keypress in older Flet builds. It is disabled during
        #省電休眠 by the loop caller.
        changed = False
        if limit_item_dropdown_text():
            changed = True
        if limit_control_text(mobile_item_input, ITEM_NAME_MAX_LEN):
            changed = True
        if limit_quick_new_input_now():
            changed = True
        if limit_active_search_input_now():
            changed = True
        return changed

    def make_unique_list_name(base_name, existing_names):
        final_name = base_name
        index = 1
        while final_name in existing_names:
            final_name = f"{base_name}({index})"
            index += 1
        return final_name
    def parse_datetime_sort_value(value):
        text = str(value or "")
        if not text:
            return 0.0
        try:
            return datetime.datetime.fromisoformat(text).timestamp()
        except Exception:
            return 0.0
    def get_list_created_sort_value(list_name, lists_raw=None, previews_raw=None):
        created_at = ""
        list_meta = None
        if isinstance(lists_raw, dict):
            list_meta = lists_raw.get(list_name)
        elif list_name in list_meta_cache:
            list_meta = list_meta_cache.get(list_name)
        if isinstance(list_meta, dict):
            created_at = list_meta.get("created_at", "") or list_meta.get("updated_at", "")
        if not created_at:
            preview_data = None
            if isinstance(previews_raw, dict):
                preview_data = previews_raw.get(list_name)
            elif list_name in list_previews_cache:
                preview_data = list_previews_cache.get(list_name)
            if isinstance(preview_data, dict):
                created_at = preview_data.get("created_at", "") or preview_data.get("updated_at", "")
        sort_value = parse_datetime_sort_value(created_at)
        if sort_value <= 0 and list_name in list_items_cache:
            item_times = [
                item_created_sort_value(item_data)
                for item_data in list_items_cache.get(list_name, {}).values()
                if isinstance(item_data, dict)
            ]
            if item_times:
                sort_value = max(item_times)
        return sort_value
    def sort_list_names_by_created(list_names, lists_raw=None, previews_raw=None):
        names = [name for name in list_names if name]
        has_manual_order = any(list_order_sort_value(name, lists_raw) is not None for name in names)
        if has_manual_order:
            return sorted(
                names,
                key=lambda name: (
                    list_order_sort_value(name, lists_raw)
                    if list_order_sort_value(name, lists_raw) is not None
                    else 999999.0,
                    -get_list_created_sort_value(name, lists_raw, previews_raw),
                    str(name)
                )
            )
        return sorted(
            names,
            key=lambda name: (
                get_list_created_sort_value(name, lists_raw, previews_raw),
                str(name)
            ),
            reverse=True
        )
    def resort_list_names(lists_raw=None, previews_raw=None):
        ordered = sort_list_names_by_created(list_names_cache, lists_raw, previews_raw)
        list_names_cache.clear()
        list_names_cache.extend(ordered)
    def make_list_metadata(created_at=None):
        now_text = datetime.datetime.now().isoformat()
        return {
            "active": True,
            "created_at": created_at or now_text,
            "updated_at": now_text
        }
    def get_numeric_order(value, default_value=999999.0):
        try:
            if value is None or value == "":
                return default_value
            return float(value)
        except Exception:
            return default_value
    def list_order_sort_value(list_name, lists_raw=None):
        list_meta = None
        if isinstance(lists_raw, dict):
            list_meta = lists_raw.get(list_name)
        elif list_name in list_meta_cache:
            list_meta = list_meta_cache.get(list_name)
        if isinstance(list_meta, dict) and "order" in list_meta:
            return get_numeric_order(list_meta.get("order"), 999999.0)
        return None
    def make_reorderable_list_view(controls, height, on_reorder):
        if not hasattr(ft, "ReorderableListView"):
            return None
        kwargs = {
            "controls": controls,
            "height": height,
            "spacing": 6,
            "on_reorder": on_reorder
        }
        for prop_name in ["show_default_drag_handles", "build_default_drag_handles"]:
            try:
                return ft.ReorderableListView(**kwargs, **{prop_name: False})
            except TypeError:
                continue
            except Exception:
                continue
        try:
            return ft.ReorderableListView(**kwargs)
        except Exception:
            return None
    def make_drag_handle(icon_size=22, tooltip="按住約 2 秒後拖拉排序"):
        content = ft.Icon(
            ft.Icons.DRAG_INDICATOR,
            size=icon_size,
            color="grey"
        )
        if hasattr(ft, "ReorderableDragHandle"):
            try:
                return ft.ReorderableDragHandle(
                    content=content,
                    tooltip=tooltip
                )
            except TypeError:
                try:
                    return ft.ReorderableDragHandle(content=content)
                except Exception:
                    pass
            except Exception:
                pass
        return content
    def normalize_reorder_new_index(old_index, new_index, item_count):
        try:
            old_index = int(old_index)
            new_index = int(new_index)
        except Exception:
            return None, None
        if old_index < 0 or old_index >= item_count:
            return None, None
        new_index = max(0, min(new_index, item_count - 1))
        return old_index, new_index
    def get_reorder_indices(e):
        old_index = getattr(e, "old_index", None)
        new_index = getattr(e, "new_index", None)
        for old_attr, new_attr in [
            ("oldIndex", "newIndex"),
            ("from_index", "to_index"),
            ("fromIndex", "toIndex"),
            ("from", "to"),
        ]:
            if old_index is None:
                old_index = getattr(e, old_attr, None)
            if new_index is None:
                new_index = getattr(e, new_attr, None)
        if old_index is not None and new_index is not None:
            return old_index, new_index
        data = getattr(e, "data", None)
        if isinstance(data, str) and data.strip():
            try:
                parsed = json.loads(data)
                if isinstance(parsed, dict):
                    old_index = parsed.get("old_index")
                    if old_index is None:
                        old_index = parsed.get("oldIndex", parsed.get("from_index", parsed.get("fromIndex", parsed.get("from"))))
                    new_index = parsed.get("new_index")
                    if new_index is None:
                        new_index = parsed.get("newIndex", parsed.get("to_index", parsed.get("toIndex", parsed.get("to"))))
                    if old_index is not None and new_index is not None:
                        return old_index, new_index
                elif isinstance(parsed, list) and len(parsed) >= 2:
                    return parsed[0], parsed[1]
            except Exception:
                parts = [part.strip() for part in data.replace(";", ",").split(",") if part.strip()]
                if len(parts) >= 2:
                    return parts[0], parts[1]
        return None, None
    def normalize_items(items_raw):
        if isinstance(items_raw, dict):
            return items_raw
        if isinstance(items_raw, list):
            return {
                str(i): v for i, v in enumerate(items_raw)
                if v and isinstance(v, dict)
            }
        return {}
    def merge_remote_items_with_local(list_name, remote_items):
        if not isinstance(remote_items, dict):
            return {}
        local_items = list_items_cache.get(list_name, {})
        if not isinstance(local_items, dict):
            local_items = {}
        merged_items = {}
        for item_id, remote_item in remote_items.items():
            if not isinstance(remote_item, dict):
                continue
            local_item = local_items.get(item_id, {})
            if isinstance(local_item, dict):
                merged = dict(local_item)
                merged.update(remote_item)
                if not merged.get("name") and local_item.get("name"):
                    merged["name"] = local_item.get("name")
                if not merged.get("qty") and local_item.get("qty"):
                    merged["qty"] = local_item.get("qty")
            else:
                merged = dict(remote_item)
            merged_items[item_id] = merged
        return merged_items
    def item_created_sort_value(item_data):
        created_at = str(item_data.get("created_at", "") or "")
        if not created_at:
            return 0.0
        try:
            return datetime.datetime.fromisoformat(created_at).timestamp()
        except Exception:
            return 0.0
    def sorted_item_entries(items):
        if not isinstance(items, dict):
            return []
        entries = [
            (item_id, item_data)
            for item_id, item_data in items.items()
            if isinstance(item_data, dict)
        ]
        has_manual_order = any("order" in item_data for _, item_data in entries)
        if has_manual_order:
            return sorted(
                entries,
                key=lambda x: (
                    bool(x[1].get("bought", False)),
                    get_numeric_order(x[1].get("order"), 999999.0),
                    -item_created_sort_value(x[1])
                )
            )
        return sorted(
            entries,
            key=lambda x: (
                bool(x[1].get("bought", False)),
                -item_created_sort_value(x[1])
            )
        )
    def refresh_history_dropdown_options():
        if is_mobile_layout["value"]:
            # Mobile uses a custom floating overlay. Keep native Dropdown options empty
            # so Flet will not reopen its built-in menu under the keyboard after typing.
            item_dropdown.options = []
        else:
            item_dropdown.options = [make_option(h) for h in reversed(history_names_cache[-100:])]
    def remove_history_overlay():
        ctrl = history_overlay_state.get("control")
        if ctrl is not None:
            try:
                if ctrl in page.overlay:
                    page.overlay.remove(ctrl)
            except Exception:
                try:
                    page.overlay.remove(ctrl)
                except Exception:
                    pass
        history_overlay_state["control"] = None
        active_item_search_control["control"] = None
    def hide_history_suggestions():
        history_suggestion_list.controls.clear()
        history_suggestion_panel.visible = False
        remove_history_overlay()
    def dismiss_history_overlay(e=None):
        hide_history_suggestions()
        page.update()
    def apply_history_suggestion(name):
        name = trim_item_name(name)
        if not name:
            return

        item_input_source["suppress_change"] = True
        sync_all_item_input_values(name)
        item_input_source["suppress_change"] = False
        item_input_source["from_quick"] = False

        selected_item_text.value = format_selected_item_text(name)
        update_mobile_item_button_label()
        hide_history_suggestions()
        page.update()

    def make_history_option_control(name, width):
        return ft.Container(
            width=max(80, width - 10),
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            border_radius=6,
            bgcolor="#F7F7F7",
            on_click=lambda e, n=name: apply_history_suggestion(n),
            content=ft.Text(
                name,
                size=15,
                weight=ft.FontWeight.BOLD,
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS
            )
        )
    def get_history_overlay_rect(panel_width, panel_height):
        screen_width = int(page.width or page.window_width or 720)
        screen_height = int(page.height or page.window_height or 850)
        safe_top = MOBILE_SAFE_TOP_PADDING if screen_width < 650 else 0

        # Put the floating history/search menu at the horizontal center near the
        # top of the screen. Add safe_top to avoid phone notch / status bar.
        left = max(6, int((screen_width - panel_width) / 2))
        top = safe_top + max(10, min(72, int(screen_height * 0.06)))

        if top + panel_height > screen_height - 8:
            top = max(safe_top + 8, screen_height - panel_height - 8)

        return left, top
    def update_history_suggestions(show_all=False):
        if not is_mobile_layout["value"]:
            hide_history_suggestions()
            force_item_dropdown_menu_up()
            return
        query = str(mobile_item_input.value or "").strip()
        query_lower = query.lower()
        matches = []
        seen = set()
        for history_name in reversed(history_names_cache[-100:]):
            item_name = str(history_name or "").strip()
            if not item_name or item_name in seen:
                continue
            if show_all or not query_lower or query_lower in item_name.lower():
                seen.add(item_name)
                matches.append(item_name)
            if len(matches) >= 8:
                break
        if not matches:
            hide_history_suggestions()
            return
        screen_width = int(page.width or page.window_width or 720)
        panel_width = min(360, max(240, screen_width - 32))
        row_height = 42
        panel_height = min(300, max(52, len(matches) * row_height + 12))
        option_list = ft.Column(
            spacing=2,
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[make_history_option_control(name, panel_width) for name in matches]
        )
        left, top = get_history_overlay_rect(panel_width, panel_height)
        overlay_panel = ft.Container(
            left=left,
            top=top,
            width=panel_width,
            height=panel_height,
            padding=4,
            border=ft.Border.all(1, "#BDBDBD"),
            border_radius=8,
            bgcolor="white",
            shadow=ft.BoxShadow(
                spread_radius=1,
                blur_radius=8,
                color="#55000000",
                offset=ft.Offset(0, 2)
            ),
            content=option_list
        )
        backdrop = ft.Container(
            left=0,
            top=0,
            width=screen_width,
            height=screen_height,
            bgcolor="#00000001",
            on_click=dismiss_history_overlay
        )
        overlay_root = ft.Container(
            width=screen_width,
            height=screen_height,
            content=ft.Stack(
                width=screen_width,
                height=screen_height,
                controls=[backdrop, overlay_panel]
            )
        )
        remove_history_overlay()
        history_overlay_state["control"] = overlay_root
        try:
            page.overlay.append(overlay_root)
        except Exception:
            history_suggestion_list.controls.clear()
            history_suggestion_list.controls.extend(option_list.controls)
            history_suggestion_panel.width = panel_width
            history_suggestion_panel.height = panel_height
            history_suggestion_panel.visible = True
        force_item_dropdown_menu_up()
    def set_history_names(history_keys):
        history_names_cache.clear()
        for name in history_keys:
            name = str(name or "").strip()
            if name and name not in history_names_cache:
                history_names_cache.append(name)
        refresh_history_dropdown_options()
    def add_history_name_local(name):
        name = str(name or "").strip()
        if not name:
            return
        if name in history_names_cache:
            history_names_cache.remove(name)
        history_names_cache.append(name)
        history_name_set.add(name)
        refresh_history_dropdown_options()
    def remove_history_name_local(name):
        name = str(name or "").strip()
        history_name_set.discard(name)
        if name in history_names_cache:
            history_names_cache.remove(name)
        refresh_history_dropdown_options()
    def update_mobile_item_button_label():
        value = trim_item_name(mobile_item_input.value)
        if value:
            mobile_item_button_label.value = value
            mobile_item_button_label.color = "black"
        else:
            mobile_item_button_label.value = "輸入/選擇"
            mobile_item_button_label.color = "grey"

    def get_item_dropdown_text():
        if is_mobile_layout["value"]:
            return trim_item_name(mobile_item_input.value)

        typed_text = trim_item_name(desktop_item_input.value)
        if typed_text:
            return typed_text

        legacy_typed_text = trim_item_name(getattr(item_dropdown, "text", "") or "")
        selected_value = trim_item_name(item_dropdown.value or "")
        if legacy_typed_text:
            return legacy_typed_text
        return selected_value

    def clear_item_dropdown():
        item_input_source["suppress_change"] = True
        mobile_item_input.value = ""
        desktop_item_input.value = ""
        item_dropdown.value = None
        try:
            item_dropdown.text = ""
        except Exception:
            pass
        item_input_source["suppress_change"] = False
        item_input_source["from_quick"] = False
        selected_item_text.value = format_selected_item_text()
        update_mobile_item_button_label()
        hide_history_suggestions()

    def update_selected_item_text():
        item_name = get_item_dropdown_text()
        if item_name:
            selected_item_text.value = format_selected_item_text(item_name)
        else:
            selected_item_text.value = format_selected_item_text()
        update_mobile_item_button_label()

    def on_item_dropdown_text_change(e):
        mark_user_activity()
        limit_item_dropdown_text()
        if not item_input_source["suppress_change"]:
            item_input_source["from_quick"] = False
        update_selected_item_text()
        refresh_history_dropdown_options()
        update_history_suggestions()
        page.update()

    def on_item_dropdown_select(e):
        mark_user_activity()
        limit_item_dropdown_text()
        if not item_input_source["suppress_change"]:
            item_input_source["from_quick"] = False
        update_selected_item_text()
        if is_mobile_layout["value"]:
            update_history_suggestions()
        else:
            hide_history_suggestions()
        page.update()

    def on_mobile_item_input_change(e):
        mark_user_activity()

        # Use e.control so the visible TextField is trimmed immediately.
        if e is not None and hasattr(e, "control"):
            limit_control_text(e.control)
        else:
            limit_control_text(mobile_item_input)

        if not item_input_source["suppress_change"]:
            item_input_source["from_quick"] = False

        update_selected_item_text()
        page.update()

    def on_quick_new_input_change(e):
        mark_user_activity()
        if e is not None and hasattr(e, "control"):
            limit_control_text(e.control, QUICK_NAME_MAX_LEN)
        else:
            limit_quick_new_input_now()
        page.update()

    def open_dialog_compat(dialog):
        try:
            if hasattr(page, "open"):
                page.open(dialog)
            else:
                page.dialog = dialog
                dialog.open = True
                page.update()
        except Exception:
            page.dialog = dialog
            dialog.open = True
            page.update()

    def close_dialog_compat(dialog):
        try:
            if hasattr(page, "close"):
                page.close(dialog)
            else:
                dialog.open = False
                page.dialog = dialog
                page.update()
        except Exception:
            dialog.open = False
            page.dialog = dialog
            page.update()

    def get_history_matches(query, limit=30):
        query = str(query or "").strip().lower()
        matches = []
        seen = set()

        for history_name in reversed(history_names_cache[-100:]):
            item_name = str(history_name or "").strip()
            if not item_name or item_name in seen:
                continue

            if not query or query in item_name.lower():
                seen.add(item_name)
                matches.append(item_name)

            if len(matches) >= limit:
                break

        return matches

    def show_mobile_history_menu(e=None):
        mark_user_activity()
        remove_history_overlay()

        screen_width = int(page.width or page.window_width or 720)
        screen_height = int(page.height or page.window_height or 850)

        panel_width = min(360, max(260, screen_width - 32))
        row_height = 44
        visible_rows = 5
        result_height = row_height * visible_rows + 8
        panel_height = 56 + result_height + 48

        safe_top = MOBILE_SAFE_TOP_PADDING if screen_width < 650 else 0

        left = max(8, int((screen_width - panel_width) / 2))
        top = safe_top + max(12, min(72, int(screen_height * 0.06)))

        search_field = ft.TextField(
            label="搜尋或輸入新項目",
            value=get_item_dropdown_text(),
            autofocus=True,
            width=panel_width - 24,
            height=50,
            text_size=16,
            text_style=ft.TextStyle(weight=ft.FontWeight.BOLD),
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=8),
        )

        active_item_search_control["control"] = search_field

        result_list = ft.Column(
            spacing=3,
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH
        )

        def set_mobile_item_value(value):
            value = trim_item_name(value)
            if not value:
                return

            item_input_source["suppress_change"] = True
            sync_all_item_input_values(value)
            item_input_source["suppress_change"] = False
            item_input_source["from_quick"] = False
            selected_item_text.value = format_selected_item_text(value)
            update_mobile_item_button_label()
            remove_history_overlay()
            page.update()

        def make_floating_history_option(name):
            return ft.Container(
                width=panel_width - 24,
                height=row_height,
                padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                border=ft.Border.all(1, "#E0E0E0"),
                border_radius=8,
                bgcolor="#F7F7F7",
                on_click=lambda e, n=name: set_mobile_item_value(n),
                content=ft.Text(
                    name,
                    size=16,
                    weight=ft.FontWeight.BOLD,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS
                )
            )

        def refresh_floating_history(e=None):
            mark_user_activity()

            # Hard trim the floating mobile search box immediately while typing.
            if e is not None and hasattr(e, "control"):
                limit_control_text(e.control)
            else:
                limit_control_text(search_field)

            query = trim_item_name(search_field.value)
            matches = get_history_matches(query, limit=100)

            result_list.controls.clear()
            if matches:
                result_list.controls.extend([
                    make_floating_history_option(name)
                    for name in matches
                ])
            else:
                result_list.controls.append(
                    ft.Container(
                        width=panel_width - 24,
                        height=row_height,
                        alignment=ft.Alignment.CENTER,
                        content=ft.Text("沒有符合的歷史紀錄", size=14, color="grey")
                    )
                )

            try:
                page.update()
            except Exception:
                pass

        def use_typed_text(e=None):
            mark_user_activity()
            limit_control_text(search_field)
            set_mobile_item_value(search_field.value)

        search_field.on_change = refresh_floating_history
        search_field.on_submit = use_typed_text

        panel = ft.Container(
            left=left,
            top=top,
            width=panel_width,
            height=panel_height,
            padding=8,
            border=ft.Border.all(1, "#BDBDBD"),
            border_radius=12,
            bgcolor="white",
            shadow=ft.BoxShadow(
                spread_radius=1,
                blur_radius=10,
                color="#66000000",
                offset=ft.Offset(0, 3)
            ),
            content=ft.Column(
                [
                    search_field,
                    ft.Container(
                        width=panel_width - 20,
                        height=result_height,
                        content=result_list
                    ),
                    ft.Row(
                        [
                            ft.TextButton(
                                "新增",
                                on_click=use_typed_text,
                                style=ft.ButtonStyle(
                                    text_style=ft.TextStyle(size=17, weight=ft.FontWeight.BOLD)
                                )
                            ),
                            ft.TextButton(
                                "取消",
                                on_click=lambda e: dismiss_history_overlay(e),
                                style=ft.ButtonStyle(
                                    text_style=ft.TextStyle(size=17, weight=ft.FontWeight.BOLD)
                                )
                            )
                        ],
                        alignment=ft.MainAxisAlignment.END,
                        spacing=6
                    )
                ],
                spacing=5,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER
            )
        )

        backdrop = ft.Container(
            left=0,
            top=0,
            width=screen_width,
            height=screen_height,
            bgcolor="#00000001",
            on_click=dismiss_history_overlay
        )

        overlay_root = ft.Container(
            width=screen_width,
            height=screen_height,
            content=ft.Stack(
                width=screen_width,
                height=screen_height,
                controls=[backdrop, panel]
            )
        )

        history_overlay_state["control"] = overlay_root
        page.overlay.append(overlay_root)
        refresh_floating_history()
        page.update()
    def decrease_main_qty(e):
        mark_user_activity()
        try:
            qty = int(main_qty_text.value)
        except Exception:
            qty = 1
        if qty > 1:
            main_qty_text.value = str(qty - 1)
        page.update()
    def increase_main_qty(e):
        mark_user_activity()
        try:
            qty = int(main_qty_text.value)
        except Exception:
            qty = 1
        main_qty_text.value = str(qty + 1)
        page.update()
    if hasattr(item_dropdown, "on_text_change"):
        item_dropdown.on_text_change = on_item_dropdown_text_change
    if hasattr(item_dropdown, "on_select"):
        item_dropdown.on_select = on_item_dropdown_select
    if hasattr(item_dropdown, "on_change"):
        item_dropdown.on_change = on_item_dropdown_select
    if hasattr(item_dropdown, "on_focus"):
        item_dropdown.on_focus = show_mobile_history_menu

    desktop_item_input.on_change = on_item_dropdown_text_change
    desktop_item_input.on_focus = show_mobile_history_menu
    desktop_item_input.on_submit = lambda e: page.run_task(add_item_final, e)
    try:
        desktop_item_input.on_click = show_mobile_history_menu
    except Exception:
        pass
    try:
        desktop_item_input.on_tap = show_mobile_history_menu
    except Exception:
        pass

    mobile_item_input.on_change = on_mobile_item_input_change
    mobile_item_input.on_focus = show_mobile_history_menu
    # Some Flet/Web builds do not bubble TextField taps to the parent GestureDetector.
    # Keep both handlers so the history popup opens from focus or a direct tap.
    try:
        mobile_item_input.on_click = show_mobile_history_menu
    except Exception:
        pass
    try:
        mobile_item_input.on_tap = show_mobile_history_menu
    except Exception:
        pass
    def scroll_items_to_top():
        async def do_scroll():
            try:
                result = items_view.scroll_to(offset=0, duration=250)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                pass
        try:
            page.run_task(do_scroll)
        except Exception:
            pass
    def show_home_screen(e=None):
        mark_user_activity()
        home_screen.visible = True
        item_screen.visible = False
        quick_edit_screen.visible = False
        render_home_lists()
        page.update()
    def show_item_screen(list_name):
        mark_user_activity()
        current_list["name"] = list_name
        current_selected_list_text.value = list_name
        try:
            set_current_list_title_view()
        except Exception:
            pass
        home_screen.visible = False
        item_screen.visible = True
        quick_edit_screen.visible = False
        if list_name in list_items_cache:
            render_items_from_cache(list_name)
            page.update()
        else:
            items_view.controls.clear()
            items_view.controls.append(
                ft.Text("載入中...", color="grey")
            )
            page.update()
            page.run_task(fetch_items, list_name, True)
    def show_quick_edit_screen(e=None):
        mark_user_activity()
        refresh_quick_edit_list()
        home_screen.visible = False
        item_screen.visible = False
        quick_edit_screen.visible = True
        page.update()
    def back_from_quick_edit(e=None):
        mark_user_activity()
        quick_edit_screen.visible = False
        if current_list["name"]:
            item_screen.visible = True
        else:
            home_screen.visible = True
        page.update()
    def build_preview_data_from_items(items):
        preview = []
        has_more = False
        for _, item_data in sorted_item_entries(items):
            if item_data.get("bought", False):
                continue
            name = item_data.get("name", "未命名")
            qty = item_data.get("qty", "1")
            text = f"{name} x{qty}"
            if len(preview) < 5:
                preview.append(text)
            else:
                has_more = True
                break
        return {
            "items": preview,
            "has_more": has_more,
            "updated_at": datetime.datetime.now().isoformat()
        }
    def update_preview_cache(list_name, items=None):
        if not list_name:
            return None
        if items is None:
            items = list_items_cache.get(list_name, {})
        preview_data = build_preview_data_from_items(items)
        list_previews_cache[list_name] = preview_data
        return preview_data
    def normalize_preview_data(preview_raw):
        if not isinstance(preview_raw, dict):
            return None
        raw_items = preview_raw.get("items")
        if raw_items is None:
            raw_items = preview_raw.get("preview", [])
        preview_items = []
        if isinstance(raw_items, list):
            for item in raw_items[:5]:
                if isinstance(item, str):
                    preview_items.append(item)
                elif isinstance(item, dict):
                    name = item.get("name", "未命名")
                    qty = item.get("qty", "1")
                    preview_items.append(f"{name} x{qty}")
        return {
            "items": preview_items,
            "has_more": bool(preview_raw.get("has_more", False)),
            "updated_at": preview_raw.get("updated_at", "")
        }

    def build_home_summary_cache_payload():
        # Small startup cache. Keep this lightweight so the phone can draw the
        # home screen before Firebase finishes refreshing.
        return {
            "list_names": list(list_names_cache),
            "list_meta": {
                name: dict(meta) if isinstance(meta, dict) else {"active": True}
                for name, meta in list_meta_cache.items()
            },
            "list_previews": {
                name: dict(preview) if isinstance(preview, dict) else preview
                for name, preview in list_previews_cache.items()
            },
            "quick_items": list(quick_items[:QUICK_ITEM_LIMIT]),
            "history_names": list(history_names_cache[-100:]),
            "updated_at": datetime.datetime.now().isoformat()
        }

    def build_home_cache_payload():
        # Full local cache. This is saved for offline / later list entry use,
        # but startup reads the smaller summary cache first to avoid slow first paint.
        payload = build_home_summary_cache_payload()
        payload["list_items"] = {
            list_name: {
                item_id: dict(item_data) if isinstance(item_data, dict) else item_data
                for item_id, item_data in items.items()
                if isinstance(items, dict)
            }
            for list_name, items in list_items_cache.items()
            if isinstance(items, dict)
        }
        return payload

    async def save_home_summary_cache_local():
        try:
            await prefs.set(
                HOME_SUMMARY_CACHE_KEY,
                json.dumps(build_home_summary_cache_payload(), ensure_ascii=False)
            )
        except Exception as ex:
            print(f"首頁摘要快取儲存失敗: {repr(ex)}")

    async def save_home_cache_local():
        # Save summary first; this is what startup reads immediately.
        await save_home_summary_cache_local()
        try:
            await prefs.set(
                HOME_CACHE_KEY,
                json.dumps(build_home_cache_payload(), ensure_ascii=False)
            )
        except Exception as ex:
            print(f"完整清單快取儲存失敗: {repr(ex)}")

    def apply_home_cache_payload(cache_payload, include_items=True):
        if not isinstance(cache_payload, dict):
            return False

        cached_names = cache_payload.get("list_names", [])
        if not isinstance(cached_names, list):
            cached_names = []

        cached_meta = cache_payload.get("list_meta", {})
        if not isinstance(cached_meta, dict):
            cached_meta = {}

        cached_previews = cache_payload.get("list_previews", {})
        if not isinstance(cached_previews, dict):
            cached_previews = {}

        list_names_cache.clear()
        for name in cached_names:
            name = str(name or "").strip()
            if name and name not in list_names_cache:
                list_names_cache.append(name)

        list_meta_cache.clear()
        for name, meta in cached_meta.items():
            name = str(name or "").strip()
            if not name:
                continue
            if isinstance(meta, dict):
                list_meta_cache[name] = dict(meta)
            else:
                list_meta_cache[name] = {"active": True}

        list_previews_cache.clear()
        for name, preview in cached_previews.items():
            name = str(name or "").strip()
            if not name:
                continue
            normalized_preview = normalize_preview_data(preview)
            if normalized_preview is not None:
                list_previews_cache[name] = normalized_preview

        if include_items:
            cached_items = cache_payload.get("list_items", {})
            if not isinstance(cached_items, dict):
                cached_items = {}
            list_items_cache.clear()
            for name, items in cached_items.items():
                name = str(name or "").strip()
                if not name or not isinstance(items, dict):
                    continue
                normalized_items = normalize_items(items)
                list_items_cache[name] = normalized_items
                if name not in list_previews_cache:
                    update_preview_cache(name, normalized_items)

        cached_history = cache_payload.get("history_names", [])
        if not isinstance(cached_history, list):
            cached_history = []
        history_keys = []
        for name in cached_history:
            name = str(name or "").strip()
            if name and name not in history_keys:
                history_keys.append(name[:ITEM_NAME_MAX_LEN])
        history_name_set.clear()
        history_name_set.update(history_keys)
        set_history_names(history_keys)

        cached_quick = cache_payload.get("quick_items", [])
        if not isinstance(cached_quick, list):
            cached_quick = []
        quick_items.clear()
        for name in cached_quick:
            name = str(name or "").strip()[:QUICK_NAME_MAX_LEN]
            if name and name not in quick_items:
                quick_items.append(name)
            if len(quick_items) >= QUICK_ITEM_LIMIT:
                break

        return bool(list_names_cache or list_previews_cache or list_items_cache or quick_items or history_keys)

    async def read_json_pref(key):
        try:
            if not await prefs.contains_key(key):
                return None
            raw_cache = await prefs.get(key)
            if not raw_cache:
                return None
            if isinstance(raw_cache, str):
                return json.loads(raw_cache)
            if isinstance(raw_cache, dict):
                return raw_cache
        except Exception as ex:
            print(f"快取讀取失敗 {key}: {repr(ex)}")
        return None

    async def load_home_summary_cache_local():
        # Fast path used at app startup. Do not read the large full-list blob here.
        cache_payload = await read_json_pref(HOME_SUMMARY_CACHE_KEY)
        if not cache_payload:
            return False
        if not apply_home_cache_payload(cache_payload, include_items=False):
            return False
        refresh_quick_ui()
        render_home_lists()
        page.update()
        return True

    async def load_full_home_cache_local(render_after=True):
        cache_payload = await read_json_pref(HOME_CACHE_KEY)
        if not cache_payload:
            return False
        if not apply_home_cache_payload(cache_payload, include_items=True):
            return False
        refresh_quick_ui()
        if render_after:
            if current_list["name"] and item_screen and item_screen.visible:
                render_items_from_cache(current_list["name"])
            elif home_screen and home_screen.visible:
                render_home_lists()
            page.update()
        return True

    async def load_home_cache_local():
        # Backward-compatible wrapper for existing calls.
        if await load_home_summary_cache_local():
            return True
        return await load_full_home_cache_local(render_after=True)

    def apply_metadata_payload(meta):
        if not isinstance(meta, dict):
            meta = {}

        lists_raw = meta.get("lists", {})
        if not isinstance(lists_raw, dict):
            lists_raw = {}

        previews_raw = meta.get("list_previews", {})
        if not isinstance(previews_raw, dict):
            previews_raw = {}

        list_previews_cache.clear()
        for preview_name, preview_data in previews_raw.items():
            normalized_preview = normalize_preview_data(preview_data)
            if normalized_preview is not None:
                list_previews_cache[preview_name] = normalized_preview

        list_meta_cache.clear()
        for list_name, list_meta in lists_raw.items():
            if isinstance(list_meta, dict):
                list_meta_cache[list_name] = dict(list_meta)
            else:
                list_meta_cache[list_name] = {"active": True}

        list_names_cache.clear()
        list_names_cache.extend(sort_list_names_by_created(lists_raw.keys(), lists_raw, previews_raw))

        history_raw = meta.get("history", {})
        if not isinstance(history_raw, dict):
            history_raw = {}
        history_keys = [
            h for h in history_raw.keys()
            if h not in ["True", "{'active': True}"]
        ]
        history_name_set.clear()
        history_name_set.update(history_keys)
        set_history_names(history_keys)

        quick_raw = meta.get("quick_items", [])
        quick_items.clear()
        if isinstance(quick_raw, list):
            for q in quick_raw:
                if isinstance(q, str) and q.strip():
                    quick_items.append(q.strip()[:QUICK_NAME_MAX_LEN])
        elif isinstance(quick_raw, dict):
            for q in quick_raw.keys():
                if isinstance(q, str) and q.strip():
                    quick_items.append(q.strip()[:QUICK_NAME_MAX_LEN])
        del quick_items[QUICK_ITEM_LIMIT:]

    def apply_all_shopping_lists_payload(shopping_lists_raw, valid_names=None):
        """
        Apply full Firebase /shopping_lists data to local cache.
        This keeps the home page able to show unchecked items from complete lists,
        while startup can still display the previous local cache immediately.
        """
        if not isinstance(shopping_lists_raw, dict):
            shopping_lists_raw = {}

        valid_set = None
        if valid_names is not None:
            valid_set = {str(name) for name in valid_names if str(name or "").strip()}

        if valid_set is None:
            candidate_names = set(shopping_lists_raw.keys())
            candidate_names.update(list_names_cache)
        else:
            candidate_names = set(valid_set)

        # Remove stale local item caches that no longer exist in metadata.
        if valid_set is not None:
            for cached_name in list(list_items_cache.keys()):
                if cached_name not in valid_set:
                    list_items_cache.pop(cached_name, None)
                    list_previews_cache.pop(cached_name, None)

        for list_name in candidate_names:
            raw_items = shopping_lists_raw.get(list_name, {})
            normalized = normalize_items(raw_items)
            list_items_cache[list_name] = normalized
            update_preview_cache(list_name, normalized)

    async def fetch_full_shopping_lists_remote(render_after=True, save_cache=True):
        if not user_token["id"]:
            return False
        try:
            shopping_lists_raw = await request_json(
                "GET",
                f"{DB_URL}/shopping_lists.json?auth={user_token['id']}"
            )
            apply_all_shopping_lists_payload(shopping_lists_raw, set(list_names_cache))
            if render_after and home_screen and home_screen.visible:
                render_home_lists()
                page.update()
            if save_cache:
                await save_home_cache_local()
            return True
        except Exception as ex:
            print(f"完整清單讀取失敗: {repr(ex)}")
            return False

    async def save_all_list_previews_remote():
        if not user_token["id"]:
            return
        preview_payload = {
            list_name: build_preview_data_from_items(items)
            for list_name, items in list_items_cache.items()
            if isinstance(items, dict)
        }
        if not preview_payload:
            return
        try:
            await request_json(
                "PUT",
                f"{DB_URL}/metadata/list_previews.json?auth={user_token['id']}",
                preview_payload
            )
        except Exception as ex:
            print(f"清單預覽批次儲存失敗: {repr(ex)}")

    async def save_list_preview_remote(list_name, items=None):
        if not user_token["id"] or not list_name:
            return
        preview_data = update_preview_cache(list_name, items)
        try:
            await request_json(
                "PUT",
                f"{DB_URL}/metadata/list_previews/{list_name}.json?auth={user_token['id']}",
                preview_data
            )
        except Exception as ex:
            print(f"清單預覽儲存失敗: {repr(ex)}")
    def refresh_home_preview_after_local_change(list_name, save_remote=True):
        update_preview_cache(list_name)
        if home_screen and home_screen.visible:
            render_home_lists()
        page.run_task(save_home_cache_local)
        if save_remote and user_token["id"]:
            page.run_task(save_list_preview_remote, list_name)
    def get_unchecked_preview(list_name):
        if list_name in list_items_cache:
            preview_data = build_preview_data_from_items(list_items_cache.get(list_name, {}))
            return preview_data["items"], preview_data["has_more"], True
        preview_data = normalize_preview_data(list_previews_cache.get(list_name))
        if preview_data is not None:
            return preview_data["items"], preview_data["has_more"], True
        return [], False, False
    home_preview_fetching = {"value": False}
    async def fetch_missing_home_previews(names=None):
        # Home page needs unchecked item previews, but avoid one request per list.
        # Fetch the complete shopping_lists tree once, then rebuild previews locally.
        if home_preview_fetching["value"]:
            return
        if not user_token["id"]:
            return
        home_preview_fetching["value"] = True
        try:
            await fetch_full_shopping_lists_remote(render_after=True, save_cache=True)
        finally:
            home_preview_fetching["value"] = False
    async def delete_home_list(list_name):
        mark_user_activity()
        if not list_name:
            return
        if list_name in list_names_cache:
            list_names_cache.remove(list_name)
        mark_local_write()
        list_items_cache.pop(list_name, None)
        list_previews_cache.pop(list_name, None)
        list_meta_cache.pop(list_name, None)
        if current_list["name"] == list_name:
            current_list["name"] = None
        clear_error()
        render_home_lists()
        page.update()
        page.run_task(delete_list_remote, list_name)
    def set_current_list_title_view():
        """Restore the current list title to the normal double-click rename view."""
        if current_list_name_container is None:
            return

        current_list_name_container.content = ft.GestureDetector(
            on_double_tap=lambda e: ask_rename_list(current_list["name"]),
            content=current_selected_list_text
        )

    def mark_local_write(seconds=3.0):
        local_write_until["value"] = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
    def is_local_write_active():
        value = local_write_until.get("value")
        return bool(value and datetime.datetime.now() < value)
    def make_copied_list_name(list_name, existing_names):
        match = re.match(r"^(.*?)(?:\((\d+)\))?$", str(list_name or "").strip())
        base_name = match.group(1) if match else str(list_name or "").strip()
        start_index = int(match.group(2) or 0) + 1 if match else 1
        index = start_index
        while True:
            candidate = f"{base_name}({index})"
            if candidate not in existing_names:
                return candidate
            index += 1
    async def rename_list(old_name, new_name):
        new_name = (new_name or "").strip()
        if not old_name:
            return
        if not new_name:
            set_error("❌ 清單名稱不可空白")
            page.update()
            return
        if new_name == old_name:
            return
        if new_name in list_names_cache:
            set_error("❌ 清單名稱已存在")
            page.update()
            return
        backup_list_names = list(list_names_cache)
        backup_current_name = current_list["name"]
        backup_old_items = list_items_cache.get(old_name)
        backup_new_items = list_items_cache.get(new_name)
        backup_old_preview = list_previews_cache.get(old_name)
        backup_new_preview = list_previews_cache.get(new_name)
        backup_old_meta = list_meta_cache.get(old_name)
        backup_new_meta = list_meta_cache.get(new_name)
        old_items = list_items_cache.get(old_name)
        if old_items is None:
            old_items = {}
        mark_local_write(6.0)
        if old_name in list_names_cache:
            list_names_cache.remove(old_name)
        if new_name not in list_names_cache:
            list_names_cache.append(new_name)
        resort_list_names()
        list_items_cache.pop(old_name, None)
        list_items_cache[new_name] = old_items
        old_preview = list_previews_cache.pop(old_name, None)
        list_previews_cache[new_name] = old_preview or build_preview_data_from_items(old_items)
        old_meta = list_meta_cache.pop(old_name, None)
        if isinstance(old_meta, dict):
            new_meta = dict(old_meta)
            new_meta["updated_at"] = datetime.datetime.now().isoformat()
        else:
            new_meta = make_list_metadata()
        list_meta_cache[new_name] = new_meta
        promote_list_to_top_local(new_name)
        if current_list["name"] == old_name:
            current_list["name"] = new_name
            current_selected_list_text.value = new_name
            set_current_list_title_view()
        clear_error()
        render_home_lists()
        if current_list["name"] == new_name:
            render_items_from_cache(new_name)
        page.update()
        try:
            if backup_old_items is None:
                items_raw = await request_json(
                    "GET",
                    f"{DB_URL}/shopping_lists/{old_name}.json?auth={user_token['id']}"
                )
                old_items = normalize_items(items_raw)
                list_items_cache[new_name] = old_items
            mark_local_write(6.0)
            await asyncio.gather(
                request_json(
                    "PATCH",
                    f"{DB_URL}/metadata/lists.json?auth={user_token['id']}",
                    {new_name: list_meta_cache.get(new_name) or make_list_metadata()}
                ),
                request_json(
                    "PUT",
                    f"{DB_URL}/shopping_lists/{new_name}.json?auth={user_token['id']}",
                    old_items
                ),
                request_json(
                    "PUT",
                    f"{DB_URL}/metadata/list_previews/{new_name}.json?auth={user_token['id']}",
                    build_preview_data_from_items(old_items)
                )
            )
            await asyncio.gather(
                request_json(
                    "DELETE",
                    f"{DB_URL}/metadata/lists/{old_name}.json?auth={user_token['id']}"
                ),
                request_json(
                    "DELETE",
                    f"{DB_URL}/shopping_lists/{old_name}.json?auth={user_token['id']}"
                ),
                request_json(
                    "DELETE",
                    f"{DB_URL}/metadata/list_previews/{old_name}.json?auth={user_token['id']}"
                )
            )
            mark_local_write(2.0)
            page.run_task(save_list_order_remote)
        except Exception as ex:
            list_names_cache.clear()
            list_names_cache.extend(backup_list_names)
            list_items_cache.pop(new_name, None)
            list_previews_cache.pop(new_name, None)
            list_meta_cache.pop(new_name, None)
            if backup_old_items is not None:
                list_items_cache[old_name] = backup_old_items
            if backup_new_items is not None:
                list_items_cache[new_name] = backup_new_items
            if backup_old_preview is not None:
                list_previews_cache[old_name] = backup_old_preview
            if backup_new_preview is not None:
                list_previews_cache[new_name] = backup_new_preview
            if backup_old_meta is not None:
                list_meta_cache[old_name] = backup_old_meta
            if backup_new_meta is not None:
                list_meta_cache[new_name] = backup_new_meta
            current_list["name"] = backup_current_name
            current_selected_list_text.value = backup_current_name or "請選擇清單"
            set_current_list_title_view()
            set_error(f"❌ 改名失敗: {repr(ex)}")
            render_home_lists()
            if current_list["name"]:
                render_items_from_cache(current_list["name"])
            page.update()
    def ask_rename_list(list_name):
        mark_user_activity()

        list_name = (list_name or "").strip()
        if not list_name:
            return

        # Keep one edit session state inside this function. It lets the blur
        # handler cancel only the current edit box, without breaking V / X clicks.
        edit_state = {
            "active": True,
            "button_clicked": False
        }

        field_width = int(current_list_name_container.width or 220) - 72
        field_width = max(90, field_width)

        rename_field = ft.TextField(
            value=list_name,
            width=field_width,
            height=34,
            text_size=14,
            autofocus=True,
            dense=True,
            content_padding=ft.Padding.symmetric(horizontal=8, vertical=0)
        )

        def restore_title_view(update_page=True):
            if not edit_state["active"]:
                return

            edit_state["active"] = False
            current_selected_list_text.value = current_list["name"] or list_name
            set_current_list_title_view()

            if update_page:
                page.update()

        def cancel_inline_rename(e=None):
            mark_user_activity()
            edit_state["button_clicked"] = True
            restore_title_view(update_page=True)

        async def save_inline_rename(e=None):
            mark_user_activity()
            edit_state["button_clicked"] = True
            new_value = (rename_field.value or "").strip()

            # Return to normal title view first, then run the Firebase rename flow.
            restore_title_view(update_page=True)
            await rename_list(list_name, new_value)

        async def cancel_inline_rename_on_blur(e=None):
            # When the user taps V / X, the TextField usually loses focus first.
            # Wait briefly so the button click can set button_clicked=True.
            await asyncio.sleep(0.20)

            if not edit_state["active"]:
                return

            if edit_state["button_clicked"]:
                return

            # Clicking anywhere except the field / V / X has the same effect as X.
            restore_title_view(update_page=True)

        def make_rename_button(text, tooltip, bgcolor, on_click):
            # Outer container has the same height as the TextField, so the row
            # uses the same vertical center line for the field and both buttons.
            return ft.Container(
                width=30,
                height=34,
                alignment=ft.Alignment.CENTER,
                tooltip=tooltip,
                on_click=on_click,
                content=ft.Container(
                    width=28,
                    height=28,
                    margin=ft.Margin(0, -14, 0, 0),
                    alignment=ft.Alignment.CENTER,
                    border_radius=6,
                    bgcolor=bgcolor,
                    ink=True,
                    content=ft.Text(
                        text,
                        size=15,
                        weight=ft.FontWeight.BOLD,
                        color="white",
                        text_align=ft.TextAlign.CENTER
                    )
                )
            )

        rename_field.on_submit = lambda e: page.run_task(save_inline_rename, e)
        rename_field.on_blur = lambda e: page.run_task(cancel_inline_rename_on_blur, e)

        current_list_name_container.content = ft.Row(
            [
                rename_field,
                make_rename_button(
                    "✓",
                    "儲存名稱",
                    "green",
                    lambda e: page.run_task(save_inline_rename, e)
                ),
                make_rename_button(
                    "✕",
                    "取消改名",
                    "grey",
                    cancel_inline_rename
                )
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=2
        )

        page.update()
    async def duplicate_list(list_name):
        mark_user_activity()
        if not list_name:
            return
        remote_lists = await request_json(
            "GET",
            f"{DB_URL}/metadata/lists.json?auth={user_token['id']}"
        )
        if not isinstance(remote_lists, dict):
            remote_lists = {}
        new_name = make_copied_list_name(list_name, set(remote_lists.keys()))
        source_items = list_items_cache.get(list_name)
        if source_items is None:
            items_raw = await request_json(
                "GET",
                f"{DB_URL}/shopping_lists/{list_name}.json?auth={user_token['id']}"
            )
            source_items = normalize_items(items_raw)
        copied_items = {}
        now_text = datetime.datetime.now().isoformat()
        for item_id, item_data in source_items.items():
            if isinstance(item_data, dict):
                copied = dict(item_data)
                copied["created_at"] = copied.get("created_at") or now_text
                copied_items[item_id] = copied
        mark_local_write()
        copied_preview = build_preview_data_from_items(copied_items)
        await asyncio.gather(
            request_json(
                "PATCH",
                f"{DB_URL}/metadata/lists.json?auth={user_token['id']}",
                {new_name: make_list_metadata()}
            ),
            request_json(
                "PUT",
                f"{DB_URL}/shopping_lists/{new_name}.json?auth={user_token['id']}",
                copied_items
            ),
            request_json(
                "PUT",
                f"{DB_URL}/metadata/list_previews/{new_name}.json?auth={user_token['id']}",
                copied_preview
            )
        )
        if new_name not in list_names_cache:
            list_names_cache.append(new_name)
        list_meta_cache[new_name] = make_list_metadata()
        promote_list_to_top_local(new_name)
        list_items_cache[new_name] = copied_items
        list_previews_cache[new_name] = copied_preview
        clear_error()
        render_home_lists()
        page.update()
    def promote_list_to_top_local(list_name):
        if not list_name:
            return
        if list_name in list_names_cache:
            list_names_cache.remove(list_name)
        list_names_cache.insert(0, list_name)
        now_text = datetime.datetime.now().isoformat()
        for index, name in enumerate(list_names_cache):
            meta = list_meta_cache.get(name)
            if not isinstance(meta, dict):
                meta = make_list_metadata()
            meta = dict(meta)
            if not meta.get("created_at"):
                meta["created_at"] = now_text
            meta["updated_at"] = now_text if name == list_name else meta.get("updated_at", now_text)
            meta["order"] = index
            list_meta_cache[name] = meta
    async def save_list_order_remote():
        if not user_token["id"]:
            return
        now_text = datetime.datetime.now().isoformat()
        patch_data = {}
        for index, list_name in enumerate(list_names_cache):
            meta = list_meta_cache.get(list_name)
            if isinstance(meta, dict):
                new_meta = dict(meta)
            else:
                new_meta = make_list_metadata()
            new_meta["active"] = True
            new_meta["order"] = index
            new_meta["updated_at"] = now_text
            list_meta_cache[list_name] = new_meta
            patch_data[list_name] = new_meta
        try:
            await request_json(
                "PATCH",
                f"{DB_URL}/metadata/lists.json?auth={user_token['id']}",
                patch_data
            )
        except Exception as ex:
            set_error(f"❌ 清單排序儲存失敗: {repr(ex)}")
            page.update()
    def reorder_home_list(old_index, new_index):
        mark_user_activity()
        old_index, new_index = normalize_reorder_new_index(old_index, new_index, len(list_names_cache))
        if old_index is None or old_index == new_index:
            return
        moved_name = list_names_cache.pop(old_index)
        list_names_cache.insert(new_index, moved_name)
        for index, list_name in enumerate(list_names_cache):
            meta = list_meta_cache.get(list_name)
            if not isinstance(meta, dict):
                meta = make_list_metadata()
            meta = dict(meta)
            meta["order"] = index
            list_meta_cache[list_name] = meta
        mark_local_write()
        clear_error()
        render_home_lists()
        page.update()
        page.run_task(save_list_order_remote)
    def on_home_reorder(e):
        old_index, new_index = get_reorder_indices(e)
        reorder_home_list(old_index, new_index)
    def render_home_lists():
        home_list_view.controls.clear()
        if not list_names_cache:
            home_list_view.controls.append(
                ft.Text("目前沒有清單，請先新增清單", color="grey")
            )
            return
        card_width = min(650, int((home_list_view.width or 660) - 10))
        drag_width = 34
        action_width = 78
        text_width = max(105, card_width - drag_width - action_width - 46)
        missing_preview_names = []
        card_controls = []
        for index, list_name in enumerate(list_names_cache):
            preview, has_more, is_loaded = get_unchecked_preview(list_name)
            if not is_loaded:
                preview_text = "同步完整清單中..."
                missing_preview_names.append(list_name)
            elif preview:
                preview_text = "、".join(preview)
                if has_more:
                    preview_text += " ..."
            else:
                preview_text = "沒有未完成項目"
            title_text = ft.Text(
                list_name,
                size=18,
                weight="bold",
                width=text_width,
                max_lines=2,
                text_align=ft.TextAlign.LEFT
            )
            preview_text_control = ft.Text(
                preview_text,
                size=14,
                color="grey",
                width=text_width,
                max_lines=2,
                overflow=ft.TextOverflow.ELLIPSIS
            )
            title_area = ft.Container(
                width=text_width,
                on_click=lambda e, n=list_name: show_item_screen(n),
                content=ft.Column(
                    [
                        title_text,
                        preview_text_control
                    ],
                    spacing=4,
                    horizontal_alignment=ft.CrossAxisAlignment.START
                )
            )
            drag_area = ft.Container(
                width=drag_width,
                height=44,
                alignment=ft.Alignment.CENTER,
                content=make_drag_handle(22)
            )
            action_area = ft.Row(
                [
                    ft.IconButton(
                        ft.Icons.CONTENT_COPY,
                        tooltip="複製清單",
                        width=34,
                        height=34,
                        icon_size=18,
                        on_click=lambda e, n=list_name: page.run_task(duplicate_list, n)
                    ),
                    ft.IconButton(
                        ft.Icons.DELETE_OUTLINE,
                        icon_color="red",
                        tooltip="刪除清單",
                        width=34,
                        height=34,
                        icon_size=18,
                        on_click=lambda e, n=list_name: page.run_task(delete_home_list, n)
                    )
                ],
                width=action_width,
                alignment=ft.MainAxisAlignment.END,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2
            )
            card = ft.Container(
                width=card_width,
                padding=10,
                border=ft.Border.all(1, "grey"),
                border_radius=10,
                bgcolor="white",
                content=ft.Row(
                    [
                        drag_area,
                        title_area,
                        action_area
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    spacing=4
                )
            )
            try:
                card.key = f"home_list_{list_name}_{index}"
            except Exception:
                pass
            card_controls.append(card)
        reorderable = make_reorderable_list_view(
            card_controls,
            max(220, int(home_list_view.height or 640)),
            on_home_reorder
        )
        if reorderable is not None:
            home_list_view.controls.append(reorderable)
        else:
            home_list_view.controls.extend(card_controls)
        if missing_preview_names and user_token["id"]:
            page.run_task(fetch_missing_home_previews, missing_preview_names)
    def select_quick_item(item_name):
        mark_user_activity()
        item_name = trim_item_name(item_name)
        if not item_name:
            return

        item_input_source["suppress_change"] = True
        sync_all_item_input_values(item_name)
        item_input_source["suppress_change"] = False
        item_input_source["from_quick"] = True

        selected_item_text.value = format_selected_item_text(item_name)
        update_mobile_item_button_label()
        hide_history_suggestions()
        clear_error()
        page.update()

    def get_quick_display_text(text):
        text = str(text or "").strip()
        if len(text) > QUICK_NAME_MAX_LEN:
            return text[:QUICK_NAME_MAX_LEN]
        return text
    def get_quick_visual_len(text):
        total = 0.0
        for ch in str(text or ""):
            total += 1.6 if ord(ch) > 127 else 1.0
        return max(1.0, total)
    def get_quick_font_size(text, btn_width, base_size):
        display_text = get_quick_display_text(text)
        usable_width = max(8, int(btn_width) - 6)
        visual_len = get_quick_visual_len(display_text)
        estimated_size = int(usable_width / (visual_len * 0.56))
        return max(4, min(base_size, estimated_size))
    def make_quick_button(text, btn_width, btn_height, base_font_size, on_click):
        display_text = get_quick_display_text(text)
        return ft.Container(
            width=btn_width,
            height=btn_height,
            padding=1,
            alignment=ft.Alignment.CENTER,
            border=ft.Border.all(1, "#BDBDBD"),
            border_radius=6,
            bgcolor="#F7F7F7",
            on_click=on_click,
            content=ft.Text(
                display_text,
                size=get_quick_font_size(display_text, btn_width, base_font_size),
                text_align=ft.TextAlign.CENTER,
                max_lines=1
            )
        )
    def refresh_quick_grid():
        quick_grid.controls.clear()
        grid_width = int(quick_grid.width or 220)
        btn_width = max(86, grid_width - 8)
        btn_height = 42 if is_mobile_layout["value"] else 44
        font_size = 15 if is_mobile_layout["value"] else 16
        for item_name in quick_items[:QUICK_ITEM_LIMIT]:
            quick_grid.controls.append(
                make_quick_button(
                    item_name,
                    btn_width,
                    btn_height,
                    font_size,
                    lambda e, n=item_name: select_quick_item(n)
                )
            )
        if not quick_items:
            quick_grid.controls.append(
                ft.Text("尚未設定快捷項目", size=11, color="grey")
            )
    def reorder_quick_item(old_index, new_index):
        mark_user_activity()
        try:
            old_index = int(old_index)
            new_index = int(new_index)
        except Exception:
            return
        if old_index < 0 or old_index >= len(quick_items):
            return
        new_index = max(0, min(new_index, len(quick_items) - 1))
        if old_index == new_index:
            return
        item = quick_items.pop(old_index)
        quick_items.insert(new_index, item)
        mark_local_write()
        clear_error()
        refresh_quick_ui()
        page.update()
        page.run_task(save_quick_items_remote)
        async def refresh_quick_after_reorder():
            await asyncio.sleep(0.15)
            refresh_quick_ui()
            page.update()
        page.run_task(refresh_quick_after_reorder)
    def on_quick_reorder(e):
        old_index, new_index = get_reorder_indices(e)
        reorder_quick_item(old_index, new_index)
    def refresh_quick_edit_list():
        quick_edit_list.controls.clear()
        if not quick_items:
            quick_edit_list.controls.append(
                ft.Text("目前沒有快捷項目", color="grey", size=14)
            )
            return
        field_height = 58
        button_height = 46
        row_padding = 5
        if is_mobile_layout["value"]:
            row_width = int((quick_edit_list.width or 300) - 2)
            row_width = max(230, row_width)
            drag_width = 34
            btn_width = 58
            icon_size = 22
            icon_width = 38
            field_width = row_width - drag_width - btn_width - icon_width - 28
            field_width = max(105, field_width)
        else:
            row_width = 380
            drag_width = 34
            field_width = 220
            btn_width = 64
            icon_size = 22
            icon_width = 38
        def make_quick_edit_row(i, item_name):
            edit_field = ft.TextField(
                value=item_name,
                width=field_width,
                height=field_height,
                text_size=17,
                label=f"快捷 {i + 1}",
                label_style=ft.TextStyle(size=14),
                    )
            def mark_quick_edit_changed(e, field=edit_field, original=item_name):
                is_changed = (field.value or "").strip() != original
                field.border_color = "red" if is_changed else None
                field.focused_border_color = "red" if is_changed else None
                page.update()
            edit_field.on_change = mark_quick_edit_changed
            edit_field.on_submit = lambda e, idx=i, field=edit_field: page.run_task(update_quick_item, idx, field.value)
            row = ft.Container(
                width=row_width,
                padding=row_padding,
                border=ft.Border.all(1, "#E0E0E0"),
                border_radius=8,
                bgcolor="white",
                content=ft.Row(
                    [
                        ft.Container(
                            width=drag_width,
                            height=button_height,
                            alignment=ft.Alignment.CENTER,
                            content=make_drag_handle(22)
                        ),
                        edit_field,
                        ft.Button(
                            "儲存",
                            width=btn_width,
                            height=button_height,
                            style=ft.ButtonStyle(
                                text_style=ft.TextStyle(size=14)
                            ),
                            on_click=lambda e, idx=i, field=edit_field:
                                page.run_task(update_quick_item, idx, field.value)
                        ),
                        ft.IconButton(
                            ft.Icons.DELETE_OUTLINE,
                            icon_color="red",
                            icon_size=icon_size,
                            width=icon_width,
                            height=button_height,
                            tooltip="刪除快捷",
                            on_click=lambda e, idx=i:
                                page.run_task(delete_quick_item, idx)
                        )
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=4
                )
            )
            try:
                row.key = f"quick_edit_{i}_{item_name}"
            except Exception:
                pass
            return row
        rows = [make_quick_edit_row(i, item_name) for i, item_name in enumerate(quick_items)]
        reorderable = make_reorderable_list_view(
            rows,
            quick_edit_list.height,
            on_quick_reorder
        )
        if reorderable is not None:
            quick_edit_list.controls.append(reorderable)
        else:
            quick_edit_list.controls.extend(rows)
    def refresh_quick_ui():
        refresh_quick_grid()
        refresh_quick_edit_list()
    async def save_quick_items_remote():
        try:
            await request_json(
                "PUT",
                f"{DB_URL}/metadata/quick_items.json?auth={user_token['id']}",
                quick_items[:QUICK_ITEM_LIMIT]
            )
        except Exception as ex:
            set_error(f"❌ 快捷項目儲存失敗: {repr(ex)}")
            page.update()
    async def add_quick_item(e):
        mark_user_activity()
        limit_quick_new_input_now()
        name = str(quick_new_input.value or "").strip()[:QUICK_NAME_MAX_LEN]
        if not name:
            set_error("❌ 請輸入快捷項目名稱")
            page.update()
            return
        if len(name) > QUICK_NAME_MAX_LEN:
            set_error(f"❌ 快捷項目最多 {QUICK_NAME_MAX_LEN} 個字")
            page.update()
            return
        if name in quick_items:
            set_error("❌ 此快捷項目已存在")
            page.update()
            return
        if len(quick_items) >= QUICK_ITEM_LIMIT:
            set_error(f"❌ 快捷項目最多 {QUICK_ITEM_LIMIT} 個")
            page.update()
            return
        quick_items.append(name)
        mark_local_write()
        quick_new_input.value = ""
        clear_error()
        refresh_quick_ui()
        page.update()
        await save_quick_items_remote()
    async def update_quick_item(index, new_name):
        mark_user_activity()
        new_name = (new_name or "").strip()
        if not new_name:
            set_error("❌ 快捷項目不可空白")
            page.update()
            return
        if len(new_name) > QUICK_NAME_MAX_LEN:
            set_error(f"❌ 快捷項目最多 {QUICK_NAME_MAX_LEN} 個字")
            page.update()
            return
        if index < 0 or index >= len(quick_items):
            return
        for i, old_name in enumerate(quick_items):
            if i != index and old_name == new_name:
                set_error("❌ 此快捷項目已存在")
                page.update()
                return
        quick_items[index] = new_name
        mark_local_write()
        clear_error()
        refresh_quick_ui()
        page.update()
        await save_quick_items_remote()
    async def delete_quick_item(index):
        mark_user_activity()
        if index < 0 or index >= len(quick_items):
            return
        quick_items.pop(index)
        mark_local_write()
        clear_error()
        refresh_quick_ui()
        page.update()
        await save_quick_items_remote()
    async def save_item_order_remote(list_name):
        if not user_token["id"] or not list_name:
            return
        items = list_items_cache.get(list_name, {})
        patch_data = {}
        for item_id, item_data in items.items():
            if not isinstance(item_data, dict):
                continue
            if str(item_id).startswith("local_"):
                continue
            patch_data[f"{item_id}/order"] = get_numeric_order(item_data.get("order"), 999999.0)
        try:
            if patch_data:
                await request_json(
                    "PATCH",
                    f"{DB_URL}/shopping_lists/{list_name}.json?auth={user_token['id']}",
                    patch_data
                )
            await save_list_preview_remote(list_name)
        except Exception as ex:
            set_error(f"❌ 項目排序儲存失敗: {repr(ex)}")
            page.update()
    def reorder_current_items(old_index, new_index):
        mark_user_activity()
        list_name = current_list["name"]
        if not list_name or list_name not in list_items_cache:
            return
        ordered_entries = sorted_item_entries(list_items_cache.get(list_name, {}))
        old_index, new_index = normalize_reorder_new_index(old_index, new_index, len(ordered_entries))
        if old_index is None or old_index == new_index:
            return
        moved_entry = ordered_entries[old_index]
        target_entry = ordered_entries[new_index]
        moved_bought = bool(moved_entry[1].get("bought", False))
        target_bought = bool(target_entry[1].get("bought", False))
        if moved_bought != target_bought:
            render_items_from_cache(list_name)
            page.update()
            async def reset_cross_group_drag():
                await asyncio.sleep(0.05)
                if current_list["name"] == list_name:
                    render_items_from_cache(list_name)
                    page.update()
            page.run_task(reset_cross_group_drag)
            return
        ordered_entries.pop(old_index)
        ordered_entries.insert(new_index, moved_entry)
        new_items = {}
        group_index = {False: 0, True: 0}
        for item_id, item_data in ordered_entries:
            new_data = dict(item_data)
            group_key = bool(new_data.get("bought", False))
            new_data["order"] = group_index[group_key]
            group_index[group_key] += 1
            new_items[item_id] = new_data
        list_items_cache[list_name] = new_items
        mark_local_write()
        refresh_home_preview_after_local_change(list_name)
        render_items_from_cache(list_name)
        page.update()
        page.run_task(save_item_order_remote, list_name)
    def on_item_reorder(e):
        old_index, new_index = get_reorder_indices(e)
        reorder_current_items(old_index, new_index)
    def render_items_from_cache(list_name):
        items_view.controls.clear()
        items = list_items_cache.get(list_name, {})
        if not items:
            items_view.controls.append(
                ft.Text("此清單目前沒有項目", color="grey")
            )
        else:
            item_controls = []
            for index, (item_id, item_data) in enumerate(sorted_item_entries(items)):
                row = render_item_row(list_name, item_id, item_data)
                try:
                    row.key = f"item_{item_id}_{index}"
                except Exception:
                    pass
                item_controls.append(row)
            reorderable = make_reorderable_list_view(
                item_controls,
                max(220, int(items_view.height or 650)),
                on_item_reorder
            )
            if reorderable is not None:
                items_view.controls.append(reorderable)
            else:
                items_view.controls.extend(item_controls)
        page.update()
    def render_item_row(list_name, item_id, item_data):
        name = item_data.get("name", "未命名")
        qty = item_data.get("qty", "1")
        bought = item_data.get("bought", False)
        qty_text = ft.Text(
            f"{qty}",
            size=16,
            weight="bold"
        )
        async def checkbox_changed(e, i_id=item_id):
            mark_user_activity()
            new_value = bool(e.control.value)
            backup_items = None
            remote_patch = {}

            if list_name in list_items_cache and i_id in list_items_cache[list_name]:
                backup_items = {
                    k: dict(v) if isinstance(v, dict) else v
                    for k, v in list_items_cache[list_name].items()
                }

                list_items_cache[list_name][i_id]["bought"] = new_value

                # Checked items stay in the checked group. The most recently
                # checked item is moved to the first row of that checked group.
                if new_value:
                    checked_entries = []
                    for other_id, other_data in list_items_cache[list_name].items():
                        if not isinstance(other_data, dict):
                            continue
                        if bool(other_data.get("bought", False)):
                            checked_entries.append((other_id, other_data))

                    checked_entries.sort(
                        key=lambda x: (
                            0 if x[0] == i_id else 1,
                            get_numeric_order(x[1].get("order"), 999999.0),
                            -item_created_sort_value(x[1])
                        )
                    )

                    for order_index, (other_id, other_data) in enumerate(checked_entries):
                        other_data["order"] = order_index
                        if not str(other_id).startswith("local_"):
                            remote_patch[f"{other_id}/order"] = order_index

                if not str(i_id).startswith("local_"):
                    remote_patch[f"{i_id}/bought"] = new_value

                mark_local_write()
                refresh_home_preview_after_local_change(list_name)

            clear_error()
            render_items_from_cache(list_name)

            try:
                if remote_patch:
                    await request_json(
                        "PATCH",
                        f"{DB_URL}/shopping_lists/{list_name}.json?auth={user_token['id']}",
                        remote_patch
                    )
            except Exception as ex:
                if backup_items is not None:
                    list_items_cache[list_name] = backup_items
                    refresh_home_preview_after_local_change(list_name)
                set_error(f"❌ 勾選更新失敗: {repr(ex)}")
                render_items_from_cache(list_name)

        async def row_qty_change(e, delta, i_id=item_id, qty_control=qty_text):
            mark_user_activity()
            try:
                old_qty = int(qty_control.value)
            except Exception:
                old_qty = 1
            new_qty = old_qty + delta
            if new_qty < 1:
                new_qty = 1
            if new_qty == old_qty:
                return
            qty_control.value = str(new_qty)
            clear_error()
            if list_name in list_items_cache and i_id in list_items_cache[list_name]:
                list_items_cache[list_name][i_id]["qty"] = str(new_qty)
                mark_local_write()
                refresh_home_preview_after_local_change(list_name)
            page.update()
            try:
                await request_json(
                    "PATCH",
                    f"{DB_URL}/shopping_lists/{list_name}/{i_id}.json?auth={user_token['id']}",
                    {"qty": str(new_qty)}
                )
            except Exception as ex:
                qty_control.value = str(old_qty)
                if list_name in list_items_cache and i_id in list_items_cache[list_name]:
                    list_items_cache[list_name][i_id]["qty"] = str(old_qty)
                    refresh_home_preview_after_local_change(list_name)
                set_error(f"❌ 數量更新失敗: {repr(ex)}")
                page.update()
        async def delete_item(e, i_id=item_id):
            mark_user_activity()
            backup_item = None
            backup_index = None
            if str(i_id).startswith("local_"):
                pending_deleted_local_items.add(str(i_id))
            if list_name in list_items_cache:
                old_keys = list(list_items_cache[list_name].keys())
                if i_id in old_keys:
                    backup_index = old_keys.index(i_id)
                backup_item = list_items_cache[list_name].pop(i_id, None)
                mark_local_write()
                refresh_home_preview_after_local_change(list_name)

            # Items are rendered inside ReorderableListView, so directly removing
            # items_view.controls will not remove the visible row. Re-render from
            # cache immediately to make the deleted row disappear.
            render_items_from_cache(list_name)
            page.update()

            if str(i_id).startswith("local_"):
                return

            try:
                await request_json(
                    "DELETE",
                    f"{DB_URL}/shopping_lists/{list_name}/{i_id}.json?auth={user_token['id']}"
                )
            except Exception as ex:
                if backup_item is not None:
                    restored_items = {}
                    old_items = list_items_cache.get(list_name, {})
                    if backup_index is None:
                        restored_items = {
                            i_id: backup_item,
                            **old_items
                        }
                    else:
                        keys = list(old_items.keys())
                        for k_index, key in enumerate(keys):
                            if k_index == backup_index:
                                restored_items[i_id] = backup_item
                            restored_items[key] = old_items[key]
                        if i_id not in restored_items:
                            restored_items[i_id] = backup_item
                    list_items_cache[list_name] = restored_items
                    refresh_home_preview_after_local_change(list_name)
                    render_items_from_cache(list_name)
                set_error(f"❌ 刪除項目失敗: {repr(ex)}")
                page.update()
        card_width = items_view.width or 330
        def make_qty_action_group(is_mobile):
            if is_mobile:
                icon_size = 16
                icon_width = 26
                icon_height = 26
                qty_width = 30
                group_width = max(140, int(card_width or 160) - 12)
                qty_controls = ft.Row(
                    [
                        ft.IconButton(
                            ft.Icons.REMOVE_CIRCLE_OUTLINE,
                            tooltip="數量減少",
                            icon_size=icon_size,
                            width=icon_width,
                            height=icon_height,
                            on_click=lambda e, d=-1, task=row_qty_change:
                                page.run_task(task, e, d)
                        ),
                        ft.Container(
                            width=qty_width,
                            alignment=ft.Alignment.CENTER,
                            content=qty_text
                        ),
                        ft.IconButton(
                            ft.Icons.ADD_CIRCLE_OUTLINE,
                            tooltip="數量增加",
                            icon_size=icon_size,
                            width=icon_width,
                            height=icon_height,
                            on_click=lambda e, d=1, task=row_qty_change:
                                page.run_task(task, e, d)
                        )
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=1
                )
                return ft.Container(
                    width=group_width,
                    content=ft.Row(
                        [
                            ft.Container(width=icon_width, height=icon_height),
                            ft.Container(expand=True, alignment=ft.Alignment.CENTER, content=qty_controls),
                            ft.IconButton(
                                ft.Icons.DELETE_OUTLINE,
                                icon_color="red",
                                tooltip="刪除項目",
                                icon_size=icon_size,
                                width=icon_width,
                                height=icon_height,
                                on_click=lambda e, task=delete_item:
                                    page.run_task(task, e)
                            )
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=1
                    )
                )
            icon_size = 18
            icon_width = 36
            icon_height = 36
            qty_width = 42
            group_width = 154
            spacing = 2
            return ft.Container(
                width=group_width,
                content=ft.Row(
                    [
                        ft.IconButton(
                            ft.Icons.REMOVE_CIRCLE_OUTLINE,
                            tooltip="數量減少",
                            icon_size=icon_size,
                            width=icon_width,
                            height=icon_height,
                            on_click=lambda e, d=-1, task=row_qty_change:
                                page.run_task(task, e, d)
                        ),
                        ft.Container(
                            width=qty_width,
                            alignment=ft.Alignment.CENTER,
                            content=qty_text
                        ),
                        ft.IconButton(
                            ft.Icons.ADD_CIRCLE_OUTLINE,
                            tooltip="數量增加",
                            icon_size=icon_size,
                            width=icon_width,
                            height=icon_height,
                            on_click=lambda e, d=1, task=row_qty_change:
                                page.run_task(task, e, d)
                        ),
                        ft.IconButton(
                            ft.Icons.DELETE_OUTLINE,
                            icon_color="red",
                            tooltip="刪除項目",
                            icon_size=icon_size,
                            width=icon_width,
                            height=icon_height,
                            on_click=lambda e, task=delete_item:
                                page.run_task(task, e)
                        )
                    ],
                    alignment=ft.MainAxisAlignment.END,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=spacing
                )
            )
        if is_mobile_layout["value"]:
            qty_text.size = 15
            qty_text.text_align = ft.TextAlign.CENTER
            return ft.Container(
                data=item_id,
                width=card_width,
                padding=5,
                border=ft.Border.all(1, "grey"),
                border_radius=6,
                alignment=ft.Alignment.CENTER,
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Checkbox(
                                    value=bought,
                                    width=30,
                                    height=30,
                                    on_change=lambda e, task=checkbox_changed:
                                        page.run_task(task, e)
                                ),
                                ft.Container(
                                    width=28,
                                    height=30,
                                    alignment=ft.Alignment.CENTER,
                                    content=make_drag_handle(20)
                                ),
                                ft.Text(
                                    name,
                                    size=16,
                                    weight="bold",
                                    expand=True,
                                    max_lines=2,
                                    overflow=ft.TextOverflow.VISIBLE,
                                    text_align=ft.TextAlign.LEFT
                                )
                            ],
                            alignment=ft.MainAxisAlignment.START,
                            vertical_alignment=ft.CrossAxisAlignment.START,
                            spacing=2
                        ),
                        ft.Row(
                            [make_qty_action_group(True)],
                            alignment=ft.MainAxisAlignment.CENTER,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=0
                        )
                    ],
                    spacing=1,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH
                )
            )
        return ft.Container(
            data=item_id,
            width=card_width,
            padding=4,
            border=ft.Border.all(1, "grey"),
            border_radius=6,
            alignment=ft.Alignment.CENTER,
            content=ft.Row(
                [
                    ft.Container(
                        width=28,
                        height=32,
                        alignment=ft.Alignment.CENTER,
                        content=make_drag_handle(20)
                    ),
                    ft.Checkbox(
                        value=bought,
                        on_change=lambda e, task=checkbox_changed:
                            page.run_task(task, e)
                    ),
                    ft.Text(
                        name,
                        size=16,
                        expand=True,
                        text_align=ft.TextAlign.CENTER
                    ),
                    make_qty_action_group(False)
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER
            )
        )
    async def fetch_items(list_name, show_loading=False):
        if not list_name or list_name == "請選擇清單":
            page.update()
            return
        if show_loading:
            items_view.controls.clear()
            items_view.controls.append(
                ft.Text("載入中...", color="grey")
            )
            page.update()
        items_raw = await request_json(
            "GET",
            f"{DB_URL}/shopping_lists/{list_name}.json?auth={user_token['id']}"
        )
        remote_items = normalize_items(items_raw)
        list_items_cache[list_name] = merge_remote_items_with_local(list_name, remote_items)
        update_preview_cache(list_name)
        render_items_from_cache(list_name)
        if home_screen.visible:
            render_home_lists()
        scroll_items_to_top()
    async def add_list_click(e):
        mark_user_activity()
        try:
            raw_input = (list_name_input.value or "").strip()
            base_name = raw_input if raw_input else datetime.datetime.now().strftime("%Y-%m-%d")
            current_lists = await request_json(
                "GET",
                f"{DB_URL}/metadata/lists.json?auth={user_token['id']}"
            )
            if not isinstance(current_lists, dict):
                current_lists = {}
            final_name = make_unique_list_name(base_name, set(current_lists.keys()))
            await request_json(
                "PATCH",
                f"{DB_URL}/metadata/lists.json?auth={user_token['id']}",
                {final_name: make_list_metadata()}
            )
            if final_name not in list_names_cache:
                list_names_cache.append(final_name)
            list_meta_cache[final_name] = make_list_metadata()
            promote_list_to_top_local(final_name)
            mark_local_write()
            list_items_cache[final_name] = {}
            list_previews_cache[final_name] = build_preview_data_from_items({})
            page.run_task(save_list_preview_remote, final_name, {})
            list_name_input.value = ""
            clear_error()
            render_home_lists()
            show_item_screen(final_name)
            page.run_task(save_list_order_remote)
        except Exception as ex:
            set_error(f"❌ 新增清單失敗: {repr(ex)}")
            page.update()
    async def delete_list_remote(list_name):
        try:
            await asyncio.gather(
                request_json(
                    "DELETE",
                    f"{DB_URL}/metadata/lists/{list_name}.json?auth={user_token['id']}"
                ),
                request_json(
                    "DELETE",
                    f"{DB_URL}/shopping_lists/{list_name}.json?auth={user_token['id']}"
                ),
                request_json(
                    "DELETE",
                    f"{DB_URL}/metadata/list_previews/{list_name}.json?auth={user_token['id']}"
                )
            )
        except Exception as ex:
            set_error(f"❌ 背景刪除清單失敗: {repr(ex)}")
            page.update()
    async def delete_current_list(e):
        mark_user_activity()
        list_name = current_list["name"]
        if not list_name:
            set_error("❌ 目前沒有可刪除的清單")
            page.update()
            return
        if list_name in list_names_cache:
            list_names_cache.remove(list_name)
        list_items_cache.pop(list_name, None)
        list_previews_cache.pop(list_name, None)
        list_meta_cache.pop(list_name, None)
        current_list["name"] = None
        clear_error()
        render_home_lists()
        show_home_screen()
        page.run_task(delete_list_remote, list_name)
    async def save_history_item(name):
        try:
            await request_json(
                "PATCH",
                f"{DB_URL}/metadata/history.json?auth={user_token['id']}",
                {name: {"active": True}}
            )
        except Exception as ex:
            print(f"歷史項目儲存失敗: {repr(ex)}")
    def parse_qty_value(value):
        try:
            qty_value = int(str(value or "1").strip())
        except Exception:
            qty_value = 1
        return max(1, qty_value)

    def validate_item_name_length(name):
        if len(str(name or "").strip()) > ITEM_NAME_MAX_LEN:
            set_error(f"❌ 新增項目最多 {ITEM_NAME_MAX_LEN} 個字")
            page.update()
            return False
        return True

    def find_same_name_item(list_name, item_name):
        target_name = str(item_name or "").strip()
        for item_id, item_data in sorted_item_entries(list_items_cache.get(list_name, {})):
            current_name = str(item_data.get("name", "") or "").strip()
            if current_name == target_name:
                return item_id, item_data
        return None, None
    async def sync_history_after_add(name, clear_input, save_to_history=True):
        if save_to_history:
            if name not in history_name_set or name not in history_names_cache:
                add_history_name_local(name)
            page.run_task(save_history_item, name)
        if clear_input:
            clear_item_dropdown()
            main_qty_text.value = "1"
        clear_error()
        page.update()
    async def add_item_to_current_list(name, qty, clear_input=True, save_to_history=True):
        list_name = current_list["name"]
        name = trim_item_name(name)
        add_qty = parse_qty_value(qty)
        if not list_name:
            set_error("❌ 請先選擇清單")
            page.update()
            return
        if not name:
            set_error("❌ 請輸入項目名稱")
            page.update()
            return
        if not validate_item_name_length(name):
            return
        now_text = datetime.datetime.now().isoformat()
        same_item_id, same_item_data = find_same_name_item(list_name, name)
        if same_item_id and isinstance(same_item_data, dict):
            old_item_data = dict(same_item_data)
            old_qty = parse_qty_value(same_item_data.get("qty", "1"))
            new_qty = old_qty + add_qty
            same_item_data["qty"] = str(new_qty)
            same_item_data["bought"] = False
            same_item_data["created_at"] = now_text
            mark_local_write()
            refresh_home_preview_after_local_change(list_name)
            render_items_from_cache(list_name)
            scroll_items_to_top()
            await sync_history_after_add(name, clear_input, save_to_history)
            async def update_existing_remote():
                try:
                    await request_json(
                        "PATCH",
                        f"{DB_URL}/shopping_lists/{list_name}/{same_item_id}.json?auth={user_token['id']}",
                        {
                            "qty": str(new_qty),
                            "bought": False,
                            "created_at": now_text
                        }
                    )
                    await save_list_preview_remote(list_name)
                except Exception as ex:
                    if list_name in list_items_cache and same_item_id in list_items_cache[list_name]:
                        list_items_cache[list_name][same_item_id] = old_item_data
                    refresh_home_preview_after_local_change(list_name, save_remote=False)
                    render_items_from_cache(list_name)
                    set_error(f"❌ 新增項目失敗: {repr(ex)}")
                    page.update()
            page.run_task(update_existing_remote)
            return
        temp_item_id = f"local_{int(datetime.datetime.now().timestamp() * 1000)}"
        old_items = list_items_cache.get(list_name, {})
        shifted_old_items = {}
        for old_id, old_data in old_items.items():
            if isinstance(old_data, dict):
                shifted_data = dict(old_data)
                shifted_data["order"] = get_numeric_order(shifted_data.get("order"), 999999.0) + 1
                shifted_old_items[old_id] = shifted_data
            else:
                shifted_old_items[old_id] = old_data
        new_item_data = {
            "name": name,
            "qty": str(add_qty),
            "bought": False,
            "created_at": now_text,
            "order": 0
        }
        list_items_cache[list_name] = {
            temp_item_id: new_item_data,
            **shifted_old_items
        }
        mark_local_write()
        refresh_home_preview_after_local_change(list_name)
        if len(items_view.controls) == 1 and isinstance(items_view.controls[0], ft.Text):
            items_view.controls.clear()
        items_view.controls.insert(
            0,
            render_item_row(list_name, temp_item_id, new_item_data)
        )
        scroll_items_to_top()
        await sync_history_after_add(name, clear_input, save_to_history)
        async def create_new_remote():
            try:
                post_data = await request_json(
                    "POST",
                    f"{DB_URL}/shopping_lists/{list_name}.json?auth={user_token['id']}",
                    new_item_data
                )
                if not isinstance(post_data, dict) or not post_data.get("name"):
                    raise RuntimeError("Firebase did not return a new item id")
                new_item_id = post_data.get("name")
                if temp_item_id in pending_deleted_local_items:
                    pending_deleted_local_items.discard(temp_item_id)
                    await request_json(
                        "DELETE",
                        f"{DB_URL}/shopping_lists/{list_name}/{new_item_id}.json?auth={user_token['id']}"
                    )
                    await save_list_preview_remote(list_name)
                    return
                if list_name in list_items_cache and temp_item_id in list_items_cache[list_name]:
                    temp_data = list_items_cache[list_name].pop(temp_item_id)
                    list_items_cache[list_name] = {
                        new_item_id: temp_data,
                        **list_items_cache[list_name]
                    }
                    refresh_home_preview_after_local_change(list_name)
                    if current_list["name"] == list_name and item_screen.visible:
                        render_items_from_cache(list_name)
                        scroll_items_to_top()
                await save_item_order_remote(list_name)
                await save_list_preview_remote(list_name)
            except Exception as ex:
                if list_name in list_items_cache:
                    list_items_cache[list_name].pop(temp_item_id, None)
                refresh_home_preview_after_local_change(list_name, save_remote=False)
                if current_list["name"] == list_name and item_screen.visible:
                    render_items_from_cache(list_name)
                set_error(f"❌ 新增項目失敗: {repr(ex)}")
                page.update()
        page.run_task(create_new_remote)
    async def add_item_final(e):
        mark_user_activity()
        hide_history_suggestions()
        name = get_item_dropdown_text()
        qty = main_qty_text.value
        save_to_history = not item_input_source["from_quick"]
        await add_item_to_current_list(
            name,
            qty,
            clear_input=True,
            save_to_history=save_to_history
        )
    add_item_button.on_click = add_item_final
    def get_option_value(opt):
        value = getattr(opt, "key", None)
        if value:
            return str(value)
        value = getattr(opt, "text", None)
        if value:
            return str(value)
        return str(opt)
    async def delete_history_item_remote(history_name, backup_options):
        try:
            await request_json(
                "DELETE",
                f"{DB_URL}/metadata/history/{history_name}.json?auth={user_token['id']}"
            )
        except Exception as ex:
            if history_name not in history_name_set:
                history_name_set.add(history_name)
            if history_name not in history_names_cache:
                history_names_cache.append(history_name)
            item_dropdown.options = backup_options
            set_error(f"❌ 刪除歷史項目失敗: {repr(ex)}")
            page.update()
    async def delete_selected_history_item(e):
        history_name = get_item_dropdown_text()
        if not history_name:
            set_error("❌ 請先選擇要刪除的歷史項目")
            page.update()
            return
        if history_name not in history_name_set:
            set_error("❌ 這不是歷史項目，無法刪除")
            page.update()
            return
        backup_options = list(item_dropdown.options or [])
        remove_history_name_local(history_name)
        clear_item_dropdown()
        clear_error()
        page.update()
        page.run_task(delete_history_item_remote, history_name, backup_options)
    async def load_metadata(selected_list=None):
        # Fetch metadata and the complete shopping_lists tree in the background.
        # Do not force the UI back to the first layer when the user has already
        # entered a list while this request is still running.
        previous_current = current_list.get("name")
        was_item_visible = bool(item_screen and item_screen.visible)
        was_home_visible = bool(home_screen and home_screen.visible)

        meta, shopping_lists_raw = await asyncio.gather(
            request_json(
                "GET",
                f"{DB_URL}/metadata.json?auth={user_token['id']}"
            ),
            request_json(
                "GET",
                f"{DB_URL}/shopping_lists.json?auth={user_token['id']}"
            ),
            return_exceptions=True
        )

        if isinstance(meta, Exception):
            raise meta
        if isinstance(shopping_lists_raw, Exception):
            print(f"完整清單讀取失敗: {repr(shopping_lists_raw)}")
            shopping_lists_raw = {}

        apply_metadata_payload(meta)
        apply_all_shopping_lists_payload(shopping_lists_raw, set(list_names_cache))
        refresh_quick_ui()
        await save_home_cache_local()

        target_list = selected_list or current_list.get("name") or previous_current

        if target_list and target_list in list_names_cache and (was_item_visible or item_screen.visible or selected_list):
            current_list["name"] = target_list
            current_selected_list_text.value = target_list
            try:
                set_current_list_title_view()
            except Exception:
                pass
            home_screen.visible = False
            item_screen.visible = True
            quick_edit_screen.visible = False
            render_items_from_cache(target_list)
            page.update()
            return

        if target_list and target_list not in list_names_cache:
            current_list["name"] = None
            current_selected_list_text.value = "請選擇清單"

        if was_home_visible or home_screen.visible or not current_list.get("name"):
            home_screen.visible = True
            item_screen.visible = False
            quick_edit_screen.visible = False
            render_home_lists()
            page.update()

    async def load_metadata_safely(selected_list=None):
        try:
            await load_metadata(selected_list)
        except Exception as ex:
            set_error(f"❌ 資料同步失敗: {repr(ex)}")
            page.update()

    async def refresh_remote_changes(e=None, show_status=True):
        if show_status:
            mark_user_activity()
        if manual_refreshing["value"]:
            return
        if not user_token["id"] or not shopping_container.visible:
            return

        manual_refreshing["value"] = True
        if show_status:
            set_error("重整中...")
            page.update()

        try:
            meta, shopping_lists_raw = await asyncio.gather(
                request_json(
                    "GET",
                    f"{DB_URL}/metadata.json?auth={user_token['id']}"
                ),
                request_json(
                    "GET",
                    f"{DB_URL}/shopping_lists.json?auth={user_token['id']}"
                ),
                return_exceptions=True
            )

            if isinstance(meta, Exception):
                raise meta
            if isinstance(shopping_lists_raw, Exception):
                print(f"完整清單讀取失敗: {repr(shopping_lists_raw)}")
                shopping_lists_raw = {}

            previous_current = current_list["name"]

            apply_metadata_payload(meta)
            apply_all_shopping_lists_payload(shopping_lists_raw, set(list_names_cache))
            refresh_quick_ui()

            if previous_current and previous_current not in list_names_cache:
                current_list["name"] = None
                current_selected_list_text.value = "請選擇清單"
                show_home_screen()

            if current_list["name"]:
                render_items_from_cache(current_list["name"])

            render_home_lists()
            await save_home_cache_local()

            if show_status:
                set_error("✅ 已重整")
            page.update()

        except Exception as ex:
            set_error(f"❌ 重整失敗: {repr(ex)}")
            page.update()
        finally:
            manual_refreshing["value"] = False
    async def sync_home_lists(show_status=False):
        if system_closed_by_idle["value"]:
            return
        if home_auto_syncing["value"]:
            return
        if is_local_write_active():
            return
        if not user_token["id"] or not shopping_container.visible:
            return
        if not home_screen or not home_screen.visible:
            return

        home_auto_syncing["value"] = True
        try:
            meta, shopping_lists_raw = await asyncio.gather(
                request_json(
                    "GET",
                    f"{DB_URL}/metadata.json?auth={user_token['id']}"
                ),
                request_json(
                    "GET",
                    f"{DB_URL}/shopping_lists.json?auth={user_token['id']}"
                ),
                return_exceptions=True
            )

            if isinstance(meta, Exception):
                raise meta
            if isinstance(shopping_lists_raw, Exception):
                print(f"完整清單讀取失敗: {repr(shopping_lists_raw)}")
                shopping_lists_raw = {}

            apply_metadata_payload(meta)
            apply_all_shopping_lists_payload(shopping_lists_raw, set(list_names_cache))
            refresh_quick_ui()
            render_home_lists()
            await save_home_cache_local()

            if show_status:
                set_error("✅ 第一層已重整")
            page.update()

        except Exception as ex:
            if show_status:
                set_error(f"❌ 第一層重整失敗: {repr(ex)}")
                page.update()
        finally:
            home_auto_syncing["value"] = False
    async def auto_sync_home_loop():
        while True:
            if system_closed_by_idle["value"]:
                await asyncio.sleep(SLEEP_IDLE_CHECK_SECONDS)
                continue
            await asyncio.sleep(ACTIVE_HOME_SYNC_SECONDS)
            try:
                if system_closed_by_idle["value"]:
                    continue
                await sync_home_lists(show_status=False)
            except Exception as ex:
                print(f"第一層自動重整失敗: {repr(ex)}")
    async def sync_current_list_items(show_status=False):
        if system_closed_by_idle["value"]:
            return
        if current_list_auto_syncing["value"]:
            return
        if is_local_write_active():
            return
        if not user_token["id"] or not shopping_container.visible:
            return
        if not item_screen or not item_screen.visible:
            return
        list_name = current_list["name"]
        if not list_name:
            return
        current_list_auto_syncing["value"] = True
        try:
            items_raw = await request_json(
                "GET",
                f"{DB_URL}/shopping_lists/{list_name}.json?auth={user_token['id']}"
            )
            remote_items = merge_remote_items_with_local(list_name, normalize_items(items_raw))
            if list_name != current_list["name"] or not item_screen.visible:
                return
            if remote_items != list_items_cache.get(list_name, {}):
                list_items_cache[list_name] = remote_items
                update_preview_cache(list_name, remote_items)
                page.run_task(save_home_cache_local)
                render_items_from_cache(list_name)
                if show_status:
                    set_error("✅ 已同步目前清單")
                page.update()
        except Exception as ex:
            if show_status:
                set_error(f"❌ 同步目前清單失敗: {repr(ex)}")
                page.update()
        finally:
            current_list_auto_syncing["value"] = False
    async def auto_sync_current_list_loop():
        while True:
            if system_closed_by_idle["value"]:
                await asyncio.sleep(SLEEP_IDLE_CHECK_SECONDS)
                continue
            await asyncio.sleep(ACTIVE_CURRENT_LIST_SYNC_SECONDS)
            try:
                if system_closed_by_idle["value"]:
                    continue
                await sync_current_list_items(show_status=False)
            except Exception as ex:
                print(f"目前清單自動同步失敗: {repr(ex)}")
    async def process_login(e):
        mark_user_activity()
        email = (email_in.value or "").strip()
        password = (pass_in.value or "").strip()
        if not email or not password:
            set_error("❌ 請輸入帳號與密碼")
            page.update()
            return
        try:
            data = await request_json(
                "POST",
                AUTH_SIGNIN,
                {
                    "email": email,
                    "password": password,
                    "returnSecureToken": True
                }
            )
            if not isinstance(data, dict) or "localId" not in data:
                error_message = ""
                if isinstance(data, dict):
                    error_message = data.get("error", {}).get("message", "")
                set_error(f"❌ 帳密錯誤: {error_message}")
                page.update()
                return
            uid = data["localId"]
            user_token["id"] = data.get("idToken")
            user_token["refresh"] = data.get("refreshToken")
            user_token["uid"] = uid
            user_data = await request_json(
                "GET",
                f"{DB_URL}/users/{uid}.json?auth={user_token['id']}"
            )
            if isinstance(user_data, dict) and user_data.get("is_approved"):
                await prefs.set("shopping_email", email)
                await prefs.set("shopping_password", password)
                if user_token["refresh"]:
                    await prefs.set("shopping_refresh_token", user_token["refresh"])
                if user_token["uid"]:
                    await prefs.set("shopping_uid", user_token["uid"])
                build_main_ui_once()
                login_container.visible = False
                shopping_container.visible = True
                clear_error()
                show_startup_loading()
                await load_home_summary_cache_local()
                page.run_task(load_full_home_cache_local, False)
                page.run_task(load_metadata_safely)
            else:
                set_error("⏳ 尚未通過審核")
                page.update()
        except Exception as e:
            set_error(f"❌ 連線失敗: {repr(e)}")
            page.update()
    async def process_register(e):
        mark_user_activity()
        email = (email_in.value or "").strip()
        password = (pass_in.value or "").strip()
        if not email or not password:
            set_error("❌ 請輸入帳號與密碼")
            page.update()
            return
        try:
            auth_data = await request_json(
                "POST",
                AUTH_SIGNUP,
                {
                    "email": email,
                    "password": password,
                    "returnSecureToken": True
                }
            )
            if isinstance(auth_data, dict) and "localId" in auth_data:
                uid = auth_data["localId"]
                temp_token = auth_data.get("idToken")
                await request_json(
                    "PUT",
                    f"{DB_URL}/users/{uid}.json?auth={temp_token}",
                    {
                        "email": email,
                        "is_approved": False
                    }
                )
                set_error("✅ 註冊成功，請聯繫管理員")
                page.update()
            else:
                error_message = ""
                if isinstance(auth_data, dict):
                    error_message = auth_data.get("error", {}).get("message", "")
                set_error(f"❌ 註冊失敗: {error_message}")
                page.update()
        except Exception as e:
            set_error(f"❌ 註冊失敗: {repr(e)}")
            page.update()

    # These controls are visible before the main UI is built, so bind them here.
    # Do not wait until build_main_ui_once(); otherwise the first login screen
    # has no active login/register handlers.
    login_button.on_click = lambda e: page.run_task(process_login, e)
    register_button.on_click = lambda e: page.run_task(process_register, e)
    email_in.on_submit = lambda e: page.run_task(process_login, e)
    pass_in.on_submit = lambda e: page.run_task(process_login, e)

    async def remove_saved_pref(key):
        try:
            remove_fn = getattr(prefs, "remove", None)
            if remove_fn is not None:
                result = remove_fn(key)
                if inspect.isawaitable(result):
                    await result
                return
        except Exception:
            pass
        try:
            await prefs.set(key, "")
        except Exception:
            pass

    async def clear_device_record():
        for key in [
            "shopping_email",
            "shopping_password",
            "shopping_refresh_token",
            "shopping_uid",
            HOME_CACHE_KEY,
            HOME_SUMMARY_CACHE_KEY
        ]:
            await remove_saved_pref(key)

    async def process_logout(e=None):
        mark_user_activity()
        if not main_ui_built["value"]:
            build_main_ui_once()
        await clear_device_record()
        user_token["id"] = None
        user_token["refresh"] = None
        user_token["uid"] = None
        current_list["name"] = None
        list_names_cache.clear()
        list_items_cache.clear()
        list_previews_cache.clear()
        list_meta_cache.clear()
        history_name_set.clear()
        history_names_cache.clear()
        quick_items.clear()
        pending_deleted_local_items.clear()
        email_in.value = ""
        pass_in.value = ""
        clear_item_dropdown()
        remove_history_overlay()
        idle_container.visible = False
        shopping_container.visible = False
        home_screen.visible = True
        item_screen.visible = False
        quick_edit_screen.visible = False
        login_container.visible = True
        clear_error()
        page.update()

    def build_main_ui_once():
        if main_ui_built["value"]:
            return

        main_ui_built["value"] = True

        nonlocal home_screen, item_screen, quick_edit_screen
        nonlocal current_list_name_container, item_qty_row_container, item_input_container
        nonlocal left_panel, right_sidebar, quick_section, item_add_section

        home_title_text = ft.Text(
            "清單總覽",
            size=24,
            weight="bold",
            text_align=ft.TextAlign.CENTER
        )
        home_add_button = ft.IconButton(
            ft.Icons.ADD_BOX,
            icon_color="green",
            tooltip="新增清單",
            width=42,
            height=42,
            icon_size=24,
            on_click=add_list_click
        )
        home_refresh_button = ft.IconButton(
            ft.Icons.REFRESH,
            tooltip="重整",
            width=42,
            height=42,
            icon_size=23,
            on_click=lambda e: page.run_task(refresh_remote_changes, e)
        )
        home_logout_button = ft.IconButton(
            ft.Icons.LOGOUT,
            icon_color="red",
            tooltip="登出並刪除此裝置紀錄",
            width=42,
            height=42,
            icon_size=23,
            on_click=lambda e: page.run_task(process_logout, e)
        )
        home_title_row = ft.Row(
            [home_title_text],
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4
        )
        home_add_row = ft.Row(
            [
                list_name_input,
                home_add_button,
                home_refresh_button,
                home_logout_button
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4
        )
        home_screen = ft.Column(
            visible=True,
            width=700,
            height=820,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
            controls=[
                home_title_row,
                home_add_row,
                err_text,
                home_list_view
            ]
        )
        quick_section = ft.Container(
            width=235,
            padding=6,
            border=ft.Border.all(1, "grey"),
            border_radius=10,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("快捷項目", size=15, weight="bold", expand=True),
                            ft.IconButton(
                                ft.Icons.EDIT_OUTLINED,
                                tooltip="編輯快捷項目",
                                icon_size=18,
                                width=30,
                                height=30,
                                on_click=show_quick_edit_screen
                            )
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER
                    ),
                    quick_grid
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4
            )
        )
        def make_history_delete_button(icon_side=28, icon_size=18):
            return ft.IconButton(
                ft.Icons.DELETE_OUTLINE,
                icon_color="red",
                tooltip="刪除目前選到的歷史項目",
                icon_size=icon_size,
                width=icon_side,
                height=icon_side,
                on_click=lambda e: page.run_task(delete_selected_history_item, e)
            )
        item_add_title_container = ft.Container(width=200)
        def build_item_add_title(section_width=200):
            section_width = int(section_width or 200)
            title_width = max(70, section_width - 36)
            return ft.Row(
                [
                    ft.Text(
                        "新增項目",
                        size=16,
                        weight="bold",
                        width=title_width,
                        text_align=ft.TextAlign.CENTER
                    ),
                    make_history_delete_button(28, 18)
                ],
                width=section_width,
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4
            )
        item_add_title_container.content = build_item_add_title(200)
        def build_item_qty_controls(section_width=200):
            section_width = int(section_width or 200)
            compact = section_width < 154
            icon_side = 26 if compact else 30
            icon_size = 17 if compact else 19
            qty_width = 26 if compact else 32
            minus_button = ft.IconButton(
                ft.Icons.REMOVE_CIRCLE_OUTLINE,
                icon_size=icon_size,
                width=icon_side,
                height=icon_side,
                on_click=decrease_main_qty
            )
            plus_button = ft.IconButton(
                ft.Icons.ADD_CIRCLE_OUTLINE,
                icon_size=icon_size,
                width=icon_side,
                height=icon_side,
                on_click=increase_main_qty
            )
            main_qty_text.width = qty_width
            main_qty_text.text_align = ft.TextAlign.CENTER
            qty_controls = ft.Row(
                [minus_button, main_qty_text, plus_button],
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=0
            )
            return ft.Container(
                width=section_width,
                alignment=ft.Alignment.CENTER,
                content=qty_controls
            )
        item_add_section = ft.Container(
            width=220,
            padding=6,
            border=ft.Border.all(1, "grey"),
            border_radius=10,
            content=ft.Column(
                [
                    item_add_title_container,
                    selected_item_text,
                    item_qty_row_container := ft.Container(
                        width=200,
                        content=build_item_qty_controls(200)
                    ),
                    item_input_container := ft.Container(
                        content=desktop_item_input,
                        margin=ft.Margin(0, 0, 0, 4)
                    ),
                    add_item_button
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=6,
                scroll=None
            )
        )
        current_list_name_container = ft.Container(
            width=330,
            alignment=ft.Alignment.CENTER,
            content=ft.GestureDetector(
                on_double_tap=lambda e: ask_rename_list(current_list["name"]),
                content=current_selected_list_text
            )
        )
        async def toggle_all_current_items(e=None):
            mark_user_activity()
            list_name = current_list["name"]
            if not list_name:
                set_error("❌ 請先選擇清單")
                page.update()
                return
            items = list_items_cache.get(list_name)
            if items is None:
                await fetch_items(list_name, show_loading=True)
                items = list_items_cache.get(list_name, {})
            if not items:
                return
            new_value = any(not item.get("bought", False) for item in items.values() if isinstance(item, dict))
            updates = {}
            for item_id, item_data in items.items():
                if isinstance(item_data, dict):
                    item_data["bought"] = new_value
                    updates[f"{item_id}/bought"] = new_value
            mark_local_write()
            refresh_home_preview_after_local_change(list_name)
            clear_error()
            render_items_from_cache(list_name)
            try:
                await request_json(
                    "PATCH",
                    f"{DB_URL}/shopping_lists/{list_name}.json?auth={user_token['id']}",
                    updates
                )
            except Exception as ex:
                set_error(f"❌ 一鍵更新失敗: {repr(ex)}")
                await fetch_items(list_name, show_loading=False)
        left_panel = ft.Container(
            width=360,
            height=760,
            padding=8,
            border=ft.Border.all(1, "grey"),
            border_radius=10,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            make_center_icon(
                                ft.Icons.ARROW_BACK, "返回", show_home_screen,
                                width=42, height=34, icon_size=22
                            ),
                            ft.Row(
                                [
                                    ft.IconButton(
                                        ft.Icons.REFRESH,
                                        tooltip="重整",
                                        width=30,
                                        height=32,
                                        icon_size=17,
                                        on_click=lambda e: page.run_task(refresh_remote_changes, e)
                                    ),
                                    ft.IconButton(
                                        ft.Icons.DONE_ALL,
                                        tooltip="一鍵勾選／取消",
                                        width=30,
                                        height=32,
                                        icon_size=17,
                                        on_click=lambda e: page.run_task(toggle_all_current_items, e)
                                    ),
                                    ft.IconButton(
                                        ft.Icons.DELETE_OUTLINE,
                                        icon_color="red",
                                        tooltip="刪除目前清單",
                                        width=32,
                                        height=32,
                                        icon_size=18,
                                        on_click=lambda e: page.run_task(delete_current_list, e)
                                    )
                                ],
                                alignment=ft.MainAxisAlignment.END,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                spacing=2
                            )
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=2
                    ),
                    current_list_name_container,
                    ft.Divider(),
                    items_view
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=6
            )
        )
        right_sidebar = ft.Container(
            width=235,
            height=760,
            padding=6,
            border=ft.Border.all(1, "grey"),
            border_radius=10,
            content=ft.Column(
                [
                    quick_section,
                    item_add_section
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=6
            )
        )
        item_screen = ft.Row(
            visible=False,
            width=620,
            height=800,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.START,
            spacing=8,
            wrap=False,
            controls=[
                left_panel,
                right_sidebar
            ]
        )
        quick_edit_screen = ft.Column(
            visible=False,
            width=700,
            height=820,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=8,
            controls=[
                ft.Row(
                    [
                        make_center_icon(
                            ft.Icons.ARROW_BACK, "返回", back_from_quick_edit,
                            width=46, height=34, icon_size=22
                        )
                    ],
                    alignment=ft.MainAxisAlignment.START
                ),
                ft.Text("編輯快捷項目", size=18, weight="bold"),
                ft.Container(
                    width=410,
                    height=700,
                    padding=8,
                    border=ft.Border.all(1, "grey"),
                    border_radius=10,
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    quick_new_input,
                                    ft.Button(
                                        "新增",
                                        width=64,
                                        height=44,
                                        style=ft.ButtonStyle(
                                            text_style=ft.TextStyle(size=14)
                                        ),
                                        on_click=lambda e: page.run_task(add_quick_item, e)
                                    )
                                ],
                                alignment=ft.MainAxisAlignment.CENTER,
                                spacing=4
                            ),
                            quick_edit_list
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=6
                    )
                )
            ]
        )
        shopping_container.controls = [
            home_screen,
            item_screen,
            quick_edit_screen
        ]
        quick_new_input.on_change = on_quick_new_input_change
        quick_new_input.on_submit = lambda e: page.run_task(add_quick_item, e)
        def apply_responsive_layout(e=None):
            screen_width = int(page.width or page.window_width or 720)
            screen_height = int(page.height or page.window_height or 850)
            is_mobile = screen_width < 650
            is_mobile_layout["value"] = is_mobile
            page.scroll = ft.ScrollMode.AUTO

            # Move main screens down on mobile to avoid notch / system status bar.
            safe_top = MOBILE_SAFE_TOP_PADDING if is_mobile else 0
            top_margin = ft.Margin(0, safe_top, 0, 0) if is_mobile else ft.Margin(0, 0, 0, 0)

            try:
                login_container.margin = top_margin
                idle_container.margin = top_margin
                shopping_container.margin = top_margin
            except Exception:
                pass

            def clamp(value, min_value, max_value):
                return max(min_value, min(value, max_value))
            if is_mobile:
                usable_width = max(280, screen_width - 8)
                usable_height = max(420, screen_height - safe_top - 8)
                row_gap = 2 if usable_width < 360 else 4
                right_width = int(usable_width * 0.42)
                right_width = clamp(right_width, 118, 190)
                left_width = usable_width - right_width - row_gap
                if left_width < 145:
                    left_width = 145
                    right_width = usable_width - left_width - row_gap
                right_width = max(108, right_width)
                left_padding = 4 if usable_width < 360 else 5
                right_padding = 3 if usable_width < 360 else 4
                section_padding = 3 if usable_width < 360 else 4
                left_content_width = max(120, left_width - left_padding * 2 - 4)
                right_content_width = max(96, right_width - right_padding * 2 - 4)
                section_inner_width = max(88, right_content_width - section_padding * 2 - 4)
                outer_margin = 4
                item_area_height = max(360, usable_height - outer_margin)
                shopping_container.width = usable_width
                shopping_container.height = item_area_height
                shopping_container.spacing = 0
                home_screen.width = usable_width
                home_screen.height = item_area_height

                # Mobile home overview: keep refresh/logout visible in the title row.
                # The add-list input stays on a separate row so the right-side icons
                # will not be clipped on narrow phones.
                home_title_text.width = max(120, usable_width - 104)
                home_title_text.size = 22
                home_title_text.text_align = ft.TextAlign.LEFT
                home_title_row.width = usable_width - 8
                home_title_row.controls = [
                    home_title_text,
                    home_refresh_button,
                    home_logout_button
                ]
                home_title_row.alignment = ft.MainAxisAlignment.SPACE_BETWEEN
                home_add_row.width = usable_width - 8
                home_add_row.controls = [
                    list_name_input,
                    home_add_button
                ]
                home_add_row.alignment = ft.MainAxisAlignment.CENTER
                home_add_button.width = 42
                home_add_button.height = 42
                home_refresh_button.width = 42
                home_refresh_button.height = 42
                home_logout_button.width = 42
                home_logout_button.height = 42
                list_name_input.width = max(190, usable_width - 62)
                home_list_view.width = usable_width - 8
                home_list_view.height = max(260, item_area_height - 122)
                item_screen.width = usable_width
                item_screen.height = item_area_height
                item_screen.wrap = False
                item_screen.spacing = row_gap
                item_screen.alignment = ft.MainAxisAlignment.START
                item_screen.controls = [
                    left_panel,
                    right_sidebar
                ]
                left_panel.width = left_width
                left_panel.height = item_area_height
                left_panel.padding = left_padding
                right_sidebar.width = right_width
                right_sidebar.height = item_area_height
                right_sidebar.padding = right_padding
                left_content_height = max(240, item_area_height - left_padding * 2 - 118)
                right_content_height = max(300, item_area_height - right_padding * 2 - 4)
                compact_add_qty = section_inner_width < 132
                add_input_height = 54 if usable_height >= 620 else 50
                add_button_height = 42 if usable_height >= 620 else 38
                add_qty_height = 58 if compact_add_qty else 34
                # Fit title, current item text, qty controls, input field, add button and spacing.
                # Keep this section just tall enough so no internal scroll bar appears.
                needed_add_height = (
                    34 + 24 + add_qty_height + add_input_height +
                    add_button_height + 42 + section_padding * 2
                )
                if usable_height < 600:
                    needed_add_height = max(218, needed_add_height - 6)
                max_add_height = min(300, max(needed_add_height, right_content_height - 105))
                item_add_height = clamp(needed_add_height, needed_add_height, max_add_height)
                quick_section_height = max(135, right_content_height - item_add_height - 6)
                if quick_section_height + item_add_height + 6 > right_content_height:
                    quick_section_height = max(90, right_content_height - item_add_height - 6)
                quick_section.width = right_content_width
                quick_section.height = quick_section_height
                quick_section.padding = section_padding
                quick_grid.width = section_inner_width
                quick_grid.height = max(150, quick_section_height - section_padding * 2 - 32)
                item_add_section.width = right_content_width
                item_add_section.height = item_add_height
                item_add_section.padding = section_padding
                item_add_title_container.width = max(92, section_inner_width)
                item_add_title_container.content = build_item_add_title(item_add_title_container.width)
                items_view.width = left_content_width
                items_view.height = left_content_height
                current_list_name_container.width = left_content_width
                current_list_name_container.alignment = ft.Alignment.CENTER_LEFT
                current_selected_list_text.width = left_content_width
                item_qty_row_container.width = max(92, section_inner_width)
                item_qty_row_container.content = build_item_qty_controls(item_qty_row_container.width)
                mobile_item_input.width = max(100, section_inner_width)
                mobile_item_input.height = add_input_height
                mobile_item_button.width = mobile_item_input.width
                mobile_item_button.height = mobile_item_input.height
                try:
                    mobile_item_input.read_only = True
                except Exception:
                    pass
                item_dropdown.width = mobile_item_input.width
                item_dropdown.height = mobile_item_input.height
                item_dropdown.menu_width = min(280, max(180, screen_width - 24))
                item_dropdown.menu_height = max(180, min(260, item_area_height - 130))
                desktop_item_input.width = mobile_item_input.width
                desktop_item_input.height = mobile_item_input.height
                item_input_container.content = mobile_item_button
                update_mobile_item_button_label()
                history_suggestion_panel.width = mobile_item_input.width
                force_item_dropdown_menu_up()
                refresh_history_dropdown_options()
                selected_item_text.width = section_inner_width
                add_item_button.width = section_inner_width
                add_item_button.height = add_button_height
                quick_edit_box = quick_edit_screen.controls[2]
                quick_edit_screen.width = usable_width
                quick_edit_screen.height = item_area_height
                quick_edit_screen.scroll = ft.ScrollMode.AUTO
                quick_edit_box.width = usable_width - 12
                quick_edit_box.height = max(280, item_area_height - 82)
                quick_edit_box.padding = 6
                quick_edit_list.width = quick_edit_box.width - 16
                quick_edit_list.height = max(190, quick_edit_box.height - 76)
                quick_new_input.width = max(150, min(quick_edit_list.width - 68, quick_edit_box.width - 82))
            else:
                shopping_container.width = 700
                shopping_container.height = 820
                shopping_container.spacing = 8
                home_screen.width = 700
                home_screen.height = 820

                # Desktop home overview: keep the original single control row.
                home_title_text.width = None
                home_title_text.size = 24
                home_title_text.text_align = ft.TextAlign.CENTER
                home_title_row.width = None
                home_title_row.controls = [home_title_text]
                home_title_row.alignment = ft.MainAxisAlignment.CENTER
                home_add_row.width = None
                home_add_row.controls = [
                    list_name_input,
                    home_add_button,
                    home_refresh_button,
                    home_logout_button
                ]
                home_add_row.alignment = ft.MainAxisAlignment.CENTER
                home_add_button.width = 42
                home_add_button.height = 42
                home_refresh_button.width = 42
                home_refresh_button.height = 42
                home_logout_button.width = 42
                home_logout_button.height = 42
                list_name_input.width = 300
                home_list_view.width = 660
                home_list_view.height = 640
                item_screen.width = 620
                item_screen.height = 800
                item_screen.wrap = False
                item_screen.spacing = 8
                item_screen.alignment = ft.MainAxisAlignment.CENTER
                item_screen.controls = [
                    left_panel,
                    right_sidebar
                ]
                left_panel.width = 360
                left_panel.height = 760
                left_panel.padding = 8
                right_sidebar.width = 235
                right_sidebar.height = 760
                right_sidebar.padding = 6
                quick_section.width = 235
                quick_section.padding = 6
                quick_section.height = None
                quick_grid.width = 235
                quick_grid.height = 260
                item_add_section.width = 220
                item_add_section.padding = 6
                item_add_section.height = None
                item_add_title_container.width = 200
                item_add_title_container.content = build_item_add_title(item_add_title_container.width)
                items_view.width = 340
                items_view.height = 650
                current_list_name_container.width = 340
                current_list_name_container.alignment = ft.Alignment.CENTER_LEFT
                current_selected_list_text.width = 340
                item_qty_row_container.width = 200
                item_qty_row_container.content = build_item_qty_controls(item_qty_row_container.width)
                item_dropdown.width = 200
                item_dropdown.height = 50
                item_dropdown.menu_width = 260
                item_dropdown.menu_height = 260
                desktop_item_input.width = 200
                desktop_item_input.height = 50
                mobile_item_input.width = desktop_item_input.width
                mobile_item_input.height = desktop_item_input.height
                mobile_item_button.width = desktop_item_input.width
                mobile_item_button.height = desktop_item_input.height
                try:
                    mobile_item_input.read_only = False
                except Exception:
                    pass
                item_input_container.content = desktop_item_input
                history_suggestion_panel.width = desktop_item_input.width
                force_item_dropdown_menu_up()
                hide_history_suggestions()
                refresh_history_dropdown_options()
                selected_item_text.width = None
                add_item_button.width = 160
                add_item_button.height = 36
                quick_edit_box = quick_edit_screen.controls[2]
                quick_edit_screen.width = 700
                quick_edit_screen.height = 820
                quick_edit_screen.scroll = None
                quick_edit_box.width = 410
                quick_edit_box.height = 700
                quick_edit_box.padding = 8
                quick_edit_list.width = 380
                quick_edit_list.height = 620
                quick_new_input.width = 220
            refresh_quick_grid()
            refresh_quick_edit_list()
            if current_list["name"]:
                render_items_from_cache(current_list["name"])
            page.update()
        page.on_resize = lambda e: (mark_user_activity(), apply_responsive_layout(e))
        try:
            page.on_keyboard_event = lambda e: mark_user_activity()
        except Exception:
            pass
        for scroll_control in [home_list_view, items_view, quick_grid, quick_edit_list]:
            try:
                scroll_control.on_scroll = lambda e: mark_user_activity()
            except Exception:
                pass
        page.add(shopping_container)
        page.update()
        apply_responsive_layout()
        refresh_quick_ui()
        force_item_dropdown_menu_up()
        refresh_history_dropdown_options()
        async def delayed_initial_layout():
            await asyncio.sleep(0.1)
            apply_responsive_layout()
            await asyncio.sleep(0.25)
            apply_responsive_layout()
        page.run_task(delayed_initial_layout)
    def show_startup_loading():
        build_main_ui_once()
        login_container.visible = False
        idle_container.visible = False
        shopping_container.visible = True
        home_screen.visible = True
        item_screen.visible = False
        quick_edit_screen.visible = False
        if list_names_cache:
            render_home_lists()
        else:
            home_list_view.controls.clear()
            home_list_view.controls.append(
                ft.Text("載入清單中...", color="grey")
            )
        clear_error()
        page.update()
    def show_login_screen():
        system_closed_by_idle["value"] = False
        idle_container.visible = False
        shopping_container.visible = False
        login_container.visible = True
        page.update()

    def close_system_without_logout():
        if system_closed_by_idle["value"]:
            return
        if not main_ui_built["value"]:
            return
        if not user_token["id"] or not shopping_container.visible:
            return
        system_closed_by_idle["value"] = True
        current_list_auto_syncing["value"] = False
        home_auto_syncing["value"] = False
        hide_history_suggestions()
        remove_history_overlay()
        shopping_container.visible = False
        login_container.visible = False
        idle_container.visible = True
        clear_error()
        page.update()

    async def reopen_system_after_idle(e=None):
        mark_user_activity()
        system_closed_by_idle["value"] = False
        build_main_ui_once()
        idle_container.visible = False
        login_container.visible = False
        shopping_container.visible = True
        page.update()
        try:
            if user_token["refresh"]:
                ok = await login_with_refresh_token(user_token["refresh"])
                if ok:
                    return
            elif user_token["id"]:
                await refresh_remote_changes(show_status=False)
                return
        except Exception as ex:
            print(f"重新開啟系統失敗: {repr(ex)}")
        show_login_screen()

    async def login_with_refresh_token(saved_refresh_token):
        if not saved_refresh_token:
            return False
        refresh_data = await request_json(
            "POST",
            AUTH_REFRESH,
            {
                "grant_type": "refresh_token",
                "refresh_token": saved_refresh_token
            }
        )
        if not isinstance(refresh_data, dict) or "id_token" not in refresh_data:
            return False
        user_token["id"] = refresh_data.get("id_token")
        user_token["refresh"] = refresh_data.get("refresh_token") or saved_refresh_token
        user_token["uid"] = refresh_data.get("user_id")
        if user_token["refresh"]:
            await prefs.set("shopping_refresh_token", user_token["refresh"])
        if user_token["uid"]:
            await prefs.set("shopping_uid", user_token["uid"])
        user_data = await request_json(
            "GET",
            f"{DB_URL}/users/{user_token['uid']}.json?auth={user_token['id']}"
        )
        if not (isinstance(user_data, dict) and user_data.get("is_approved")):
            return False
        build_main_ui_once()
        login_container.visible = False
        shopping_container.visible = True
        clear_error()
        page.update()
        page.run_task(load_metadata_safely)
        return True
    async def auto_login():
        await asyncio.sleep(0.05)
        try:
            has_refresh = await prefs.contains_key("shopping_refresh_token")
            if has_refresh:
                saved_refresh_token = await prefs.get("shopping_refresh_token")
                if saved_refresh_token:
                    show_startup_loading()
                    # Startup fast path: draw the small local summary first.
                    # The large full-list local cache and Firebase refresh run in the background.
                    await load_home_summary_cache_local()
                    page.run_task(load_full_home_cache_local, False)
                    ok = await login_with_refresh_token(saved_refresh_token)
                    if ok:
                        print("使用 refreshToken 自動登入")
                        return
                    show_login_screen()
            has_email = await prefs.contains_key("shopping_email")
            has_password = await prefs.contains_key("shopping_password")
            if not has_email or not has_password:
                show_login_screen()
                return
            saved_email = await prefs.get("shopping_email")
            saved_password = await prefs.get("shopping_password")
            if not saved_email or not saved_password:
                show_login_screen()
                return
            email_in.value = saved_email
            pass_in.value = saved_password
            page.update()
            print(f"自動登入帳號: {saved_email}")
            await process_login(None)
        except Exception as e:
            show_login_screen()
            print(f"自動登入失敗: {repr(e)}")
    async def idle_close_loop():
        while True:
            await asyncio.sleep(
                SLEEP_IDLE_CHECK_SECONDS
                if system_closed_by_idle["value"]
                else ACTIVE_IDLE_CHECK_SECONDS
            )
            try:
                if system_closed_by_idle["value"]:
                    continue
                if not user_token["id"] or not shopping_container.visible:
                    continue
                idle_seconds = (datetime.datetime.now() - last_activity_at["value"]).total_seconds()
                if idle_seconds >= IDLE_CLOSE_SECONDS:
                    close_system_without_logout()
            except Exception as ex:
                print(f"閒置檢查失敗: {repr(ex)}")

    async def hard_text_limit_loop():
        while True:
            await asyncio.sleep(INPUT_LIMIT_CHECK_SECONDS)
            try:
                if system_closed_by_idle["value"]:
                    await asyncio.sleep(SLEEP_IDLE_CHECK_SECONDS)
                    continue
                if limit_all_typing_fields_now():
                    update_selected_item_text()
                    page.update()
            except Exception as ex:
                print(f"文字長度即時限制失敗: {repr(ex)}")

    page.run_task(auto_login)
    page.run_task(auto_sync_current_list_loop)
    page.run_task(auto_sync_home_loop)
    page.run_task(idle_close_loop)
    page.run_task(hard_text_limit_loop)
if __name__ == "__main__":
    ft.run(main, assets_dir="assets")
