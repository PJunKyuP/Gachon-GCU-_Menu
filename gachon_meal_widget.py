import customtkinter as ctk
import calendar
import datetime as dt
import html
import re
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import ttk


CAFETERIAS = [
    {"name": "비전타워 식당", "url": "https://www.gachon.ac.kr/kor/7347/subview.do"},
    {"name": "교육대학원 식당", "url": "https://www.gachon.ac.kr/kor/7349/subview.do"},
    {"name": "학생생활관 식당", "url": "https://www.gachon.ac.kr/kor/7350/subview.do"},
    {
        "name": "체육관(메디컬) 식당",
        "url": "https://www.gachon.ac.kr/kor/7351/subview.do",
    },
]

CARD_COLORS = ["#F9E79F", "#F5CBA7", "#D5F5E3", "#D6EAF8"]
REFRESH_MINUTES = 30
DATE_RE = re.compile(r"\d{4}\.\d{2}\.\d{2}")
PERIOD_RE = re.compile(r"(\d{4}\.\d{2}\.\d{2})\s*~\s*(\d{4}\.\d{2}\.\d{2})")
WEEKDAY_KR = ("월", "화", "수", "목", "금", "토", "일")
MAX_WEEK_LOOKUP_STEPS = 12
SECTION_TITLES = {
    "lunch": "점심",
    "dinner": "저녁",
    "breakfast": "아침",
    "other": "기타",
}
LUNCH_HINTS = (
    "점심",
    "중식",
    "런치",
    "a메뉴",
    "b메뉴",
    "정식",
    "일품",
    "라면코너",
    "교직원식",
    "샐러드",
)
DINNER_HINTS = ("저녁", "석식", "디너")
BREAKFAST_HINTS = ("아침", "조식")
FONT_CANDIDATES = (
    "Pretendard",
    "SUIT",
    "Noto Sans KR",
    "나눔스퀘어",
    "나눔고딕",
    "맑은 고딕",
    "Segoe UI",
)
WINDOWS_APP_USER_MODEL_ID = "kr.gachon.menu"
APP_ICON_ICO_CANDIDATES = ("assets/images/black_logo.ico",)
APP_ICON_PNG_CANDIDATES = (
    "assets/images/black_logo.png",
    "black_logo.png",
)


def get_resource_path(file_name: str) -> str:
    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return str(base_dir / file_name)


def set_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return

    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            WINDOWS_APP_USER_MODEL_ID
        )
    except (AttributeError, OSError):
        return


def resolve_font_family(root: tk.Misc) -> str:
    available = {name.lower(): name for name in tkfont.families(root)}
    for candidate in FONT_CANDIDATES:
        match = available.get(candidate.lower())
        if match:
            return match
    return "Malgun Gothic"


@dataclass
class DayMenu:
    label: str
    meals: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class WeekNavForm:
    action: str
    layout: str
    monday: str


def fetch_html_with_curl(
    url: str,
    timeout_seconds: int = 25,
    method: str = "GET",
    form_data: dict[str, str] | None = None,
) -> str:
    cmd = [
        "curl",
        "-sL",
        "--connect-timeout",
        "10",
        "--max-time",
        str(timeout_seconds),
    ]

    method_upper = method.upper()
    if method_upper == "POST":
        encoded_data = urllib.parse.urlencode(form_data or {})
        cmd.extend(
            [
                "-X",
                "POST",
                "-H",
                "Content-Type: application/x-www-form-urlencoded",
                "--data",
                encoded_data,
            ]
        )
    elif method_upper != "GET":
        raise RuntimeError(f"지원하지 않는 요청 방식입니다: {method}")

    cmd.append(url)

    try:
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
            creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
            completed = subprocess.run(
                cmd,
                capture_output=True,
                check=False,
                startupinfo=startupinfo,
                creationflags=creationflags,
            )
        else:
            completed = subprocess.run(cmd, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "curl 명령을 찾지 못했습니다. Windows 기본 curl이 필요합니다."
        ) from exc

    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", "ignore").strip()
        raise RuntimeError(stderr or f"curl 실패 (code={completed.returncode})")

    if not completed.stdout:
        raise RuntimeError("빈 응답이 왔습니다.")

    return completed.stdout.decode("utf-8", "replace")


def clean_html_text(fragment: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def format_korean_date(date_value: dt.date) -> str:
    weekday = WEEKDAY_KR[date_value.weekday()]
    return f"{date_value.strftime('%Y.%m.%d')} ( {weekday} )"


def parse_menu_page(page_html: str) -> tuple[str, str, dict[str, DayMenu]]:
    title = ""
    title_match = re.search(
        r'<div[^>]*class="[^"]*_dietInfo[^"]*"[^>]*>.*?<dt>(.*?)</dt>',
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if title_match:
        title = clean_html_text(title_match.group(1))

    period = ""
    term_match = re.search(
        r'<div[^>]*class="[^"]*_dietTerm[^"]*"[^>]*>(.*?)</div>',
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if term_match:
        term_text = clean_html_text(term_match.group(1))
        period_match = re.search(
            r"\d{4}\.\d{2}\.\d{2}\s*~\s*\d{4}\.\d{2}\.\d{2}", term_text
        )
        if period_match:
            period = re.sub(r"\s+", " ", period_match.group(0)).strip()

    tbody_match = re.search(
        r"<tbody>(.*?)</tbody>", page_html, flags=re.IGNORECASE | re.DOTALL
    )
    days: dict[str, DayMenu] = {}
    if not tbody_match:
        return title, period, days

    current_date = ""
    current_label = ""
    rows = re.findall(
        r"<tr>(.*?)</tr>", tbody_match.group(1), flags=re.IGNORECASE | re.DOTALL
    )
    for row_html in rows:
        raw_cells = re.findall(
            r"<(th|td)\b[^>]*>(.*?)</\1>", row_html, flags=re.IGNORECASE | re.DOTALL
        )
        if not raw_cells:
            continue

        cells = [(tag.lower(), clean_html_text(content)) for tag, content in raw_cells]
        first_tag, first_text = cells[0]

        if first_tag == "th":
            date_match = DATE_RE.search(first_text)
            if date_match:
                current_date = date_match.group(0)
                current_label = first_text

        if not current_date:
            continue

        day_data = days.setdefault(
            current_date, DayMenu(label=current_label or current_date)
        )

        if first_tag == "th":
            if len(cells) < 3:
                continue
            meal_type, meal_text = cells[1][1], cells[2][1]
        else:
            if len(cells) < 2:
                continue
            meal_type, meal_text = cells[0][1], cells[1][1]

        day_data.meals.append((meal_type, meal_text))

    return title, period, days


def _parse_date_key(date_key: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(date_key, "%Y.%m.%d").date()
    except ValueError:
        return None


def _parse_period_range(period: str) -> tuple[dt.date, dt.date] | None:
    match = PERIOD_RE.search(period or "")
    if not match:
        return None

    start_date = _parse_date_key(match.group(1))
    end_date = _parse_date_key(match.group(2))
    if not start_date or not end_date:
        return None

    if start_date <= end_date:
        return start_date, end_date
    return end_date, start_date


def _parse_week_nav_form(page_html: str) -> WeekNavForm | None:
    form_tag_match = re.search(
        r'<form\b[^>]*id=["\']viewForm["\'][^>]*>', page_html, flags=re.IGNORECASE
    )
    if not form_tag_match:
        return None

    form_tag = form_tag_match.group(0)
    action_match = re.search(
        r'action=["\']([^"\']+)["\']', form_tag, flags=re.IGNORECASE
    )
    layout_match = re.search(
        r'<input[^>]*name=["\']layout["\'][^>]*value=["\']([^"\']*)["\']',
        page_html,
        flags=re.IGNORECASE,
    )
    monday_match = re.search(
        r'<input[^>]*name=["\']monday["\'][^>]*value=["\']([^"\']*)["\']',
        page_html,
        flags=re.IGNORECASE,
    )

    if not action_match or not layout_match or not monday_match:
        return None

    return WeekNavForm(
        action=html.unescape(action_match.group(1)).strip(),
        layout=html.unescape(layout_match.group(1)).strip(),
        monday=html.unescape(monday_match.group(1)).strip(),
    )


def _resolve_html_for_target_date(
    base_url: str,
    initial_html: str,
    target_date: dt.date,
    timeout_seconds: int = 25,
) -> str:
    html_text = initial_html
    seen_states: set[tuple[str, str, str]] = set()

    for _ in range(MAX_WEEK_LOOKUP_STEPS + 1):
        _title, period, days = parse_menu_page(html_text)
        period_range = _parse_period_range(period)

        if period_range:
            period_start, period_end = period_range
            if period_start <= target_date <= period_end:
                return html_text
            direction = "pre" if target_date < period_start else "next"
        else:
            parsed_dates = [
                parsed
                for parsed in (_parse_date_key(date_key) for date_key in days)
                if parsed
            ]
            if not parsed_dates:
                return html_text

            min_date = min(parsed_dates)
            max_date = max(parsed_dates)
            if min_date <= target_date <= max_date:
                return html_text

            direction = "pre" if target_date < min_date else "next"

        nav_form = _parse_week_nav_form(html_text)
        if not nav_form:
            return html_text

        state_key = (nav_form.action, nav_form.monday, direction)
        if state_key in seen_states:
            return html_text
        seen_states.add(state_key)

        target_url = urllib.parse.urljoin(base_url, nav_form.action)
        html_text = fetch_html_with_curl(
            target_url,
            timeout_seconds=timeout_seconds,
            method="POST",
            form_data={
                "layout": nav_form.layout,
                "monday": nav_form.monday,
                "week": direction,
            },
        )

    return html_text


def pick_day_menu(
    days: dict[str, DayMenu], target_date: dt.date | None = None
) -> DayMenu | None:
    key = pick_day_key(days, target_date=target_date)
    if not key:
        return None
    return days.get(key)


def pick_day_key(
    days: dict[str, DayMenu], target_date: dt.date | None = None
) -> str | None:
    if not days:
        return None

    date_to_find = target_date or dt.date.today()
    date_key = date_to_find.strftime("%Y.%m.%d")
    if date_key in days:
        return date_key

    for date_key in days:
        if _parse_date_key(date_key) == date_to_find:
            return date_key

    return None


def classify_meal_bucket(meal_type: str) -> str:
    normalized = meal_type.replace(" ", "").lower()

    if any(hint in normalized for hint in BREAKFAST_HINTS):
        return "breakfast"
    if any(hint in normalized for hint in DINNER_HINTS):
        return "dinner"

    strong_lunch_hints = ("점심", "중식", "런치")
    if any(hint in normalized for hint in strong_lunch_hints):
        return "lunch"

    weak_lunch_hints = tuple(
        hint for hint in LUNCH_HINTS if hint not in {"점심", "중식", "런치"}
    )
    if any(hint in normalized for hint in weak_lunch_hints):
        return "lunch"

    return "other"


def split_menu_lines(meal_text: str) -> list[str]:
    lines: list[str] = []
    for line in meal_text.splitlines():
        clean_line = re.sub(r"\s+", " ", line).strip()
        if clean_line and clean_line not in {"-", "--"}:
            lines.append(clean_line)
    return lines


def group_day_menu(
    day_menu: DayMenu | None,
) -> dict[str, list[tuple[str, list[str]]]]:
    grouped: dict[str, list[tuple[str, list[str]]]] = {
        "lunch": [],
        "dinner": [],
        "breakfast": [],
        "other": [],
    }
    if not day_menu:
        return grouped

    for meal_type, meal_text in day_menu.meals:
        bucket = classify_meal_bucket(meal_type)
        grouped[bucket].append((meal_type, split_menu_lines(meal_text)))

    return grouped


def bucket_has_real_items(entries: list[tuple[str, list[str]]]) -> bool:
    for _meal_type, lines in entries:
        for line in lines:
            if line.strip():
                return True
    return False


def format_meal_section(
    section_title: str,
    entries: list[tuple[str, list[str]]],
    compact: bool = False,
    max_lines: int = 9,
) -> list[str]:
    lines = [f"[{section_title}]"]

    if not entries:
        lines.append("- 등록된 메뉴 없음")
        lines.append("")
        return lines

    total_lines = 0
    truncated = False
    show_subtitle = len(entries) > 1

    for meal_type, menu_lines in entries:
        items = menu_lines or ["등록된 식단내용이 없습니다."]

        if show_subtitle:
            lines.append(f"• {meal_type}")

        for item in items:
            if compact and total_lines >= max_lines:
                truncated = True
                break
            prefix = "  - " if show_subtitle else "- "
            lines.append(f"{prefix}{item}")
            total_lines += 1

        if compact and truncated:
            break
        if show_subtitle:
            lines.append("")

    if truncated:
        lines.append("- ...더 있음")

    lines.append("")
    return lines


def format_grouped_menu(
    grouped: dict[str, list[tuple[str, list[str]]]],
    compact: bool = False,
) -> str:
    if compact:
        order = ("lunch", "dinner")
    else:
        order_list = ["lunch", "dinner"]
        if grouped.get("breakfast"):
            order_list.append("breakfast")
        if grouped.get("other"):
            order_list.append("other")
        order = tuple(order_list)

    lines: list[str] = []
    for section_key in order:
        lines.extend(
            format_meal_section(
                section_title=SECTION_TITLES[section_key],
                entries=grouped.get(section_key, []),
                compact=compact,
                max_lines=8 if compact else 999,
            )
        )

    return "\n".join(lines).strip()


def fetch_cafeteria_note(
    cafeteria: dict[str, str], target_date: dt.date | None = None
) -> dict[str, object]:
    selected_date = target_date or dt.date.today()

    html_text = fetch_html_with_curl(cafeteria["url"])
    html_text = _resolve_html_for_target_date(
        cafeteria["url"], html_text, selected_date
    )

    parsed_title, period, days = parse_menu_page(html_text)
    target_key = pick_day_key(days, target_date=selected_date)
    target_day = days.get(target_key) if target_key else None

    grouped_by_date: dict[str, dict[str, list[tuple[str, list[str]]]]] = {}
    for date_key, day_menu in days.items():
        grouped_by_date[date_key] = group_day_menu(day_menu)

    lunch_available_any_day = any(
        bucket_has_real_items(grouped.get("lunch", []))
        for grouped in grouped_by_date.values()
    )
    dinner_available_any_day = any(
        bucket_has_real_items(grouped.get("dinner", []))
        for grouped in grouped_by_date.values()
    )

    grouped = grouped_by_date.get(target_key or "", group_day_menu(target_day))
    grouped = {bucket: list(entries) for bucket, entries in grouped.items()}
    date_label = (
        target_day.label
        if target_day
        else f"{format_korean_date(selected_date)}\n선택한 날짜 식단 정보 없음"
    )

    full_text = format_grouped_menu(grouped, compact=False)
    compact_text = format_grouped_menu(grouped, compact=True)

    return {
        "title": cafeteria["name"],
        "date_label": date_label,
        "period": period or "확인 불가",
        "full_text": full_text,
        "compact_text": compact_text,
        "grouped": grouped,
        "lunch_available_any_day": lunch_available_any_day,
        "dinner_available_any_day": dinner_available_any_day,
        "source_title": parsed_title or cafeteria["name"],
        "url": cafeteria["url"],
        "selected_date": selected_date.strftime("%Y.%m.%d"),
    }


class DatePickerDialog:
    def __init__(self, parent, initial_date: dt.date, font_family: str) -> None:
        self.parent = parent
        self.initial_date = initial_date
        self.font_family = font_family
        self.today = dt.date.today()
        self.selected_date = None
        self.view_year = initial_date.year
        self.view_month = initial_date.month
        self.month_var = tk.StringVar()

        self.window = ctk.CTkToplevel(parent)
        self.window.title("날짜 선택")
        self.window.geometry("340x380")
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self.window.bind("<Escape>", lambda _e: self._cancel())

        top_row = ctk.CTkFrame(self.window, fg_color="transparent")
        top_row.pack(fill="x", padx=15, pady=(20, 10))

        prev_btn = ctk.CTkButton(
            top_row,
            text="<",
            command=lambda: self._move_month(-1),
            width=40,
            height=35,
            corner_radius=8,
            font=(self.font_family, 14, "bold"),
        )
        prev_btn.pack(side="left")

        month_label = ctk.CTkLabel(
            top_row, textvariable=self.month_var, font=(self.font_family, 16, "bold")
        )
        month_label.pack(side="left", expand=True)

        next_btn = ctk.CTkButton(
            top_row,
            text=">",
            command=lambda: self._move_month(1),
            width=40,
            height=35,
            corner_radius=8,
            font=(self.font_family, 14, "bold"),
        )
        next_btn.pack(side="right")

        self.grid_wrap = ctk.CTkFrame(self.window, fg_color="transparent")
        self.grid_wrap.pack(fill="both", padx=15, pady=5)

        bottom_row = ctk.CTkFrame(self.window, fg_color="transparent")
        bottom_row.pack(fill="x", padx=15, pady=(10, 20))

        today_btn = ctk.CTkButton(
            bottom_row,
            text="오늘 선택",
            command=lambda: self._select(self.today),
            width=100,
            corner_radius=8,
            font=(self.font_family, 13, "bold"),
            fg_color="#27AE60",
            hover_color="#229954",
        )
        today_btn.pack(side="left")

        cancel_btn = ctk.CTkButton(
            bottom_row,
            text="취소",
            command=self._cancel,
            width=70,
            corner_radius=8,
            font=(self.font_family, 13),
            fg_color="#7F8C8D",
            hover_color="#616A6B",
        )
        cancel_btn.pack(side="right")

        self._render_calendar()

    def _move_month(self, offset: int) -> None:
        month_index = self.view_year * 12 + (self.view_month - 1) + offset
        self.view_year, month_zero_based = divmod(month_index, 12)
        self.view_month = month_zero_based + 1
        self._render_calendar()

    def _render_calendar(self) -> None:
        for child in self.grid_wrap.winfo_children():
            child.destroy()
        self.month_var.set(f"{self.view_year}년 {self.view_month:02d}월")
        WEEKDAY_KR = ("월", "화", "수", "목", "금", "토", "일")
        weekday_text_color = ("#000000", "#000000")
        saturday_text_color = ("#1E6FD1", "#1E6FD1")
        sunday_text_color = ("#D93025", "#D93025")
        for col, weekday in enumerate(WEEKDAY_KR):
            tc = (
                sunday_text_color
                if col == 6
                else (saturday_text_color if col == 5 else weekday_text_color)
            )
            lbl = ctk.CTkLabel(
                self.grid_wrap,
                text=weekday,
                font=(self.font_family, 13, "bold"),
                text_color=tc,
                width=42,
            )
            lbl.grid(row=0, column=col, padx=1, pady=(0, 10))

        first_wd, days = calendar.monthrange(self.view_year, self.view_month)
        for day in range(1, days + 1):
            d_val = dt.date(self.view_year, self.view_month, day)
            idx = first_wd + (day - 1)
            row = 1 + (idx // 7)
            col = idx % 7

            btn_color = (
                ("#3B8ED0", "#1F6AA5")
                if d_val == self.initial_date
                else (
                    ("#27AE60", "#229954")
                    if d_val == self.today
                    else ("#F7F7F7", "#F7F7F7")
                )
            )
            tx_color = (
                ("#FFFFFF", "#FFFFFF")
                if (d_val == self.initial_date or d_val == self.today)
                else (
                    sunday_text_color
                    if col == 6
                    else (saturday_text_color if col == 5 else weekday_text_color)
                )
            )
            hv_color = (
                "#1F6AA5"
                if d_val == self.initial_date
                else ("#229954" if d_val == self.today else "#E3E3E3")
            )

            b = ctk.CTkButton(
                self.grid_wrap,
                text=str(day),
                command=lambda d=d_val: self._select(d),
                font=(
                    self.font_family,
                    13,
                    "bold" if d_val == self.initial_date else "normal",
                ),
                width=42,
                height=38,
                corner_radius=8,
                fg_color=btn_color,
                text_color=tx_color,
                text_color_disabled=tx_color,
                hover_color=hv_color,
                border_width=1
                if (d_val != self.initial_date and d_val != self.today)
                else 0,
                border_color=("#D5D5D5", "#D5D5D5"),
                state="normal",
            )
            if d_val != self.initial_date and d_val != self.today:
                b.configure(font=(self.font_family, 13, "bold"))
            b.grid(row=row, column=col, padx=1, pady=1)

    def _select(self, picked: dt.date) -> None:
        self.selected_date = picked
        if self.window.winfo_exists():
            self.window.destroy()

    def _cancel(self) -> None:
        self.selected_date = None
        if self.window.winfo_exists():
            self.window.destroy()

    def show(self) -> dt.date | None:
        self.window.update_idletasks()
        pw = self.parent.winfo_width()
        ph = self.parent.winfo_height()
        px = self.parent.winfo_rootx()
        py = self.parent.winfo_rooty()
        w = self.window.winfo_width()
        h = self.window.winfo_height()
        self.window.geometry(
            f"+{px + max((pw - w) // 2, 0)}+{py + max((ph - h) // 2, 0)}"
        )
        self.window.grab_set()
        self.window.focus_set()
        self.window.wait_window()
        return self.selected_date


class MealWidgetApp:
    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        self.root.title("가천대학교 학식 메뉴")
        self.root.geometry("1400x900")
        self.root.minsize(1050, 700)
        self.font_family = resolve_font_family(self.root)
        self.icon_image = None
        self._apply_app_icon()

        self.is_topmost = False
        self.was_topmost_before_pip = self.is_topmost
        self.is_pip_mode = False
        self.normal_geometry = "1400x900"
        self.saved_geometry = ""
        self.is_refreshing = False
        self.pending_refresh = False
        self.root.attributes("-topmost", self.is_topmost)

        self.selected_date = dt.date.today()
        self.selected_date_var = tk.StringVar(
            value=format_korean_date(self.selected_date)
        )
        self.last_update_var = tk.StringVar(value="업데이트 대기 중")
        self.status_var = tk.StringVar(value="")

        self.cafe_visibility_vars = [tk.BooleanVar(value=True) for _ in CAFETERIAS]
        self.cards = []
        self.latest_notes = []
        self.pip_windows = []

        self._build_header()
        self._build_cards()

        self.root.bind("<F5>", lambda e: self.refresh_data())
        self.refresh_data()
        self._schedule_periodic_refresh()

    def _font(self, size: int, weight: str = "normal") -> tuple[str, int, str]:
        return (self.font_family, size, weight)

    def _apply_app_icon(self) -> None:
        icon_ico = ""
        for candidate in APP_ICON_ICO_CANDIDATES:
            candidate_path = Path(get_resource_path(candidate))
            if candidate_path.exists():
                icon_ico = str(candidate_path)
                break
        if icon_ico:
            try:
                self.root.iconbitmap(icon_ico)
            except tk.TclError:
                pass

        icon_png = ""
        for candidate in APP_ICON_PNG_CANDIDATES:
            candidate_path = Path(get_resource_path(candidate))
            if candidate_path.exists():
                icon_png = str(candidate_path)
                break
        if not icon_png:
            return
        try:
            from PIL import Image, ImageTk

            self.icon_image = ImageTk.PhotoImage(Image.open(icon_png))
            self.root.iconphoto(True, self.icon_image)
        except Exception:
            pass

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self.root, fg_color="transparent")
        header.pack(fill="x", padx=30, pady=(25, 10))

        top_row = ctk.CTkFrame(header, fg_color="transparent")
        top_row.pack(fill="x")

        title = ctk.CTkLabel(
            top_row,
            text="가천대학교 학식 메뉴",
            font=self._font(28, "bold"),
            text_color=["#1C2833", "#FDFEFE"],
        )
        title.pack(side="left")

        status = ctk.CTkLabel(
            top_row,
            textvariable=self.status_var,
            font=self._font(13),
            text_color=["#7F8C8D", "#BDC3C7"],
        )
        status.pack(side="left", padx=(15, 0))

        right_wrap = ctk.CTkFrame(top_row, fg_color="transparent")
        right_wrap.pack(side="right")

        updated = ctk.CTkLabel(
            right_wrap,
            textvariable=self.last_update_var,
            font=self._font(13),
            text_color=["#7F8C8D", "#BDC3C7"],
        )
        updated.pack(side="left", padx=(0, 15))

        src_btn = ctk.CTkButton(
            right_wrap,
            text="원본 보기",
            command=self.open_source_pages,
            font=self._font(13, "bold"),
            corner_radius=12,
            width=80,
            fg_color="#F1C40F",
            text_color="#1C2833",
            hover_color="#D4AC0D",
        )
        src_btn.pack(side="left", padx=5)

        ref_btn = ctk.CTkButton(
            right_wrap,
            text="새로고침",
            command=self.refresh_data,
            font=self._font(13, "bold"),
            corner_radius=12,
            width=80,
        )
        ref_btn.pack(side="left", padx=5)

        self.topmost_btn = ctk.CTkButton(
            right_wrap,
            text="항상 위: OFF",
            command=self.toggle_topmost,
            font=self._font(13),
            corner_radius=12,
            width=100,
            fg_color="#EAECEE",
            text_color="#1C2833",
            hover_color="#D5DBDB",
        )
        self.topmost_btn.pack(side="left", padx=5)
        self._sync_topmost_button_style()

        self.pip_btn = ctk.CTkButton(
            right_wrap,
            text="PIP 모드: OFF",
            command=self.toggle_pip_mode,
            font=self._font(13),
            corner_radius=12,
            width=100,
            fg_color="#34495E",
            hover_color="#2C3E50",
        )
        self.pip_btn.pack(side="left", padx=5)

        date_row = ctk.CTkFrame(header, fg_color="transparent")
        date_row.pack(fill="x", pady=(15, 0))

        date_title = ctk.CTkLabel(
            date_row, text="조회 날짜:", font=self._font(15, "bold")
        )
        date_title.pack(side="left", padx=(0, 10))

        prev_d = ctk.CTkButton(
            date_row,
            text="<",
            command=lambda: self._shift_selected_date(-1),
            font=self._font(14, "bold"),
            corner_radius=10,
            width=40,
            fg_color=["#E5E7E9", "#424949"],
            text_color=["#2C3E50", "#ECF0F1"],
            hover_color=["#D5D8DC", "#212F3C"],
        )
        prev_d.pack(side="left", padx=(0, 5))

        dl_btn = ctk.CTkButton(
            date_row,
            textvariable=self.selected_date_var,
            command=self._open_date_picker,
            font=self._font(14, "bold"),
            corner_radius=10,
            width=150,
            fg_color=["#D4E6F1", "#1A5276"],
            text_color=["#154360", "#EAF2F8"],
            hover_color=["#A9CCE3", "#154360"],
        )
        dl_btn.pack(side="left", padx=5)

        next_d = ctk.CTkButton(
            date_row,
            text=">",
            command=lambda: self._shift_selected_date(1),
            font=self._font(14, "bold"),
            corner_radius=10,
            width=40,
            fg_color=["#E5E7E9", "#424949"],
            text_color=["#2C3E50", "#ECF0F1"],
            hover_color=["#D5D8DC", "#212F3C"],
        )
        next_d.pack(side="left", padx=(5, 15))

        today_btn = ctk.CTkButton(
            date_row,
            text="오늘",
            command=self._reset_selected_date,
            font=self._font(13, "bold"),
            corner_radius=10,
            width=60,
            fg_color="#2ECC71",
            hover_color="#27AE60",
        )
        today_btn.pack(side="left")

        hint = ctk.CTkLabel(
            date_row,
            text="모든 식당을 같은 날짜로 조회합니다.",
            font=self._font(12),
            text_color=["#7F8C8D", "#95A5A6"],
        )
        hint.pack(side="left", padx=(15, 0))

        filter_row = ctk.CTkFrame(header, fg_color="transparent")
        filter_row.pack(fill="x", pady=(15, 0))
        filter_title = ctk.CTkLabel(
            filter_row, text="표시 식당:", font=self._font(15, "bold")
        )
        filter_title.pack(side="left", padx=(0, 10))

        for idx, cafeteria in enumerate(CAFETERIAS):
            chk = ctk.CTkCheckBox(
                filter_row,
                text=cafeteria["name"],
                variable=self.cafe_visibility_vars[idx],
                command=self._on_toggle_cafeteria,
                font=self._font(13),
                corner_radius=6,
                border_width=2,
            )
            chk.pack(side="left", padx=8)

    def _set_selected_date(self, new_date: dt.date, force_refresh: bool = True) -> None:
        if new_date == self.selected_date and not force_refresh:
            return
        self.selected_date = new_date
        self.selected_date_var.set(format_korean_date(new_date))
        if force_refresh:
            self.refresh_data()

    def _shift_selected_date(self, offset_days: int) -> None:
        if offset_days == 0:
            return
        self._set_selected_date(self.selected_date + dt.timedelta(days=offset_days))

    def _open_date_picker(self) -> None:
        picker = DatePickerDialog(self.root, self.selected_date, self.font_family)
        picked = picker.show()
        if picked:
            self._set_selected_date(picked)

    def _reset_selected_date(self) -> None:
        self._set_selected_date(dt.date.today())

    def _build_cards(self) -> None:
        self.cards_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self.cards_frame.pack(fill="both", expand=True, padx=25, pady=(10, 25))

        CARD_BG_COLORS = [
            ["#FDF2E9", "#6E2C00"],
            ["#E8F8F5", "#0E6251"],
            ["#EBF5FB", "#154360"],
            ["#F4ECF7", "#512E5F"],
        ]

        for idx, cafeteria in enumerate(CAFETERIAS):
            c_color = CARD_BG_COLORS[idx % len(CARD_BG_COLORS)]
            card = ctk.CTkFrame(self.cards_frame, corner_radius=20, fg_color=c_color)

            top_bar = ctk.CTkFrame(
                card, corner_radius=10, fg_color=["#FAD7A1", "#935116"], height=10
            )
            top_bar.pack(fill="x", padx=100, pady=(15, 5))

            t_c = ["#17202A", "#FDFEFE"]
            s_c = ["#566573", "#B3B6B7"]

            title_var = tk.StringVar(value=cafeteria["name"])
            sub_var = tk.StringVar(value="데이터 불러오는 중...")

            title_lbl = ctk.CTkLabel(
                card,
                textvariable=title_var,
                font=self._font(20, "bold"),
                text_color=t_c,
            )
            title_lbl.pack(fill="x", padx=20, anchor="w")

            sub_lbl = ctk.CTkLabel(
                card,
                textvariable=sub_var,
                font=self._font(13),
                text_color=s_c,
                justify="left",
            )
            # Removed sub_lbl packing according to user request

            # Content Wrap inside card
            wrap = ctk.CTkFrame(card, corner_radius=12, fg_color=["#FFFFFF", "#2C3E50"])
            wrap.pack(fill="both", expand=True, padx=15, pady=(0, 15))

            header_f = ctk.CTkFrame(
                wrap, corner_radius=12, fg_color=["#F2F4F4", "#212F3C"], height=38
            )
            header_f.pack(fill="x", padx=5, pady=5)
            header_f.pack_propagate(False)

            l_lbl = ctk.CTkLabel(
                header_f, text="점심", font=self._font(15, "bold"), text_color=t_c
            )
            l_lbl.pack(side="left", fill="x", expand=True)

            d_lbl = ctk.CTkLabel(
                header_f, text="저녁", font=self._font(15, "bold"), text_color=t_c
            )
            d_lbl.pack(side="left", fill="x", expand=True)

            body_f = ctk.CTkFrame(wrap, fg_color="transparent")
            body_f.pack(fill="both", expand=True, padx=10, pady=(5, 10))

            l_txt = ctk.CTkTextbox(
                body_f,
                font=self._font(14),
                corner_radius=10,
                fg_color="transparent",
                text_color=t_c,
                wrap="word",
                border_spacing=5,
            )
            l_txt.pack(side="left", fill="both", expand=True, padx=(0, 5))
            d_txt = ctk.CTkTextbox(
                body_f,
                font=self._font(14),
                corner_radius=10,
                fg_color="transparent",
                text_color=t_c,
                wrap="word",
                border_spacing=5,
            )
            d_txt.pack(side="left", fill="both", expand=True, padx=(5, 0))

            e_var = tk.StringVar(value="")
            e_lbl = ctk.CTkLabel(
                card,
                textvariable=e_var,
                font=self._font(12),
                text_color=s_c,
                justify="left",
            )
            e_lbl.pack(fill="x", padx=20, pady=(0, 10), anchor="w")

            self._set_text(l_txt, "불러오는 중입니다...")
            self._set_text(d_txt, "불러오는 중입니다...")

            self.cards.append(
                {
                    "title_var": title_var,
                    "subtitle_var": sub_var,
                    "title_label": title_lbl,
                    "subtitle_label": sub_lbl,
                    "lunch_head_label": l_lbl,
                    "dinner_head_label": d_lbl,
                    "card_frame": card,
                    "lunch_text_widget": l_txt,
                    "dinner_text_widget": d_txt,
                    "extra_var": e_var,
                    "extra_label": e_lbl,
                    "default_title": cafeteria["name"],
                }
            )

        self.empty_lbl = ctk.CTkLabel(
            self.cards_frame,
            text="표시할 식당을 선택해 주세요.",
            font=self._font(18, "bold"),
            text_color=["#7F8C8D", "#BDC3C7"],
        )
        self._relayout_cards()

    def _on_toggle_cafeteria(self) -> None:
        self._relayout_cards()
        if self.is_pip_mode:
            self._sync_pip_windows()

    def _relayout_cards(self) -> None:
        if not self.cards_frame:
            return
        visible = [
            c["card_frame"]
            for i, c in enumerate(self.cards)
            if (
                self.cafe_visibility_vars[i].get()
                if i < len(self.cafe_visibility_vars)
                else True
            )
        ]

        for c in self.cards:
            c["card_frame"].grid_forget()
        self.empty_lbl.grid_forget()

        for r in range(3):
            self.cards_frame.grid_rowconfigure(r, weight=0)
        for c in range(2):
            self.cards_frame.grid_columnconfigure(c, weight=0)

        count = len(visible)
        if count == 0:
            self.cards_frame.grid_rowconfigure(0, weight=1)
            self.cards_frame.grid_columnconfigure(0, weight=1)
            self.empty_lbl.grid(row=0, column=0, sticky="nsew")
            return

        cols = 1 if count == 1 else 2
        rows = (count + cols - 1) // cols
        for r in range(rows):
            self.cards_frame.grid_rowconfigure(r, weight=1)
        for c in range(cols):
            self.cards_frame.grid_columnconfigure(c, weight=1)

        for i, f in enumerate(visible):
            r, c = (i, 0) if cols == 1 else divmod(i, 2)
            cs = 2 if (cols == 2 and count % 2 == 1 and i == count - 1) else 1
            f.grid(row=r, column=c, columnspan=cs, sticky="nsew", padx=12, pady=12)

    def _set_text(self, txt: ctk.CTkTextbox, text: str) -> None:
        txt.configure(state="normal")
        txt.delete("1.0", "end")
        txt.insert("1.0", text)
        txt.tag_config("center", justify="center")
        txt.tag_add("center", "1.0", "end")
        txt.tag_config("category", foreground="#E67E22")
        for i, line in enumerate(text.split("\n")):
            if line.strip().startswith("[") and line.strip().endswith("]"):
                txt.tag_add("category", f"{i + 1}.0", f"{i + 1}.end")
        txt.configure(state="disabled")

    def _sync_topmost_button_style(self) -> None:
        if self.is_topmost:
            self.topmost_btn.configure(
                text="항상 위: ON",
                fg_color="#E74C3C",
                text_color="#FFFFFF",
                hover_color="#C0392B",
            )
        else:
            self.topmost_btn.configure(
                text="항상 위: OFF",
                fg_color="#EAECEE",
                text_color="#1C2833",
                hover_color="#D5DBDB",
            )

    def open_source_pages(self) -> None:
        urls = [
            CAFETERIAS[i]["url"]
            for i, v in enumerate(self.cafe_visibility_vars)
            if v.get() and i < len(CAFETERIAS)
        ]
        for u in urls:
            webbrowser.open(u)
        self.status_var.set(
            f"원본 페이지 {len(urls)}개를 열었습니다."
            if urls
            else "표시 중인 식당이 없어 원본 페이지를 열지 않았습니다."
        )

    def _sync_pip_windows(self) -> None:
        if self.is_pip_mode:
            self._open_pip_windows()
            self._render_pip_windows(self.latest_notes)

    def _close_pip_windows(self) -> None:
        for w in self.pip_windows:
            win = w.get("window")
            if win and win.winfo_exists():
                win.destroy()
        self.pip_windows.clear()

    def _on_close_pip_window(self, idx: int) -> None:
        remaining = []
        for w in self.pip_windows:
            win = w.get("window")
            w_idx = w.get("index")
            if w_idx == idx:
                if win and win.winfo_exists():
                    win.destroy()
                continue
            remaining.append(w)
        self.pip_windows = remaining

    def _open_pip_windows(self) -> None:
        visible = [
            i
            for i, v in enumerate(self.cafe_visibility_vars)
            if v.get() and i < len(CAFETERIAS)
        ]

        alive = []
        for w in self.pip_windows:
            win = w.get("window")
            idx = w.get("index")
            if idx not in visible:
                if win and win.winfo_exists():
                    win.destroy()
            else:
                alive.append(w)
        self.pip_windows = alive

        open_indices = {w.get("index") for w in self.pip_windows}

        self.root.update_idletasks()
        bx, by = self.root.winfo_rootx() + 30, self.root.winfo_rooty() + 100
        ww, wh = 380, 480
        CARD_BG_COLORS = [
            ["#FDF2E9", "#6E2C00"],
            ["#E8F8F5", "#0E6251"],
            ["#EBF5FB", "#154360"],
            ["#F4ECF7", "#512E5F"],
        ]

        for order, idx in enumerate(visible):
            if idx in open_indices:
                continue

            caf = CAFETERIAS[idx]
            r, c = divmod(order, 2)
            x, y = bx + c * (ww + 20), by + r * (wh + 20)

            c_color = CARD_BG_COLORS[idx % len(CARD_BG_COLORS)]
            win = ctk.CTkToplevel(self.root)
            win.title(f"PIP - {caf['name']}")
            win.geometry(f"{ww}x{wh}+{x}+{y}")
            win.minsize(300, 350)
            win.attributes("-topmost", True)
            win.attributes("-alpha", 0.95)
            win.protocol("WM_DELETE_WINDOW", lambda i=idx: self._on_close_pip_window(i))

            main_f = ctk.CTkFrame(win, corner_radius=15, fg_color=c_color)
            main_f.pack(fill="both", expand=True, padx=10, pady=10)

            t_v = tk.StringVar(value=caf["name"])
            s_v = tk.StringVar(value="")

            t_lbl = ctk.CTkLabel(
                main_f,
                textvariable=t_v,
                font=self._font(16, "bold"),
                text_color=["#17202A", "#FDFEFE"],
            )
            t_lbl.pack(fill="x", padx=15, pady=(15, 0), anchor="w")

            s_lbl = ctk.CTkLabel(
                main_f,
                textvariable=s_v,
                font=self._font(12),
                text_color=["#566573", "#B3B6B7"],
            )
            # Removed subtitle packing in PIP mode

            b_f = ctk.CTkFrame(
                main_f, corner_radius=10, fg_color=["#FFFFFF", "#2C3E50"]
            )
            b_f.pack(fill="both", expand=True, padx=12, pady=(0, 15))

            b_txt = ctk.CTkTextbox(
                b_f,
                font=self._font(13),
                corner_radius=10,
                fg_color="transparent",
                text_color=["#17202A", "#FDFEFE"],
                wrap="word",
            )
            b_txt.pack(fill="both", expand=True, padx=8, pady=8)

            self.pip_windows.append(
                {
                    "index": idx,
                    "window": win,
                    "title_var": t_v,
                    "subtitle_var": s_v,
                    "body_text": b_txt,
                }
            )

    def toggle_topmost(self) -> None:
        if self.is_pip_mode:
            return
        self.is_topmost = not self.is_topmost
        self.root.attributes("-topmost", self.is_topmost)
        self._sync_topmost_button_style()

    def toggle_pip_mode(self) -> None:
        self.is_pip_mode = not self.is_pip_mode
        self._apply_mode_styles()
        if self.latest_notes:
            self._render_notes(self.latest_notes)
        if self.is_pip_mode:
            self._sync_pip_windows()
        else:
            self._close_pip_windows()

    def _apply_mode_styles(self) -> None:
        if self.is_pip_mode:
            self.saved_geometry = self.root.geometry()
            self.was_topmost_before_pip = self.is_topmost
            self.root.minsize(700, 500)
            self.root.geometry("1000x650")
            self.root.attributes("-alpha", 0.96)
            self.is_topmost = False
            self.root.attributes("-topmost", False)
            self.topmost_btn.configure(state="disabled")
            self._sync_topmost_button_style()
            self.pip_btn.configure(text="PIP 모드: ON", fg_color="#F39C12")
        else:
            self.root.attributes("-alpha", 1.0)
            self.root.minsize(1050, 700)
            self.root.geometry(self.saved_geometry or self.normal_geometry)
            self.is_topmost = self.was_topmost_before_pip
            self.root.attributes("-topmost", self.is_topmost)
            self.topmost_btn.configure(state="normal")
            self._sync_topmost_button_style()
            self.pip_btn.configure(text="PIP 모드: OFF", fg_color="#34495E")

        font_shift = -3 if self.is_pip_mode else 0
        for c in self.cards:
            if "title_label" in c:
                c["title_label"].configure(font=self._font(20 + font_shift, "bold"))
            if "subtitle_label" in c:
                c["subtitle_label"].configure(font=self._font(13 + font_shift))
            if "lunch_head_label" in c:
                c["lunch_head_label"].configure(
                    font=self._font(15 + font_shift, "bold")
                )
            if "dinner_head_label" in c:
                c["dinner_head_label"].configure(
                    font=self._font(15 + font_shift, "bold")
                )
            if "lunch_text_widget" in c:
                c["lunch_text_widget"].configure(font=self._font(14 + font_shift))
            if "dinner_text_widget" in c:
                c["dinner_text_widget"].configure(font=self._font(14 + font_shift))
            if "extra_label" in c:
                c["extra_label"].configure(font=self._font(12 + font_shift))

    def _build_subtitle(self, note: dict) -> str:
        if note.get("error"):
            return "식단 로딩 실패"
        dl = str(note.get("date_label", ""))
        p = str(note.get("period", "확인 불가"))
        return dl if self.is_pip_mode else f"{dl}\n주간: {p}"

    def _get_bucket_entries(self, note: dict, bucket: str) -> list:
        grouped = note.get("grouped")
        if not isinstance(grouped, dict):
            return []
        raw = grouped.get(bucket, [])
        if not isinstance(raw, list):
            return []
        entries = []
        for r in raw:
            if not isinstance(r, (tuple, list)) or len(r) != 2:
                continue
            mt = str(r[0]).strip()
            rl = r[1]
            lines = (
                [str(i).strip() for i in rl if str(i).strip()]
                if isinstance(rl, list)
                else ([str(rl).strip()] if str(rl).strip() else [])
            )
            entries.append((mt, lines))
        return entries

    def _format_bucket_entries(self, entries: list, max_lines: int) -> str:
        if not entries:
            return "등록된 메뉴가 없습니다."
        lines, used, show = [], 0, len(entries) > 1
        for mt, m_items in entries:
            items = m_items or ["등록된 메뉴가 없습니다."]
            if show:
                lines.append(f"[{mt}]")
            for i in items:
                if used >= max_lines:
                    lines.append("...더 있음")
                    return "\n".join(lines).strip()
                lines.append(i)
                used += 1
            if show:
                lines.append("")
        return "\n".join(lines).strip()

    def _build_section_text(self, note: dict, bucket: str) -> str:
        err = note.get("error")
        if isinstance(err, str) and err:
            return f"오류: {err}" if bucket == "lunch" else "확인 불가"
        entries = self._get_bucket_entries(note, bucket)
        if not bucket_has_real_items(entries):
            if bucket == "dinner" and note.get("dinner_available_any_day") is False:
                return "등록된 메뉴가 없습니다."
            if bucket == "lunch" and note.get("lunch_available_any_day") is False:
                return "등록된 메뉴가 없습니다."
        max_lz = 11 if self.is_pip_mode else 30
        return self._format_bucket_entries(entries, max_lz)

    def _build_extra_info(self, note: dict) -> str:
        if note.get("error"):
            return ""
        bc = len(self._get_bucket_entries(note, "breakfast"))
        oc = len(self._get_bucket_entries(note, "other"))
        p = []
        if bc:
            p.append(f"아침 {bc}개")
        if oc:
            p.append(f"기타 {oc}개")
        if not p:
            return ""
        return f"{'추가 메뉴' if self.is_pip_mode else '추가 메뉴:'} {', '.join(p)}"

    def _build_pip_note_text(self, note: dict) -> str:
        lt = self._build_section_text(note, "lunch")
        dt_ = self._build_section_text(note, "dinner")
        pt = [f"[점심]\n{lt}", f"[저녁]\n{dt_}"]
        et = self._build_extra_info(note)
        if et:
            pt.append(f"[추가]\n{et}")
        return "\n\n".join(pt).strip()

    def _render_pip_windows(self, notes: list) -> None:
        if not self.is_pip_mode:
            return
        alive = []
        for w in self.pip_windows:
            win = w.get("window")
            if not win or not win.winfo_exists():
                continue
            idx = w.get("index")
            if not isinstance(idx, int):
                continue
            note = notes[idx] if idx < len(notes) else {}
            dt_ = CAFETERIAS[idx]["name"] if idx < len(CAFETERIAS) else "식당"
            tv, sv, bt = w.get("title_var"), w.get("subtitle_var"), w.get("body_text")
            if tv:
                tv.set(str(note.get("title", dt_)))
            if sv:
                sv.set(self._build_subtitle(note))
            if bt:
                self._set_text(bt, self._build_pip_note_text(note))
            alive.append(w)
        self.pip_windows = alive

    def _render_notes(self, notes: list) -> None:
        for i, c in enumerate(self.cards):
            note = notes[i] if i < len(notes) else {}
            tv, sv, ev, dt_ = (
                c.get("title_var"),
                c.get("subtitle_var"),
                c.get("extra_var"),
                str(c.get("default_title", "")),
            )
            lt, rt = c.get("lunch_text_widget"), c.get("dinner_text_widget")
            if tv:
                tv.set(str(note.get("title", dt_)))
            if sv:
                sv.set(self._build_subtitle(note))
            if lt:
                self._set_text(lt, self._build_section_text(note, "lunch"))
            if rt:
                self._set_text(rt, self._build_section_text(note, "dinner"))
            if ev:
                ev.set(self._build_extra_info(note))
        if self.is_pip_mode:
            self._render_pip_windows(notes)

    def refresh_data(self) -> None:
        if self.is_refreshing:
            self.pending_refresh = True
            return
        td = self.selected_date
        self.is_refreshing = True
        self.pending_refresh = False
        self.status_var.set(f"업데이트 중... ({format_korean_date(td)})")
        threading.Thread(target=self._refresh_worker, args=(td,), daemon=True).start()

    def _refresh_worker(self, td: dt.date) -> None:
        notes, errs = [], 0
        for c in CAFETERIAS:
            try:
                notes.append(fetch_cafeteria_note(c, target_date=td))
            except Exception as e:
                errs += 1
                notes.append(
                    {
                        "title": c["name"],
                        "date_label": f"{format_korean_date(td)}\n식단 로딩 실패",
                        "period": "-",
                        "full_text": "",
                        "compact_text": "",
                        "source_title": c["name"],
                        "url": c["url"],
                        "error": str(e),
                        "selected_date": td.strftime("%Y.%m.%d"),
                    }
                )
        self.root.after(0, lambda: self._apply_notes(notes, errs, td))

    def _apply_notes(self, notes: list, errs: int, td: dt.date) -> None:
        if td != self.selected_date:
            self.is_refreshing = False
            self.pending_refresh = False
            self.refresh_data()
            return
        self.latest_notes = notes
        self._render_notes(notes)
        self.last_update_var.set(
            dt.datetime.now().strftime("최근 업데이트: %Y-%m-%d %H:%M")
        )
        ss = f" ({format_korean_date(td)})"
        bs = "완료 / PIP" if self.is_pip_mode else "완료"
        self.status_var.set(f"완료 (일부 실패: {errs}개){ss}" if errs else f"{bs}{ss}")
        self.is_refreshing = False
        if self.pending_refresh:
            self.pending_refresh = False
            self.refresh_data()

    def _schedule_periodic_refresh(self) -> None:
        self.root.after(REFRESH_MINUTES * 60 * 1000, self._periodic_refresh)

    def _periodic_refresh(self) -> None:
        self.refresh_data()
        self._schedule_periodic_refresh()


def main() -> None:
    set_windows_app_user_model_id()
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    app = MealWidgetApp(root)
    _ = app
    root.mainloop()


if __name__ == "__main__":
    main()
