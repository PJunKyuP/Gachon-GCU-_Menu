import datetime as dt
import html
import re
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
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


def fetch_html_with_curl(url: str, timeout_seconds: int = 25) -> str:
    cmd = [
        "curl",
        "-sL",
        "--connect-timeout",
        "10",
        "--max-time",
        str(timeout_seconds),
        url,
    ]
    try:
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


def pick_day_menu(days: dict[str, DayMenu]) -> DayMenu | None:
    key = pick_day_key(days)
    if not key:
        return None
    return days.get(key)


def _parse_date_key(date_key: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(date_key, "%Y.%m.%d").date()
    except ValueError:
        return None


def pick_day_key(days: dict[str, DayMenu]) -> str | None:
    if not days:
        return None

    today = dt.date.today()
    today_key = today.strftime("%Y.%m.%d")
    if today_key in days:
        return today_key

    parsed_dates: list[tuple[dt.date, str]] = []
    for date_key in days:
        parsed = _parse_date_key(date_key)
        if parsed:
            parsed_dates.append((parsed, date_key))

    if not parsed_dates:
        return sorted(days.keys())[0]

    nearest_key = min(parsed_dates, key=lambda item: abs((item[0] - today).days))[1]
    return nearest_key


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


def find_nearest_bucket_date(
    grouped_by_date: dict[str, dict[str, list[tuple[str, list[str]]]]],
    base_date_key: str,
    bucket: str,
) -> str | None:
    base_date = _parse_date_key(base_date_key) or dt.date.today()
    candidates: list[tuple[int, int, str]] = []

    for date_key, grouped in grouped_by_date.items():
        entries = grouped.get(bucket, [])
        if not bucket_has_real_items(entries):
            continue

        parsed = _parse_date_key(date_key)
        if not parsed:
            continue

        diff = (parsed - base_date).days
        abs_diff = abs(diff)
        prefer_future = 0 if diff >= 0 else 1
        candidates.append((abs_diff, prefer_future, date_key))

    if not candidates:
        return None

    candidates.sort()
    return candidates[0][2]


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


def fetch_cafeteria_note(cafeteria: dict[str, str]) -> dict[str, object]:
    html_text = fetch_html_with_curl(cafeteria["url"])
    parsed_title, period, days = parse_menu_page(html_text)
    target_key = pick_day_key(days)
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

    fallback_messages: list[str] = []
    if target_key:
        for bucket in ("lunch", "dinner"):
            entries = grouped.get(bucket, [])
            if bucket_has_real_items(entries):
                continue

            nearest_key = find_nearest_bucket_date(grouped_by_date, target_key, bucket)
            if not nearest_key:
                continue
            if nearest_key == target_key:
                continue

            grouped[bucket] = grouped_by_date[nearest_key].get(bucket, [])
            fallback_messages.append(f"{SECTION_TITLES[bucket]} 대체: {nearest_key}")

    date_label = target_day.label if target_day else "오늘 식단 정보 없음"
    if fallback_messages:
        date_label = f"{date_label}\n({' / '.join(fallback_messages)})"

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
        self.root.attributes("-topmost", self.is_topmost)

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
        icon_ico_path = get_resource_path("logo.ico")
        if Path(icon_ico_path).exists():
            try:
                self.root.iconbitmap(icon_ico_path)
            except tk.TclError:
                pass

        icon_png_path = get_resource_path("logo.png")
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
            return

        self.is_refreshing = True
        self.status_var.set("업데이트 중...")

        thread = threading.Thread(target=self._refresh_worker, daemon=True)
        thread.start()

    def _refresh_worker(self) -> None:
        notes: list[dict[str, object]] = []
        errors = 0

        for cafeteria in CAFETERIAS:
            try:
                notes.append(fetch_cafeteria_note(cafeteria))
            except Exception as exc:  # noqa: BLE001
                errors += 1
                notes.append(
                    {
                        "title": cafeteria["name"],
                        "date_label": "식단 로딩 실패",
                        "period": "-",
                        "full_text": "",
                        "compact_text": "",
                        "source_title": cafeteria["name"],
                        "url": cafeteria["url"],
                        "error": str(exc),
                    }
                )

        self.root.after(0, lambda: self._apply_notes(notes, errors))

    def _apply_notes(self, notes: list[dict[str, object]], errors: int) -> None:
        self.latest_notes = notes
        self._render_notes(notes)

        now_text = dt.datetime.now().strftime("최근 업데이트: %Y-%m-%d %H:%M")
        self.last_update_var.set(now_text)

        if errors:
            self.status_var.set(f"완료 (일부 실패: {errors}개)")
        else:
            self.status_var.set("완료 / PIP" if self.is_pip_mode else "완료")

        self.is_refreshing = False

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
