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
WINDOWS_APP_USER_MODEL_ID = "kr.gachon.mealwidget"


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


class DatePickerDialog:
    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        initial_date: dt.date,
        font_family: str,
    ) -> None:
        self.parent = parent
        self.initial_date = initial_date
        self.font_family = font_family
        self.today = dt.date.today()
        self.selected_date: dt.date | None = None
        self.view_year = initial_date.year
        self.view_month = initial_date.month
        self.month_var = tk.StringVar()

        self.window = tk.Toplevel(parent)
        self.window.title("날짜 선택")
        self.window.configure(bg="#ECE7DD")
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self.window.bind("<Escape>", lambda _event: self._cancel())

        top_row = tk.Frame(self.window, bg="#ECE7DD")
        top_row.pack(fill="x", padx=12, pady=(10, 6))

        prev_btn = tk.Button(
            top_row,
            text="<",
            command=lambda: self._move_month(-1),
            font=self._font(10, "bold"),
            bg="#F6EED3",
            activebackground="#EEDFAF",
            relief="groove",
            padx=10,
        )
        prev_btn.pack(side="left")

        month_label = tk.Label(
            top_row,
            textvariable=self.month_var,
            font=self._font(11, "bold"),
            bg="#ECE7DD",
            fg="#3A312D",
            width=16,
        )
        month_label.pack(side="left", expand=True)

        next_btn = tk.Button(
            top_row,
            text=">",
            command=lambda: self._move_month(1),
            font=self._font(10, "bold"),
            bg="#F6EED3",
            activebackground="#EEDFAF",
            relief="groove",
            padx=10,
        )
        next_btn.pack(side="right")

        self.grid_wrap = tk.Frame(self.window, bg="#ECE7DD")
        self.grid_wrap.pack(fill="both", padx=12, pady=(2, 6))

        bottom_row = tk.Frame(self.window, bg="#ECE7DD")
        bottom_row.pack(fill="x", padx=12, pady=(0, 10))

        today_btn = tk.Button(
            bottom_row,
            text="오늘 선택",
            command=lambda: self._select(self.today),
            font=self._font(9, "bold"),
            bg="#E8F0D6",
            activebackground="#D9E8BB",
            relief="groove",
            padx=10,
        )
        today_btn.pack(side="left")

        cancel_btn = tk.Button(
            bottom_row,
            text="취소",
            command=self._cancel,
            font=self._font(9),
            bg="#E7E3D7",
            relief="groove",
            padx=10,
        )
        cancel_btn.pack(side="right")

        self._render_calendar()

    def _font(self, size: int, weight: str = "normal") -> tuple[str, int, str]:
        return (self.font_family, size, weight)

    def _move_month(self, offset: int) -> None:
        month_index = self.view_year * 12 + (self.view_month - 1) + offset
        self.view_year, month_zero_based = divmod(month_index, 12)
        self.view_month = month_zero_based + 1
        self._render_calendar()

    def _render_calendar(self) -> None:
        for child in self.grid_wrap.winfo_children():
            child.destroy()

        self.month_var.set(f"{self.view_year}년 {self.view_month:02d}월")

        for col, weekday in enumerate(WEEKDAY_KR):
            fg = "#A64545" if col == 6 else "#4A3F36"
            header = tk.Label(
                self.grid_wrap,
                text=weekday,
                font=self._font(9, "bold"),
                bg="#ECE7DD",
                fg=fg,
                width=4,
            )
            header.grid(row=0, column=col, padx=2, pady=(0, 4))

        first_weekday, day_count = calendar.monthrange(self.view_year, self.view_month)
        for day in range(1, day_count + 1):
            date_value = dt.date(self.view_year, self.view_month, day)
            index = first_weekday + (day - 1)
            row = 1 + (index // 7)
            col = index % 7

            bg_color = "#FFF8DF"
            if date_value == self.today:
                bg_color = "#E8F0D6"
            if date_value == self.initial_date:
                bg_color = "#F6E7AC"

            button = tk.Button(
                self.grid_wrap,
                text=str(day),
                command=lambda d=date_value: self._select(d),
                font=self._font(
                    9, "bold" if date_value == self.initial_date else "normal"
                ),
                bg=bg_color,
                activebackground="#EEDFAF",
                relief="groove",
                width=4,
                padx=0,
                pady=2,
            )
            button.grid(row=row, column=col, padx=2, pady=2, sticky="nsew")

    def _select(self, picked_date: dt.date) -> None:
        self.selected_date = picked_date
        if self.window.winfo_exists():
            self.window.destroy()

    def _cancel(self) -> None:
        self.selected_date = None
        if self.window.winfo_exists():
            self.window.destroy()

    def show(self) -> dt.date | None:
        self.window.update_idletasks()
        parent_width = self.parent.winfo_width()
        parent_height = self.parent.winfo_height()
        parent_x = self.parent.winfo_rootx()
        parent_y = self.parent.winfo_rooty()

        width = self.window.winfo_width()
        height = self.window.winfo_height()
        x = parent_x + max((parent_width - width) // 2, 0)
        y = parent_y + max((parent_height - height) // 2, 0)
        self.window.geometry(f"+{x}+{y}")

        self.window.grab_set()
        self.window.focus_set()
        self.window.wait_window()
        return self.selected_date


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


class MealWidgetApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("가천대학교 학식 메뉴")
        self.root.geometry("1220x820")
        self.root.minsize(920, 620)
        self.root.configure(bg="#ECE7DD")

        self.font_family = resolve_font_family(self.root)
        self.icon_image: tk.PhotoImage | None = None
        self._apply_app_icon()

        self.is_topmost = True
        self.was_topmost_before_pip = self.is_topmost
        self.is_pip_mode = False
        self.normal_geometry = "1220x820"
        self.saved_window_geometry = ""
        self.is_refreshing = False
        self.pending_refresh = False
        self.root.attributes("-topmost", self.is_topmost)

        self.selected_date = dt.date.today()
        self.selected_date_var = tk.StringVar(
            value=format_korean_date(self.selected_date)
        )

        self.last_update_var = tk.StringVar(value="업데이트 대기 중")
        self.status_var = tk.StringVar(value="")

        self.cafe_visibility_vars: list[tk.BooleanVar] = [
            tk.BooleanVar(value=True) for _ in CAFETERIAS
        ]
        self.cards: list[dict[str, object]] = []
        self.latest_notes: list[dict[str, object]] = []
        self.cards_frame: tk.Frame | None = None
        self.empty_cards_label: tk.Label | None = None
        self.pip_windows: list[dict[str, object]] = []

        self._build_header()
        self._build_cards()

        self.root.bind("<F5>", lambda _event: self.refresh_data())
        self.refresh_data()
        self._schedule_periodic_refresh()

    def _font(self, size: int, weight: str = "normal") -> tuple[str, int, str]:
        return (self.font_family, size, weight)

    def _apply_app_icon(self) -> None:
        icon_ico_path = get_resource_path("assets/images/logo.ico")
        if Path(icon_ico_path).exists():
            try:
                self.root.iconbitmap(icon_ico_path)
            except tk.TclError:
                pass

        icon_png_path = get_resource_path("assets/images/logo.png")
        if not Path(icon_png_path).exists():
            return

        try:
            self.icon_image = tk.PhotoImage(file=icon_png_path)
        except tk.TclError:
            self.icon_image = None
            return

        self.root.iconphoto(True, self.icon_image)

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg="#ECE7DD")
        header.pack(fill="x", padx=14, pady=(12, 4))

        top_row = tk.Frame(header, bg="#ECE7DD")
        top_row.pack(fill="x")

        title = tk.Label(
            top_row,
            text="가천대학교 학식 메뉴",
            font=self._font(20, "bold"),
            bg="#ECE7DD",
            fg="#2E2A26",
        )
        title.pack(side="left")

        status = tk.Label(
            top_row,
            textvariable=self.status_var,
            font=self._font(10),
            bg="#ECE7DD",
            fg="#6B5E57",
        )
        status.pack(side="left", padx=(12, 0))

        right_wrap = tk.Frame(top_row, bg="#ECE7DD")
        right_wrap.pack(side="right")

        updated = tk.Label(
            right_wrap,
            textvariable=self.last_update_var,
            font=self._font(10),
            bg="#ECE7DD",
            fg="#5B504A",
        )
        updated.pack(side="left", padx=(0, 10))

        source_btn = tk.Button(
            right_wrap,
            text="원본 보기",
            command=self.open_source_pages,
            font=self._font(10),
            bg="#FDF8E5",
            relief="groove",
            padx=8,
        )
        source_btn.pack(side="left", padx=4)

        refresh_btn = tk.Button(
            right_wrap,
            text="새로고침",
            command=self.refresh_data,
            font=self._font(10, "bold"),
            bg="#FAF3D2",
            activebackground="#F6E7AC",
            relief="groove",
            padx=10,
        )
        refresh_btn.pack(side="left", padx=4)

        self.topmost_btn = tk.Button(
            right_wrap,
            text="항상 위: ON",
            command=self.toggle_topmost,
            font=self._font(10),
            bg="#E7E3D7",
            relief="groove",
            padx=8,
        )
        self.topmost_btn.pack(side="left", padx=4)

        self.pip_btn = tk.Button(
            right_wrap,
            text="PIP 모드: OFF",
            command=self.toggle_pip_mode,
            font=self._font(10),
            bg="#E1E7F2",
            relief="groove",
            padx=8,
        )
        self.pip_btn.pack(side="left", padx=4)

        date_row = tk.Frame(header, bg="#ECE7DD")
        date_row.pack(fill="x", pady=(8, 0))

        date_title = tk.Label(
            date_row,
            text="조회 날짜:",
            font=self._font(10, "bold"),
            bg="#ECE7DD",
            fg="#3A312D",
        )
        date_title.pack(side="left", padx=(0, 8))

        prev_date_btn = tk.Button(
            date_row,
            text="<",
            command=lambda: self._shift_selected_date(-1),
            font=self._font(10, "bold"),
            bg="#F6EED3",
            activebackground="#EEDFAF",
            relief="groove",
            padx=10,
        )
        prev_date_btn.pack(side="left", padx=(0, 4))

        date_label_btn = tk.Button(
            date_row,
            textvariable=self.selected_date_var,
            command=self._open_date_picker,
            font=self._font(10, "bold"),
            bg="#FFF8DF",
            activebackground="#F6EECF",
            relief="groove",
            padx=12,
        )
        date_label_btn.pack(side="left", padx=2)

        next_date_btn = tk.Button(
            date_row,
            text=">",
            command=lambda: self._shift_selected_date(1),
            font=self._font(10, "bold"),
            bg="#F6EED3",
            activebackground="#EEDFAF",
            relief="groove",
            padx=10,
        )
        next_date_btn.pack(side="left", padx=(4, 8))

        today_btn = tk.Button(
            date_row,
            text="오늘",
            command=self._reset_selected_date,
            font=self._font(9, "bold"),
            bg="#E8F0D6",
            activebackground="#D9E8BB",
            relief="groove",
            padx=8,
        )
        today_btn.pack(side="left")

        date_hint = tk.Label(
            date_row,
            text="모든 식당을 같은 날짜로 조회합니다.",
            font=self._font(9),
            bg="#ECE7DD",
            fg="#6B5E57",
        )
        date_hint.pack(side="left", padx=(10, 0))

        filter_row = tk.Frame(header, bg="#ECE7DD")
        filter_row.pack(fill="x", pady=(8, 0))

        filter_title = tk.Label(
            filter_row,
            text="표시 식당:",
            font=self._font(10, "bold"),
            bg="#ECE7DD",
            fg="#3A312D",
        )
        filter_title.pack(side="left", padx=(0, 8))

        for index, cafeteria in enumerate(CAFETERIAS):
            check = tk.Checkbutton(
                filter_row,
                text=cafeteria["name"],
                variable=self.cafe_visibility_vars[index],
                command=self._on_toggle_cafeteria,
                font=self._font(9),
                bg="#ECE7DD",
                fg="#3A312D",
                activebackground="#ECE7DD",
                selectcolor="#FFF6CC",
                padx=4,
                pady=0,
            )
            check.pack(side="left", padx=3)

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
        picked_date = picker.show()
        if not picked_date:
            return
        self._set_selected_date(picked_date)

    def _reset_selected_date(self) -> None:
        self._set_selected_date(dt.date.today())

    def _build_cards(self) -> None:
        self.cards_frame = tk.Frame(self.root, bg="#ECE7DD")
        self.cards_frame.pack(fill="both", expand=True, padx=10, pady=(6, 12))

        for index, cafeteria in enumerate(CAFETERIAS):
            card_color = CARD_COLORS[index % len(CARD_COLORS)]
            card = tk.Frame(
                self.cards_frame,
                bg=card_color,
                bd=1,
                relief="solid",
                highlightthickness=1,
            )

            tape = tk.Frame(card, bg="#FFF7CC", height=12)
            tape.pack(fill="x", padx=80, pady=(8, 4))

            title_var = tk.StringVar(value=cafeteria["name"])
            subtitle_var = tk.StringVar(value="데이터 불러오는 중...")

            title_label = tk.Label(
                card,
                textvariable=title_var,
                font=self._font(15, "bold"),
                bg=card_color,
                fg="#3A312D",
                anchor="w",
            )
            title_label.pack(fill="x", padx=12)

            subtitle_label = tk.Label(
                card,
                textvariable=subtitle_var,
                font=self._font(10),
                bg=card_color,
                fg="#66564D",
                justify="left",
                anchor="w",
            )
            subtitle_label.pack(fill="x", padx=12, pady=(2, 4))

            table_wrap = tk.Frame(
                card,
                bg="#FFFDF7",
                bd=1,
                relief="solid",
                highlightthickness=1,
                highlightbackground="#CDBFA8",
            )
            table_wrap.pack(fill="both", expand=True, padx=10, pady=(0, 6))

            table_head = tk.Frame(table_wrap, bg="#F1E3CA", height=30)
            table_head.pack(fill="x")
            table_head.pack_propagate(False)

            lunch_head_label = tk.Label(
                table_head,
                text="점심",
                font=self._font(11, "bold"),
                bg="#F1E3CA",
                fg="#4A3F36",
                anchor="center",
            )
            lunch_head_label.pack(side="left", fill="x", expand=True)

            head_divider = tk.Frame(table_head, bg="#CDBFA8", width=1)
            head_divider.pack(side="left", fill="y")

            dinner_head_label = tk.Label(
                table_head,
                text="저녁",
                font=self._font(11, "bold"),
                bg="#F1E3CA",
                fg="#4A3F36",
                anchor="center",
            )
            dinner_head_label.pack(side="left", fill="x", expand=True)

            table_body = tk.Frame(table_wrap, bg="#FFFDF7")
            table_body.pack(fill="both", expand=True)

            lunch_wrap = tk.Frame(table_body, bg="#FFFDF7")
            lunch_wrap.pack(side="left", fill="both", expand=True)

            body_divider = tk.Frame(table_body, bg="#D7CCB8", width=1)
            body_divider.pack(side="left", fill="y")

            dinner_wrap = tk.Frame(table_body, bg="#FFFDF7")
            dinner_wrap.pack(side="left", fill="both", expand=True)

            lunch_text_widget = tk.Text(
                lunch_wrap,
                wrap="word",
                width=1,
                height=1,
                font=self._font(10),
                relief="flat",
                bg="#FFFDF7",
                fg="#2F2A28",
                padx=6,
                pady=6,
                borderwidth=0,
            )
            lunch_scroll = ttk.Scrollbar(
                lunch_wrap, orient="vertical", command=lunch_text_widget.yview
            )
            lunch_text_widget.configure(yscrollcommand=lunch_scroll.set)

            lunch_text_widget.pack(side="left", fill="both", expand=True)
            lunch_scroll.pack(side="right", fill="y")

            dinner_text_widget = tk.Text(
                dinner_wrap,
                wrap="word",
                width=1,
                height=1,
                font=self._font(10),
                relief="flat",
                bg="#FFFDF7",
                fg="#2F2A28",
                padx=6,
                pady=6,
                borderwidth=0,
            )
            dinner_scroll = ttk.Scrollbar(
                dinner_wrap, orient="vertical", command=dinner_text_widget.yview
            )
            dinner_text_widget.configure(yscrollcommand=dinner_scroll.set)

            dinner_text_widget.pack(side="left", fill="both", expand=True)
            dinner_scroll.pack(side="right", fill="y")

            extra_var = tk.StringVar(value="")
            extra_label = tk.Label(
                card,
                textvariable=extra_var,
                font=self._font(9),
                bg=card_color,
                fg="#6B5E57",
                justify="left",
                anchor="w",
            )
            extra_label.pack(fill="x", padx=12, pady=(0, 4))

            self._set_text(lunch_text_widget, "불러오는 중입니다...")
            self._set_text(dinner_text_widget, "불러오는 중입니다...")

            self.cards.append(
                {
                    "title_var": title_var,
                    "subtitle_var": subtitle_var,
                    "title_label": title_label,
                    "subtitle_label": subtitle_label,
                    "lunch_head_label": lunch_head_label,
                    "dinner_head_label": dinner_head_label,
                    "card_frame": card,
                    "lunch_text_widget": lunch_text_widget,
                    "dinner_text_widget": dinner_text_widget,
                    "extra_var": extra_var,
                    "extra_label": extra_label,
                    "default_title": cafeteria["name"],
                }
            )

        self.empty_cards_label = tk.Label(
            self.cards_frame,
            text="표시할 식당을 선택해 주세요.",
            font=self._font(13, "bold"),
            bg="#ECE7DD",
            fg="#6B5E57",
        )
        self._relayout_cards()

    def _on_toggle_cafeteria(self) -> None:
        self._relayout_cards()
        if self.is_pip_mode:
            self._sync_pip_windows()

    def _relayout_cards(self) -> None:
        if not isinstance(self.cards_frame, tk.Frame):
            return

        visible_frames: list[tk.Frame] = []
        for index, card in enumerate(self.cards):
            frame = card.get("card_frame")
            if not isinstance(frame, tk.Frame):
                continue

            frame.grid_forget()
            is_visible = (
                self.cafe_visibility_vars[index].get()
                if index < len(self.cafe_visibility_vars)
                else True
            )
            if is_visible:
                visible_frames.append(frame)

        if isinstance(self.empty_cards_label, tk.Label):
            self.empty_cards_label.grid_forget()

        for row in range(3):
            self.cards_frame.grid_rowconfigure(row, weight=0)
        for col in range(2):
            self.cards_frame.grid_columnconfigure(col, weight=0)

        count = len(visible_frames)
        if count == 0:
            self.cards_frame.grid_rowconfigure(0, weight=1)
            self.cards_frame.grid_columnconfigure(0, weight=1)
            self.cards_frame.grid_columnconfigure(1, weight=1)
            if isinstance(self.empty_cards_label, tk.Label):
                self.empty_cards_label.grid(
                    row=0,
                    column=0,
                    columnspan=2,
                    sticky="nsew",
                    padx=14,
                    pady=14,
                )
            return

        cols = 1 if count == 1 else 2
        rows = (count + cols - 1) // cols

        for row in range(rows):
            self.cards_frame.grid_rowconfigure(row, weight=1)
        for col in range(cols):
            self.cards_frame.grid_columnconfigure(col, weight=1)

        for index, frame in enumerate(visible_frames):
            if cols == 1:
                row = index
                col = 0
                col_span = 1
            else:
                row, col = divmod(index, 2)
                col_span = 1
                if count % 2 == 1 and index == count - 1 and count > 1:
                    col = 0
                    col_span = 2

            frame.grid(
                row=row,
                column=col,
                columnspan=col_span,
                sticky="nsew",
                padx=10,
                pady=10,
            )

    def _set_text(self, text_widget: tk.Text, text: str) -> None:
        text_widget.configure(state="normal")
        text_widget.delete("1.0", "end")
        text_widget.insert("1.0", text)
        text_widget.configure(state="disabled")

    def open_source_pages(self) -> None:
        visible_urls: list[str] = []
        for index, cafeteria in enumerate(CAFETERIAS):
            is_visible = (
                self.cafe_visibility_vars[index].get()
                if index < len(self.cafe_visibility_vars)
                else True
            )
            if is_visible:
                visible_urls.append(cafeteria["url"])

        if not visible_urls:
            self.status_var.set("표시 중인 식당이 없어 원본 페이지를 열지 않았습니다.")
            return

        for url in visible_urls:
            webbrowser.open(url)

        if len(visible_urls) == 1:
            self.status_var.set("원본 페이지를 열었습니다.")
        else:
            self.status_var.set(f"원본 페이지 {len(visible_urls)}개를 열었습니다.")

    def _sync_pip_windows(self) -> None:
        if not self.is_pip_mode:
            return
        self._open_pip_windows()
        self._render_pip_windows(self.latest_notes)

    def _close_pip_windows(self) -> None:
        for window_info in self.pip_windows:
            window = window_info.get("window")
            if isinstance(window, tk.Toplevel) and window.winfo_exists():
                window.destroy()
        self.pip_windows.clear()

    def _on_close_pip_window(self, index: int) -> None:
        if index < len(self.cafe_visibility_vars):
            self.cafe_visibility_vars[index].set(False)
        self._on_toggle_cafeteria()

    def _open_pip_windows(self) -> None:
        self._close_pip_windows()

        visible_indices = [
            index
            for index, var in enumerate(self.cafe_visibility_vars)
            if var.get() and index < len(CAFETERIAS)
        ]
        if not visible_indices:
            return

        self.root.update_idletasks()
        base_x = self.root.winfo_rootx() + 24
        base_y = self.root.winfo_rooty() + 92
        window_width = 360
        window_height = 430
        cols = 2

        for order, index in enumerate(visible_indices):
            cafeteria = CAFETERIAS[index]
            row, col = divmod(order, cols)
            x = base_x + col * (window_width + 18)
            y = base_y + row * (window_height + 18)

            color = CARD_COLORS[index % len(CARD_COLORS)]
            window = tk.Toplevel(self.root)
            window.title(f"PIP - {cafeteria['name']}")
            window.configure(bg=color)
            window.geometry(f"{window_width}x{window_height}+{x}+{y}")
            window.minsize(280, 300)
            window.attributes("-topmost", True)
            window.attributes("-alpha", 0.97)
            window.protocol(
                "WM_DELETE_WINDOW",
                lambda i=index: self._on_close_pip_window(i),
            )

            tape = tk.Frame(window, bg="#FFF7CC", height=10)
            tape.pack(fill="x", padx=70, pady=(8, 4))

            title_var = tk.StringVar(value=cafeteria["name"])
            subtitle_var = tk.StringVar(value="")

            title_label = tk.Label(
                window,
                textvariable=title_var,
                font=self._font(13, "bold"),
                bg=color,
                fg="#3A312D",
                anchor="w",
            )
            title_label.pack(fill="x", padx=12)

            subtitle_label = tk.Label(
                window,
                textvariable=subtitle_var,
                font=self._font(9),
                bg=color,
                fg="#66564D",
                justify="left",
                anchor="w",
            )
            subtitle_label.pack(fill="x", padx=12, pady=(2, 6))

            body_wrap = tk.Frame(
                window,
                bg="#FFFDF7",
                bd=1,
                relief="solid",
                highlightthickness=1,
                highlightbackground="#CDBFA8",
            )
            body_wrap.pack(fill="both", expand=True, padx=10, pady=(0, 10))

            body_text = tk.Text(
                body_wrap,
                wrap="word",
                width=1,
                height=1,
                font=self._font(9),
                relief="flat",
                bg="#FFFDF7",
                fg="#2F2A28",
                padx=8,
                pady=8,
                borderwidth=0,
            )
            body_scroll = ttk.Scrollbar(
                body_wrap,
                orient="vertical",
                command=body_text.yview,
            )
            body_text.configure(yscrollcommand=body_scroll.set)

            body_text.pack(side="left", fill="both", expand=True)
            body_scroll.pack(side="right", fill="y")

            self._set_text(body_text, "불러오는 중입니다...")

            self.pip_windows.append(
                {
                    "index": index,
                    "window": window,
                    "title_var": title_var,
                    "subtitle_var": subtitle_var,
                    "body_text": body_text,
                }
            )

    def toggle_topmost(self) -> None:
        self.is_topmost = not self.is_topmost
        self.root.attributes("-topmost", self.is_topmost)
        self.topmost_btn.configure(
            text=f"항상 위: {'ON' if self.is_topmost else 'OFF'}"
        )

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
            self.saved_window_geometry = self.root.geometry()
            self.was_topmost_before_pip = self.is_topmost
            self.root.minsize(620, 420)
            self.root.geometry("860x540")
            self.root.attributes("-alpha", 0.95)

            self.is_topmost = True
            self.root.attributes("-topmost", True)
            self.topmost_btn.configure(text="항상 위: ON")
            self.pip_btn.configure(text="PIP 모드: ON")
        else:
            self.root.attributes("-alpha", 1.0)
            self.root.minsize(920, 620)
            self.root.geometry(self.saved_window_geometry or self.normal_geometry)

            self.is_topmost = self.was_topmost_before_pip
            self.root.attributes("-topmost", self.is_topmost)
            self.topmost_btn.configure(
                text=f"항상 위: {'ON' if self.is_topmost else 'OFF'}"
            )
            self.pip_btn.configure(text="PIP 모드: OFF")

        for card in self.cards:
            title_label = card.get("title_label")
            subtitle_label = card.get("subtitle_label")
            lunch_head_label = card.get("lunch_head_label")
            dinner_head_label = card.get("dinner_head_label")
            lunch_text_widget = card.get("lunch_text_widget")
            dinner_text_widget = card.get("dinner_text_widget")
            extra_label = card.get("extra_label")

            if isinstance(title_label, tk.Label):
                title_label.configure(
                    font=self._font(13 if self.is_pip_mode else 15, "bold")
                )
            if isinstance(subtitle_label, tk.Label):
                subtitle_label.configure(font=self._font(9 if self.is_pip_mode else 10))
            if isinstance(lunch_head_label, tk.Label):
                lunch_head_label.configure(
                    font=self._font(10 if self.is_pip_mode else 11, "bold")
                )
            if isinstance(dinner_head_label, tk.Label):
                dinner_head_label.configure(
                    font=self._font(10 if self.is_pip_mode else 11, "bold")
                )
            if isinstance(lunch_text_widget, tk.Text):
                lunch_text_widget.configure(
                    font=self._font(9 if self.is_pip_mode else 10)
                )
            if isinstance(dinner_text_widget, tk.Text):
                dinner_text_widget.configure(
                    font=self._font(9 if self.is_pip_mode else 10)
                )
            if isinstance(extra_label, tk.Label):
                extra_label.configure(font=self._font(8 if self.is_pip_mode else 9))

    def _build_subtitle(self, note: dict[str, object]) -> str:
        if note.get("error"):
            return "식단 로딩 실패"

        date_label = str(note.get("date_label", ""))
        period = str(note.get("period", "확인 불가"))
        if self.is_pip_mode:
            return date_label
        return f"{date_label}\n주간: {period}"

    def _get_bucket_entries(
        self, note: dict[str, object], bucket: str
    ) -> list[tuple[str, list[str]]]:
        grouped = note.get("grouped")
        if not isinstance(grouped, dict):
            return []

        raw_entries = grouped.get(bucket, [])
        if not isinstance(raw_entries, list):
            return []

        entries: list[tuple[str, list[str]]] = []
        for raw in raw_entries:
            if not isinstance(raw, (tuple, list)) or len(raw) != 2:
                continue

            meal_type = str(raw[0]).strip()
            raw_lines = raw[1]
            lines: list[str] = []
            if isinstance(raw_lines, list):
                for item in raw_lines:
                    text = str(item).strip()
                    if text:
                        lines.append(text)
            else:
                text = str(raw_lines).strip()
                if text:
                    lines.append(text)

            entries.append((meal_type, lines))

        return entries

    def _format_bucket_entries(
        self, entries: list[tuple[str, list[str]]], max_lines: int
    ) -> str:
        if not entries:
            return "등록된 메뉴 없음"

        lines: list[str] = []
        used_lines = 0
        show_meal_type = len(entries) > 1

        for meal_type, menu_items in entries:
            items = menu_items or ["등록된 식단내용이 없습니다."]
            if show_meal_type:
                lines.append(meal_type)

            for item in items:
                if used_lines >= max_lines:
                    lines.append("...더 있음")
                    return "\n".join(lines).strip()
                prefix = "  - " if show_meal_type else "• "
                lines.append(f"{prefix}{item}")
                used_lines += 1

            if show_meal_type:
                lines.append("")

        return "\n".join(lines).strip()

    def _build_section_text(self, note: dict[str, object], bucket: str) -> str:
        error = note.get("error")
        if isinstance(error, str) and error:
            if bucket == "lunch":
                return f"오류: {error}"
            return "확인 불가"

        entries = self._get_bucket_entries(note, bucket)
        if not bucket_has_real_items(entries):
            if bucket == "dinner" and note.get("dinner_available_any_day") is False:
                return "학교 식단표에 저녁 메뉴가 등록되지 않았습니다."
            if bucket == "lunch" and note.get("lunch_available_any_day") is False:
                return "학교 식단표에 점심 메뉴가 등록되지 않았습니다."

        max_lines = 10 if self.is_pip_mode else 28
        return self._format_bucket_entries(entries, max_lines)

    def _build_extra_info(self, note: dict[str, object]) -> str:
        if note.get("error"):
            return ""

        breakfast_count = len(self._get_bucket_entries(note, "breakfast"))
        other_count = len(self._get_bucket_entries(note, "other"))
        parts: list[str] = []
        if breakfast_count:
            parts.append(f"아침 {breakfast_count}개")
        if other_count:
            parts.append(f"기타 {other_count}개")

        if not parts:
            return ""

        prefix = "추가 메뉴" if self.is_pip_mode else "추가 메뉴:"
        return f"{prefix} {', '.join(parts)}"

    def _build_pip_note_text(self, note: dict[str, object]) -> str:
        lunch_text = self._build_section_text(note, "lunch")
        dinner_text = self._build_section_text(note, "dinner")
        parts = [f"[점심]\n{lunch_text}", f"[저녁]\n{dinner_text}"]

        extra_text = self._build_extra_info(note)
        if extra_text:
            parts.append(f"[추가]\n{extra_text}")

        return "\n\n".join(parts).strip()

    def _render_pip_windows(self, notes: list[dict[str, object]]) -> None:
        if not self.is_pip_mode:
            return

        alive_windows: list[dict[str, object]] = []
        for window_info in self.pip_windows:
            window = window_info.get("window")
            if not isinstance(window, tk.Toplevel) or not window.winfo_exists():
                continue

            index = window_info.get("index")
            if not isinstance(index, int):
                continue

            note = notes[index] if index < len(notes) else {}
            default_title = (
                CAFETERIAS[index]["name"] if index < len(CAFETERIAS) else "식당"
            )

            title_var = window_info.get("title_var")
            subtitle_var = window_info.get("subtitle_var")
            body_text = window_info.get("body_text")

            if isinstance(title_var, tk.StringVar):
                title_var.set(str(note.get("title", default_title)))
            if isinstance(subtitle_var, tk.StringVar):
                subtitle_var.set(self._build_subtitle(note))
            if isinstance(body_text, tk.Text):
                self._set_text(body_text, self._build_pip_note_text(note))

            alive_windows.append(window_info)

        self.pip_windows = alive_windows

    def _render_notes(self, notes: list[dict[str, object]]) -> None:
        for index, card in enumerate(self.cards):
            note = notes[index] if index < len(notes) else {}

            title_var = card.get("title_var")
            subtitle_var = card.get("subtitle_var")
            lunch_text_widget = card.get("lunch_text_widget")
            dinner_text_widget = card.get("dinner_text_widget")
            extra_var = card.get("extra_var")
            default_title = str(card.get("default_title", ""))

            if isinstance(title_var, tk.StringVar):
                title_var.set(str(note.get("title", default_title)))
            if isinstance(subtitle_var, tk.StringVar):
                subtitle_var.set(self._build_subtitle(note))
            if isinstance(lunch_text_widget, tk.Text):
                self._set_text(
                    lunch_text_widget, self._build_section_text(note, "lunch")
                )
            if isinstance(dinner_text_widget, tk.Text):
                self._set_text(
                    dinner_text_widget, self._build_section_text(note, "dinner")
                )
            if isinstance(extra_var, tk.StringVar):
                extra_var.set(self._build_extra_info(note))

        if self.is_pip_mode:
            self._render_pip_windows(notes)

    def refresh_data(self) -> None:
        if self.is_refreshing:
            self.pending_refresh = True
            return

        target_date = self.selected_date
        self.is_refreshing = True
        self.pending_refresh = False
        self.status_var.set(f"업데이트 중... ({format_korean_date(target_date)})")

        thread = threading.Thread(
            target=self._refresh_worker,
            args=(target_date,),
            daemon=True,
        )
        thread.start()

    def _refresh_worker(self, target_date: dt.date) -> None:
        notes: list[dict[str, object]] = []
        errors = 0

        for cafeteria in CAFETERIAS:
            try:
                notes.append(fetch_cafeteria_note(cafeteria, target_date=target_date))
            except Exception as exc:  # noqa: BLE001
                errors += 1
                notes.append(
                    {
                        "title": cafeteria["name"],
                        "date_label": f"{format_korean_date(target_date)}\n식단 로딩 실패",
                        "period": "-",
                        "full_text": "",
                        "compact_text": "",
                        "source_title": cafeteria["name"],
                        "url": cafeteria["url"],
                        "error": str(exc),
                        "selected_date": target_date.strftime("%Y.%m.%d"),
                    }
                )

        self.root.after(0, lambda: self._apply_notes(notes, errors, target_date))

    def _apply_notes(
        self,
        notes: list[dict[str, object]],
        errors: int,
        target_date: dt.date,
    ) -> None:
        if target_date != self.selected_date:
            self.is_refreshing = False
            self.pending_refresh = False
            self.refresh_data()
            return

        self.latest_notes = notes
        self._render_notes(notes)

        now_text = dt.datetime.now().strftime("최근 업데이트: %Y-%m-%d %H:%M")
        self.last_update_var.set(now_text)

        status_suffix = f" ({format_korean_date(target_date)})"
        if errors:
            self.status_var.set(f"완료 (일부 실패: {errors}개){status_suffix}")
        else:
            base_status = "완료 / PIP" if self.is_pip_mode else "완료"
            self.status_var.set(f"{base_status}{status_suffix}")

        self.is_refreshing = False
        if self.pending_refresh:
            self.pending_refresh = False
            self.refresh_data()

    def _schedule_periodic_refresh(self) -> None:
        interval_ms = REFRESH_MINUTES * 60 * 1000
        self.root.after(interval_ms, self._periodic_refresh)

    def _periodic_refresh(self) -> None:
        self.refresh_data()
        self._schedule_periodic_refresh()


def main() -> None:
    set_windows_app_user_model_id()
    root = tk.Tk()
    app = MealWidgetApp(root)
    _ = app
    root.mainloop()


if __name__ == "__main__":
    main()
