from __future__ import annotations

import calendar
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Dict, Sequence, Tuple

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, ObjectProperty, StringProperty
from kivy.resources import resource_find
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label

BASE_PATTERN: Tuple[str, ...] = ("День", "Ночь", "Отсыпной", "Выходной")

SHIFT_COLORS = {
    "День": (1.0, 0.2, 0.2, 1),
    "Ночь": (0.2, 0.6, 1.0, 1),
    "Отсыпной": (0.6, 1.0, 0.6, 1),
    "Выходной": (0.88, 0.88, 0.88, 1),
    "Отпуск": (0.74, 0.74, 0.74, 1),
    "Пусто": (0.60, 0.60, 0.60, 1),
}

WEEKDAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS_RU = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}


def date_range(start_date: date, end_date: date):
    if start_date > end_date:
        raise ValueError("start_date не может быть позже end_date")
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def parse_date_ddmmyyyy(text: str) -> date:
    return datetime.strptime(text.strip(), "%d.%m.%Y").date()


def months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month) + 1


def parse_pattern_text(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"[,\n;]+", text) if p.strip()]
    return parts


def resolve_pattern_shift(
    day: date,
    base_pattern: Sequence[str],
    base_start_index: int = 0,
    cycle_anchor_date: date | None = None,
    pattern_resets: Sequence[tuple[date, int]] | None = None,
) -> str:
    if not base_pattern:
        raise ValueError("base_pattern не может быть пустым")

    if cycle_anchor_date is None:
        cycle_anchor_date = day

    active_anchor_date = cycle_anchor_date
    active_start_index = base_start_index

    for reset_date, reset_index in pattern_resets or ():
        if reset_date <= day:
            active_anchor_date = reset_date
            active_start_index = reset_index
        else:
            break

    offset_days = (day - active_anchor_date).days
    return base_pattern[(active_start_index + offset_days) % len(base_pattern)]


def build_schedule(
    start_date: date,
    end_date: date,
    base_pattern: Sequence[str] = BASE_PATTERN,
    base_start_index: int = 0,
    cycle_anchor_date: date | None = None,
    manual_shifts: Dict[date, str] | None = None,
    pattern_resets: Sequence[tuple[date, int]] | None = None,
) -> Dict[date, dict]:
    if not base_pattern:
        raise ValueError("base_pattern не может быть пустым")

    if manual_shifts is None:
        manual_shifts = {}

    if cycle_anchor_date is None:
        cycle_anchor_date = start_date

    resets = sorted(pattern_resets or [], key=lambda item: item[0])
    result: Dict[date, dict] = {}

    for day in date_range(start_date, end_date):
        base_shift = resolve_pattern_shift(
            day=day,
            base_pattern=base_pattern,
            base_start_index=base_start_index,
            cycle_anchor_date=cycle_anchor_date,
            pattern_resets=resets,
        )
        final_shift = manual_shifts.get(day, base_shift)
        result[day] = {
            "date": day,
            "shift": final_shift,
            "base_shift": base_shift,
            "manual": day in manual_shifts,
        }

    return result


@dataclass
class MonthState:
    year: int
    month: int


class ShiftDayButton(Button):
    def __init__(self, day_date: date | None = None, **kwargs):
        super().__init__(**kwargs)
        self.day_date = day_date
        self.background_normal = ""
        self.background_down = ""
        self.font_size = dp(13)
        self.halign = "center"
        self.valign = "middle"
        self.text_size = self.size
        self.bind(size=self._update_text_size)

    def _update_text_size(self, *args):
        self.text_size = self.size


class RoundedTextInput(Button):
    _active_input = None

    focus = BooleanProperty(False)
    hint_text = StringProperty("")
    background_active = StringProperty("")
    cursor_color = ListProperty([0, 0, 0, 1])
    disabled_foreground_color = ListProperty([0, 0, 0, 1])
    foreground_color = ListProperty([0, 0, 0, 1])
    hint_text_color = ListProperty([0.4, 0.4, 0.4, 1])
    selection_color = ListProperty([0.2, 0.6, 1, 0.35])
    readonly = BooleanProperty(False)
    write_tab = BooleanProperty(False)
    multiline = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._keyboard = None
        self._textinput_bound = False
        self.background_normal = ""
        self.background_down = ""
        self.background_color = (0, 0, 0, 0)
        self.halign = "left"
        self.valign = "middle"
        self.bind(size=self._update_text_size, foreground_color=self._sync_text_color)
        self._sync_text_color()

    def _sync_text_color(self, *_):
        self.color = self.foreground_color

    def _update_text_size(self, *_):
        self.text_size = (
            max(0, self.width - dp(28)),
            max(0, self.height - dp(8)),
        )

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self.request_text_focus()
            return True

        if self.focus:
            self.release_text_focus()
        return super().on_touch_down(touch)

    def request_text_focus(self):
        if self.readonly:
            return

        if RoundedTextInput._active_input is not None and RoundedTextInput._active_input is not self:
            RoundedTextInput._active_input.release_text_focus()
        RoundedTextInput._active_input = self

        self.focus = True
        if self._keyboard is None:
            self._keyboard = Window.request_keyboard(self._keyboard_closed, self, "text")
            if self._keyboard is not None:
                self._keyboard.bind(on_key_down=self._on_keyboard_down)
                Window.bind(on_textinput=self._on_textinput)
                self._textinput_bound = True

    def release_text_focus(self):
        if self._keyboard is not None:
            self._keyboard.unbind(on_key_down=self._on_keyboard_down)
            if self._textinput_bound:
                Window.unbind(on_textinput=self._on_textinput)
                self._textinput_bound = False
            self._keyboard.release()
            self._keyboard = None
        if RoundedTextInput._active_input is self:
            RoundedTextInput._active_input = None
        self.focus = False

    def _keyboard_closed(self):
        if self._textinput_bound:
            Window.unbind(on_textinput=self._on_textinput)
            self._textinput_bound = False
        self._keyboard = None
        if RoundedTextInput._active_input is self:
            RoundedTextInput._active_input = None
        self.focus = False

    def _on_textinput(self, window, text):
        if self.focus and not self.readonly and text:
            self.text += text
            return True
        return False

    def _on_keyboard_down(self, keyboard, keycode, text, modifiers):
        modifiers = modifiers or []
        key_name = keycode[1] if isinstance(keycode, tuple) else str(keycode)

        if key_name == "backspace":
            self.text = self.text[:-1]
            return True
        if key_name == "delete":
            self.text = ""
            return True
        if key_name in {"enter", "numenter"}:
            if self.multiline:
                self.text += "\n"
            else:
                self.release_text_focus()
            return True
        if key_name == "escape":
            self.release_text_focus()
            return True
        if key_name == "tab":
            if self.write_tab:
                self.text += "\t"
            else:
                self.release_text_focus()
            return True

        return False


class PatternTextInput(RoundedTextInput):
    pass


Factory.register("RoundedTextInput", cls=RoundedTextInput)
Factory.register("PatternTextInput", cls=PatternTextInput)


class CalendarAppRoot(BoxLayout):
    base_pattern = ListProperty(list(BASE_PATTERN))
    months_count = NumericProperty(12)
    base_start_index = NumericProperty(0)
    selected_day = ObjectProperty(None, allownone=True)
    auto_adjust_following = BooleanProperty(False)
    controls_expanded = BooleanProperty(False)

    def __init__(self, **kwargs):
        today = date.today()
        self.ui_font_name = resource_find("Roboto-Regular.ttf") or "Roboto"
        self.ui_font_bold = resource_find("Roboto-Bold.ttf") or self.ui_font_name

        self.start_month = MonthState(today.year, today.month)
        self.current_month = MonthState(today.year, today.month)

        self.cycle_anchor_date = date(today.year, today.month, 1)

        self.months_loaded: list[tuple[int, int]] = []
        self.manual_shifts: Dict[date, str] = {}
        self.day_notes: Dict[date, str] = {}
        self._state_loaded = False
        self._last_append_ts = 0.0
        self._syncing_toggle = False

        super().__init__(**kwargs)
        Clock.schedule_once(self._post_init, 0)

    def _post_init(self, *_):
        if self._state_loaded:
            return
        self._state_loaded = True
        self.load_state()
        self.load_initial_months()
        self.update_selected_widgets()

    def get_save_path(self) -> Path:
        app = App.get_running_app()
        if app is None:
            return Path("shift_calendar_data.json")
        save_dir = Path(app.user_data_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        return save_dir / "shift_calendar_data.json"

    def save_state(self):
        save_file = self.get_save_path()
        data = {
            "start_month": {
                "year": self.start_month.year,
                "month": self.start_month.month,
            },
            "months_count": int(self.months_count),
            "base_start_index": int(self.base_start_index),
            "base_pattern": list(self.base_pattern),
            "cycle_anchor_date": self.cycle_anchor_date.isoformat(),
            "manual_shifts": {
                day.isoformat(): shift for day, shift in self.manual_shifts.items()
            },
            "day_notes": {
                day.isoformat(): note for day, note in self.day_notes.items()
            },
            "auto_adjust_following": bool(self.auto_adjust_following),
            "controls_expanded": bool(self.controls_expanded),
            "date_search_input": self.ids.date_search_input.text if "date_search_input" in self.ids else "",
            "start_input": self.ids.start_input.text if "start_input" in self.ids else "",
            "end_input": self.ids.end_input.text if "end_input" in self.ids else "",
            "range_pattern_input": self.ids.range_pattern_input.text if "range_pattern_input" in self.ids else "",
            "selected_day": self.selected_day.isoformat() if self.selected_day else "",
        }

        try:
            save_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def load_state(self):
        save_file = self.get_save_path()
        if not save_file.exists():
            return

        try:
            data = json.loads(save_file.read_text(encoding="utf-8"))
        except Exception:
            return

        start_month = data.get("start_month")
        if isinstance(start_month, dict):
            year = start_month.get("year")
            month = start_month.get("month")
            if isinstance(year, int) and isinstance(month, int):
                self.start_month = MonthState(year, month)
                self.current_month = MonthState(year, month)

        months_count = data.get("months_count")
        if isinstance(months_count, int) and months_count > 0:
            self.months_count = months_count

        base_start_index = data.get("base_start_index")
        if isinstance(base_start_index, int):
            self.base_start_index = base_start_index

        base_pattern = data.get("base_pattern")
        if isinstance(base_pattern, list) and base_pattern:
            self.base_pattern = [str(x) for x in base_pattern]

        anchor = data.get("cycle_anchor_date")
        if isinstance(anchor, str) and anchor:
            try:
                self.cycle_anchor_date = date.fromisoformat(anchor)
            except Exception:
                pass

        manual = data.get("manual_shifts", {})
        if isinstance(manual, dict):
            loaded = {}
            for key, value in manual.items():
                try:
                    loaded[date.fromisoformat(key)] = str(value)
                except Exception:
                    continue
            self.manual_shifts = loaded

        notes = data.get("day_notes", {})
        if isinstance(notes, dict):
            loaded_notes = {}
            for key, value in notes.items():
                try:
                    note = str(value).strip()
                    if note:
                        loaded_notes[date.fromisoformat(key)] = note
                except Exception:
                    continue
            self.day_notes = loaded_notes

        auto_adjust_following = data.get("auto_adjust_following")
        if isinstance(auto_adjust_following, bool):
            self.auto_adjust_following = auto_adjust_following

        controls_expanded = data.get("controls_expanded")
        if isinstance(controls_expanded, bool):
            self.controls_expanded = controls_expanded

        if "start_input" in self.ids and isinstance(data.get("start_input"), str):
            self.ids.start_input.text = data["start_input"] or self.default_start_text()
        if "end_input" in self.ids and isinstance(data.get("end_input"), str):
            self.ids.end_input.text = data["end_input"] or self.default_end_text()
        if "range_pattern_input" in self.ids and isinstance(data.get("range_pattern_input"), str):
            self.ids.range_pattern_input.text = data["range_pattern_input"] or "День,Ночь,Ночь,День"
        if "date_search_input" in self.ids and isinstance(data.get("date_search_input"), str):
            self.ids.date_search_input.text = data["date_search_input"] or "03.06.2026"

        selected_day = data.get("selected_day")
        if isinstance(selected_day, str) and selected_day:
            try:
                self.selected_day = date.fromisoformat(selected_day)
            except Exception:
                self.selected_day = None

        self.update_selected_widgets()

    def month_name(self, month: int) -> str:
        return MONTHS_RU.get(month, "")

    def month_text(self, year: int, month: int) -> str:
        return f"{self.month_name(month)} {year}"

    def default_start_text(self) -> str:
        today = date.today()
        return today.replace(day=1).strftime("%d.%m.%Y")

    def default_end_text(self) -> str:
        today = date.today()
        last_day_num = calendar.monthrange(today.year, today.month)[1]
        return date(today.year, today.month, last_day_num).strftime("%d.%m.%Y")

    def selected_day_text(self) -> str:
        if self.selected_day is None:
            return "Выбранный день: нет"
        return f"Выбранный день: {self.selected_day.strftime('%d.%m.%Y')}"

    def shift_short(self, shift: str) -> str:
        mapping = {
            "День": "День",
            "Ночь": "Ночь",
            "Отсыпной": "Отсыпной",
            "Выходной": "Выходной",
            "Отпуск": "Отпуск",
        }
        return mapping.get(shift, shift[:1].upper() if shift else "")

    def selected_note_text(self) -> str:
        if self.selected_day is None:
            return ""
        return self.day_notes.get(self.selected_day, "")

    def pattern_index_for_shift(self, shift: str) -> int | None:
        try:
            return list(self.base_pattern).index(shift)
        except ValueError:
            return None

    def next_pattern_index_for_shift(self, shift: str) -> int:
        current_index = self.pattern_index_for_shift(shift)
        if current_index is None:
            return int(self.base_start_index) % len(self.base_pattern)
        return (current_index + 1) % len(self.base_pattern)

    def get_pattern_resets(self) -> list[tuple[date, int]]:
        if not self.auto_adjust_following or not self.manual_shifts:
            return []

        resets: list[tuple[date, int]] = []
        sorted_days = [
            day for day in sorted(self.manual_shifts)
            if self.manual_shifts[day] in self.base_pattern
        ]
        if not sorted_days:
            return []

        block_end = sorted_days[0]
        last_shift = self.manual_shifts[block_end]

        for current_day in sorted_days[1:]:
            if current_day == block_end + timedelta(days=1):
                block_end = current_day
                last_shift = self.manual_shifts[current_day]
                continue

            resets.append(
                (
                    block_end + timedelta(days=1),
                    self.next_pattern_index_for_shift(last_shift),
                )
            )
            block_end = current_day
            last_shift = self.manual_shifts[current_day]

        resets.append(
            (
                block_end + timedelta(days=1),
                self.next_pattern_index_for_shift(last_shift),
            )
        )
        return resets

    def base_shift_for_day(self, day: date) -> str:
        return resolve_pattern_shift(
            day=day,
            base_pattern=self.base_pattern,
            base_start_index=self.base_start_index,
            cycle_anchor_date=self.cycle_anchor_date,
            pattern_resets=self.get_pattern_resets(),
        )

    def update_selected_widgets(self):
        if "selected_day_label" in self.ids:
            self.ids.selected_day_label.text = self.selected_day_text()

        if "shift_spinner" in self.ids:
            if self.selected_day is None:
                self.ids.shift_spinner.text = self.base_pattern[0] if self.base_pattern else "День"
            else:
                self.ids.shift_spinner.text = self.manual_shifts.get(
                    self.selected_day,
                    self.base_shift_for_day(self.selected_day),
                )

        if "adjust_following_checkbox" in self.ids:
            self._syncing_toggle = True
            self.ids.adjust_following_checkbox.active = self.auto_adjust_following
            self._syncing_toggle = False

        if "day_note_input" in self.ids:
            self.ids.day_note_input.text = self.selected_note_text()

    def add_months(self, year: int, month: int, offset: int) -> tuple[int, int]:
        total = (year * 12 + (month - 1)) + offset
        new_year = total // 12
        new_month = total % 12 + 1
        return new_year, new_month

    def load_initial_months(self):
        if "months_container" not in self.ids:
            return

        scroll_y = self.ids.months_scroll.scroll_y if "months_scroll" in self.ids else 1

        container = self.ids.months_container
        container.clear_widgets()
        self.months_loaded = []

        year = self.start_month.year
        month = self.start_month.month
        pattern_resets = self.get_pattern_resets()

        for i in range(int(self.months_count)):
            y, m = self.add_months(year, month, i)
            self.add_month_widget(y, m, pattern_resets=pattern_resets)
            self.months_loaded.append((y, m))

        Clock.schedule_once(lambda dt: self._restore_scroll(scroll_y), 0)

    def _restore_scroll(self, scroll_y: float):
        if "months_scroll" in self.ids:
            self.ids.months_scroll.scroll_y = scroll_y

    def add_month_widget(
        self,
        year: int,
        month: int,
        pattern_resets: Sequence[tuple[date, int]] | None = None,
    ):
        month_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        month_box.bind(minimum_height=month_box.setter("height"))

        title = Label(
            text=self.month_text(year, month),
            size_hint_y=None,
            height=dp(24),
            font_size="16sp",
            bold=True,
            halign="left",
            valign="middle",
            color=(1, 1, 1, 1),
        )
        title.bind(size=lambda instance, size: setattr(instance, "text_size", size))
        month_box.add_widget(title)

        week_header = GridLayout(cols=7, size_hint_y=None, height=dp(28), spacing=dp(4))
        for name in WEEKDAY_NAMES:
            lbl = Label(
                text=name,
                bold=True,
                color=(1, 1, 1, 1),
                halign="center",
                valign="middle",
            )
            lbl.bind(size=lambda instance, size: setattr(instance, "text_size", size))
            week_header.add_widget(lbl)
        month_box.add_widget(week_header)

        days_grid = GridLayout(
            cols=7,
            size_hint_y=None,
            spacing=dp(4),
            padding=dp(2),
            row_force_default=True,
            row_default_height=dp(56),
        )
        days_grid.bind(minimum_height=days_grid.setter("height"))

        first_day = date(year, month, 1)
        last_day_num = calendar.monthrange(year, month)[1]
        last_day = date(year, month, last_day_num)

        weekday_index = first_day.weekday()
        for _ in range(weekday_index):
            days_grid.add_widget(Label(text="", size_hint_y=None, height=dp(56)))

        schedule = build_schedule(
            start_date=first_day,
            end_date=last_day,
            base_pattern=self.base_pattern,
            base_start_index=self.base_start_index,
            cycle_anchor_date=self.cycle_anchor_date,
            manual_shifts=self.manual_shifts,
            pattern_resets=pattern_resets,
        )

        for day in date_range(first_day, last_day):
            item = schedule[day]
            shift = item["shift"]
            short_shift = self.shift_short(shift)
            day_color = SHIFT_COLORS.get(shift, SHIFT_COLORS["Пусто"])
            note_mark = " *" if day in self.day_notes else ""

            btn = ShiftDayButton(
                day_date=day,
                text=f"{day.day}{note_mark}\n{short_shift}",
                size_hint_y=None,
                height=dp(56),
                background_color=day_color,
                color=(0, 0, 0, 1),
            )

            if self.selected_day == day:
                btn.background_color = (0.25, 0.55, 0.95, 1)
                btn.color = (1, 1, 1, 1)

            btn.bind(on_press=self.on_day_press)
            days_grid.add_widget(btn)

        used_cells = weekday_index + len(list(date_range(first_day, last_day)))
        remainder = used_cells % 7
        if remainder != 0:
            for _ in range(7 - remainder):
                days_grid.add_widget(Label(text="", size_hint_y=None, height=dp(56)))

        month_box.add_widget(days_grid)
        self.ids.months_container.add_widget(month_box)

    def append_next_month(self):
        if "months_container" not in self.ids:
            return

        if self.months_loaded:
            last_year, last_month = self.months_loaded[-1]
            y, m = self.add_months(last_year, last_month, 1)
        else:
            y, m = self.start_month.year, self.start_month.month

        self.add_month_widget(y, m, pattern_resets=self.get_pattern_resets())
        self.months_loaded.append((y, m))

    def on_scroll_y(self, scrollview, value):
        if value <= 0.08 and monotonic() - self._last_append_ts > 0.45:
            self._last_append_ts = monotonic()
            self.append_next_month()

    def toggle_controls_panel(self, *_):
        self.controls_expanded = not self.controls_expanded
        self.save_state()

    def go_to_today(self, *_):
        today = date.today()
        self.start_month = MonthState(today.year, today.month)
        self.current_month = MonthState(today.year, today.month)
        self.selected_day = today
        self.months_count = 12
        self.load_initial_months()
        self.update_selected_widgets()
        self.save_state()

    def find_date(self, *_):
        if "date_search_input" not in self.ids:
            return

        try:
            target_day = parse_date_ddmmyyyy(self.ids.date_search_input.text)
        except Exception:
            self.ids.info_label.text = "Неверная дата для поиска. Нужно дд.мм.гггг"
            return

        self.start_month = MonthState(target_day.year, target_day.month)
        self.current_month = MonthState(target_day.year, target_day.month)
        self.months_count = max(int(self.months_count), 12)
        self.selected_day = target_day
        self.ids.info_label.text = f"Найдена дата: {target_day.strftime('%d.%m.%Y')}"
        self.save_state()
        self.refresh_calendar()

    def refresh_calendar(self):
        self.load_initial_months()
        self.update_selected_widgets()

    def on_auto_adjust_toggle(self, active: bool):
        if self._syncing_toggle:
            return
        self.auto_adjust_following = bool(active)
        if "info_label" in self.ids:
            if self.auto_adjust_following:
                self.ids.info_label.text = "Автоподстройка следующих смен включена."
            else:
                self.ids.info_label.text = "Автоподстройка следующих смен выключена."
        self.save_state()
        self.refresh_calendar()

    def clear_selected_day(self, *_):
        if self.selected_day and self.selected_day in self.manual_shifts:
            del self.manual_shifts[self.selected_day]
            self.ids.info_label.text = f"Смена на {self.selected_day.strftime('%d.%m.%Y')} сброшена"
        else:
            self.ids.info_label.text = "Для выбранного дня нет ручной смены."
        self.save_state()
        self.refresh_calendar()

    def clear_all_manual_shifts(self, *_):
        self.manual_shifts.clear()
        self.ids.info_label.text = "Все ручные смены сброшены."
        self.save_state()
        self.refresh_calendar()

    def apply_selected_shift(self, *_):
        if not self.selected_day:
            self.ids.info_label.text = "Сначала выбери день на календаре."
            return

        self.manual_shifts[self.selected_day] = self.ids.shift_spinner.text
        self.ids.info_label.text = (
            f"На {self.selected_day.strftime('%d.%m.%Y')} установлено: {self.ids.shift_spinner.text}"
        )
        self.save_state()
        self.refresh_calendar()

    def apply_range_shift(self, *_):
        try:
            start_dt = parse_date_ddmmyyyy(self.ids.start_input.text)
            end_dt = parse_date_ddmmyyyy(self.ids.end_input.text)
        except Exception:
            self.ids.info_label.text = "Неверный формат даты. Нужно дд.мм.гггг"
            return

        if start_dt > end_dt:
            self.ids.info_label.text = "Начальная дата не может быть позже конечной."
            return

        pattern = parse_pattern_text(self.ids.range_pattern_input.text)
        if not pattern:
            self.ids.info_label.text = "Укажи режим диапазона, например: День,Ночь,Ночь,День"
            return

        normalized_pattern = []
        for item in pattern:
            name = item.strip()
            if not name:
                continue
            normalized_pattern.append(name)

        if not normalized_pattern:
            self.ids.info_label.text = "Укажи режим диапазона, например: День,Ночь,Ночь,День"
            return

        allowed = set(self.base_pattern)
        for shift in normalized_pattern:
            if shift not in allowed:
                self.ids.info_label.text = f"Неизвестная смена: {shift}"
                return

        idx = 0
        for day in date_range(start_dt, end_dt):
            self.manual_shifts[day] = normalized_pattern[idx % len(normalized_pattern)]
            idx += 1

        self.start_month = MonthState(start_dt.year, start_dt.month)
        self.current_month = MonthState(start_dt.year, start_dt.month)
        self.months_count = months_between(start_dt, end_dt)
        self.selected_day = None

        self.ids.info_label.text = (
            f"Диапазон применён: {start_dt.strftime('%d.%m.%Y')} — {end_dt.strftime('%d.%m.%Y')}"
        )

        self.save_state()
        self.refresh_calendar()

    def apply_vacation_range(self, *_):
        try:
            start_dt = parse_date_ddmmyyyy(self.ids.start_input.text)
            end_dt = parse_date_ddmmyyyy(self.ids.end_input.text)
        except Exception:
            self.ids.info_label.text = "Неверный формат даты отпуска. Нужно дд.мм.гггг"
            return

        if start_dt > end_dt:
            self.ids.info_label.text = "Начальная дата отпуска не может быть позже конечной."
            return

        for day in date_range(start_dt, end_dt):
            self.manual_shifts[day] = "Отпуск"

        first_work_day = end_dt + timedelta(days=1)
        self.manual_shifts[first_work_day] = "День"

        self.start_month = MonthState(start_dt.year, start_dt.month)
        self.current_month = MonthState(start_dt.year, start_dt.month)
        self.months_count = months_between(start_dt, first_work_day)
        self.selected_day = None

        self.ids.info_label.text = (
            f"Отпуск отмечен: {start_dt.strftime('%d.%m.%Y')} - {end_dt.strftime('%d.%m.%Y')}. "
            f"{first_work_day.strftime('%d.%m.%Y')} поставлена смена День."
        )
        self.save_state()
        self.refresh_calendar()

    def save_day_note(self, *_):
        if not self.selected_day:
            self.ids.info_label.text = "Сначала выбери дату для отметки."
            return

        note = self.ids.day_note_input.text.strip()
        if not note:
            self.ids.info_label.text = "Напиши текст отметки."
            return

        self.day_notes[self.selected_day] = note
        self.ids.info_label.text = (
            f"Отметка сохранена на {self.selected_day.strftime('%d.%m.%Y')}: {note}"
        )
        self.save_state()
        self.refresh_calendar()

    def clear_day_note(self, *_):
        if not self.selected_day:
            self.ids.info_label.text = "Сначала выбери дату для удаления отметки."
            return

        if self.selected_day in self.day_notes:
            del self.day_notes[self.selected_day]
            self.ids.day_note_input.text = ""
            self.ids.info_label.text = f"Отметка на {self.selected_day.strftime('%d.%m.%Y')} удалена."
        else:
            self.ids.info_label.text = "Для выбранной даты отметки нет."

        self.save_state()
        self.refresh_calendar()

    def rebuild_range(self, *_):
        self.apply_range_shift()

    def on_day_press(self, button: ShiftDayButton):
        self.selected_day = button.day_date
        self.update_selected_widgets()

        self.ids.info_label.text = (
            f"День {self.selected_day.strftime('%d.%m.%Y')} выбран. "
            f"Текущая смена: {self.ids.shift_spinner.text}"
        )
        if self.selected_day in self.day_notes:
            self.ids.info_label.text += f". Отметка: {self.day_notes[self.selected_day]}"
        self.save_state()
        self.refresh_calendar()


class ShiftCalendarApp(App):
    def build(self):
        kv_candidates = []
        try:
            kv_candidates.append(Path(__file__).with_name("Interface.kv"))
        except Exception:
            pass

        try:
            found = resource_find("Interface.kv")
            if found:
                kv_candidates.append(Path(found))
        except Exception:
            pass

        loaded = False
        for kv_path in kv_candidates:
            try:
                if kv_path.exists():
                    Builder.load_file(str(kv_path))
                    loaded = True
                    break
            except Exception:
                continue

        if not loaded:
            print("Warning: Interface.kv was not found; building UI from Python only.")

        return CalendarAppRoot()


if __name__ == "__main__":
    ShiftCalendarApp().run()
