#!/usr/bin/env python3
"""
lctop - terminal-based llama.cpp context monitor.

Monitors the llama.cpp /slots endpoint and displays context usage in a
btop/htop-style curses interface.

Requirements:
    Python 3.10+
    curses
    Python standard library only
"""

from __future__ import annotations

import argparse
import curses
import json
import locale
import math
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

MIN_WIDTH = 60
MIN_HEIGHT = 10
DEFAULT_URL = "http://127.0.0.1"
DEFAULT_INTERVAL = 1.0
DISCOVERY_URL = "http://127.0.0.1:8080/models"
REQUEST_TIMEOUT = 3.0
BAR_MAX_WIDTH = 72

# Colour-pair IDs.
PAIR_GREEN = 1
PAIR_YELLOW = 2
PAIR_ORANGE = 3
PAIR_RED = 4
PAIR_DIM = 5
PAIR_HEADER = 6
PAIR_ERROR = 7
PAIR_DIALOG = 8
PAIR_DIALOG_ACCENT = 9

SHADE_CHARS=("░","▒","▓","█")


@dataclass(slots=True)
class SlotSample:
    """Normalised context information for one llama.cpp slot."""

    timestamp: float
    slot_id: int
    used: int
    limit: int
    prompt_tokens: int
    generated_tokens: int
    processing: bool
    raw_state: str = ""
    error: str | None = None

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def percentage(self) -> float:
        if self.limit <= 0:
            return 0.0
        return max(0.0, min(100.0, self.used * 100.0 / self.limit))

    @property
    def status(self) -> str:
        if self.error:
            return "error"
        if self.processing:
            return "processing"
        return self.raw_state or "idle"


class Monitor:
    """Fetches llama.cpp slot data and maintains a bounded sample history."""

    def __init__(
        self,
        url: str,
        slot_id: int,
        interval: float,
        history_size: int = 300,
    ) -> None:
        self.url = url
        self.slot_id = slot_id
        self.interval = interval
        self.samples: deque[SlotSample] = deque(maxlen=history_size)
        self.last_good_sample: SlotSample | None = None

    def fetch(self) -> SlotSample:
        """Fetch and normalise one sample from the configured /slots endpoint."""
        request = urllib.request.Request(
            self.url,
            headers={
                "Accept": "application/json",
                "User-Agent": "lctop/1.0",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                payload = json.load(response)
            slot = self._select_slot(payload)
            sample = self._normalise_slot(slot)
            self.last_good_sample = sample
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            json.JSONDecodeError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
        ) as exc:
            sample = self._error_sample(str(exc))

        self.samples.append(sample)
        return sample

    def add_simulated(self, sample: SlotSample) -> None:
        self.last_good_sample = sample
        self.samples.append(sample)

    def _select_slot(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict):
            if isinstance(payload.get("slots"), list):
                slots = payload["slots"]
            elif isinstance(payload.get("data"), list):
                slots = payload["data"]
            else:
                # Some builds may expose a single slot object directly.
                slots = [payload]
        elif isinstance(payload, list):
            slots = payload
        else:
            raise TypeError("unexpected /slots response format")

        if not slots:
            raise ValueError("/slots returned no slots")

        for slot in slots:
            if not isinstance(slot, dict):
                continue
            candidate_id = first_int(
                slot,
                "id",
                "slot_id",
                "slot",
                default=-1,
            )
            if candidate_id == self.slot_id:
                return slot

        raise ValueError(f"slot {self.slot_id} not found")

    def _normalise_slot(self, slot: dict[str, Any]) -> SlotSample:
        slot_id = first_int(slot, "id", "slot_id", "slot", default=self.slot_id)

        limit = first_int(
            slot,
            "n_ctx",
            "context_size",
            "ctx_size",
            "limit",
            "capacity",
            default=0,
        )

        prompt = first_int(
            slot,
            "n_prompt_tokens",
            "prompt_tokens",
            "tokens_prompt",
            default=0,
        )

        generated = first_int(
            slot,
            "n_decoded",
            "n_generated_tokens",
            "generated_tokens",
            "tokens_generated",
            default=0,
        )

        used = first_int(
            slot,
            "n_ctx_used",
            "context_used",
            "used",
            "tokens_used",
            default=-1,
        )

        if used < 0:
            # llama.cpp versions expose slightly different counters. Prompt +
            # decoded tokens is the best portable approximation.
            used = max(0, prompt + generated)

        if limit <= 0:
            # Try nested task/result objects used by some server builds.
            for nested_key in ("task", "result", "metrics"):
                nested = slot.get(nested_key)
                if isinstance(nested, dict):
                    limit = first_int(
                        nested,
                        "n_ctx",
                        "context_size",
                        "ctx_size",
                        "limit",
                        default=limit,
                    )
                    if limit > 0:
                        break

        raw_state = str(
            slot.get("state")
            or slot.get("status")
            or slot.get("command")
            or ""
        ).strip().lower()

        processing = infer_processing(slot, raw_state)

        return SlotSample(
            timestamp=time.time(),
            slot_id=slot_id,
            used=max(0, used),
            limit=max(0, limit),
            prompt_tokens=max(0, prompt),
            generated_tokens=max(0, generated),
            processing=processing,
            raw_state=raw_state,
        )

    def _error_sample(self, message: str) -> SlotSample:
        previous = self.last_good_sample
        if previous is None:
            return SlotSample(
                timestamp=time.time(),
                slot_id=self.slot_id,
                used=0,
                limit=0,
                prompt_tokens=0,
                generated_tokens=0,
                processing=False,
                error=message,
            )

        return SlotSample(
            timestamp=time.time(),
            slot_id=previous.slot_id,
            used=previous.used,
            limit=previous.limit,
            prompt_tokens=previous.prompt_tokens,
            generated_tokens=previous.generated_tokens,
            processing=previous.processing,
            raw_state=previous.raw_state,
            error=message,
        )


def first_int(mapping: dict[str, Any], *keys: str, default: int = 0) -> int:
    """Return the first integer-like value found for any key."""
    for key in keys:
        value = mapping.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return default


def infer_processing(slot: dict[str, Any], state: str) -> bool:
    """Infer whether a slot is actively processing across server versions."""
    for key in ("is_processing", "processing", "busy"):
        value = slot.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)

    idle_value = slot.get("is_idle")
    if isinstance(idle_value, bool):
        return not idle_value

    if state:
        processing_states = {
            "processing",
            "prompt",
            "generating",
            "generation",
            "working",
            "busy",
            "started",
        }
        idle_states = {
            "idle",
            "ready",
            "available",
            "done",
            "stopped",
        }
        if any(word in state for word in processing_states):
            return True
        if any(word in state for word in idle_states):
            return False

    # llama.cpp commonly reports a non-zero task id while a slot is active.
    task_id = first_int(slot, "id_task", "task_id", default=-1)
    return task_id >= 0


def init_colours() -> None:
    curses.start_color()
    try:
        curses.use_default_colors()
        background = -1
    except curses.error:
        background = curses.COLOR_BLACK

    orange = 208 if curses.COLORS >= 256 else curses.COLOR_YELLOW
    dim_fg = 244 if curses.COLORS >= 256 else curses.COLOR_WHITE

    safe_init_pair(PAIR_GREEN, curses.COLOR_GREEN, background)
    safe_init_pair(PAIR_YELLOW, curses.COLOR_YELLOW, background)
    safe_init_pair(PAIR_ORANGE, orange, background)
    safe_init_pair(PAIR_RED, curses.COLOR_RED, background)
    safe_init_pair(PAIR_DIM, dim_fg, background)
    safe_init_pair(PAIR_HEADER, curses.COLOR_CYAN, background)
    safe_init_pair(PAIR_ERROR, curses.COLOR_RED, background)
    safe_init_pair(PAIR_DIALOG, curses.COLOR_WHITE, curses.COLOR_BLACK)
    safe_init_pair(PAIR_DIALOG_ACCENT, curses.COLOR_YELLOW, curses.COLOR_BLACK)


def safe_init_pair(pair: int, foreground: int, background: int) -> None:
    try:
        curses.init_pair(pair, foreground, background)
    except curses.error:
        pass


def colour_pair_for_fraction(fraction: float) -> int:
    if fraction < 0.50:
        return PAIR_GREEN
    if fraction < 0.70:
        return PAIR_YELLOW
    if fraction < 0.85:
        return PAIR_ORANGE
    return PAIR_RED


def addstr_safe(
    window: curses.window,
    y: int,
    x: int,
    text: str,
    attr: int = 0,
) -> None:
    """Draw text while avoiding curses' bottom-right-cell exception."""
    height, width = window.getmaxyx()
    if y < 0 or y >= height or x >= width:
        return
    if x < 0:
        text = text[-x:]
        x = 0
    available = max(0, width - x)
    if available <= 0:
        return
    try:
        window.addnstr(y, x, text, available, attr)
    except curses.error:
        pass


def centred_x(width: int, text: str) -> int:
    """Return the x-coordinate needed to centre a single or multiline string."""
    longest_line = max((len(line) for line in text.splitlines()), default=0)
    return max(0, (width - longest_line) // 2)


def format_number(value: int) -> str:
    try:
        return f"{value:n}"
    except ValueError:
        return f"{value:,}"


def draw(
    stdscr: curses.window,
    sample: SlotSample,
    url: str,
    interval: float,
    test_mode: bool = False,
) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()

    if width < MIN_WIDTH or height < MIN_HEIGHT:
        message = f"Terminal too small: need at least {MIN_WIDTH}x{MIN_HEIGHT}"
        current = f"Current size: {width}x{height}"
        addstr_safe(
            stdscr,
            max(0, height // 2 - 1),
            centred_x(width, message),
            message,
            curses.A_BOLD | curses.color_pair(PAIR_ERROR),
        )
        addstr_safe(
            stdscr,
            min(height - 1, height // 2),
            centred_x(width, current),
            current,
            curses.color_pair(PAIR_DIM),
        )
        stdscr.refresh()
        return

    title = "lctop"
    mode = "TEST MODE" if test_mode else f"slot {sample.slot_id}"
    addstr_safe(
        stdscr,
        0,
        2,
        title,
        curses.A_BOLD | curses.color_pair(PAIR_HEADER),
    )
    addstr_safe(
        stdscr,
        0,
        max(2, width - len(mode) - 2),
        mode,
        curses.A_BOLD | curses.color_pair(PAIR_HEADER),
    )

    used_text = format_number(sample.used)
    limit_text = format_number(sample.limit) if sample.limit else "?"
    header = f"{used_text} / {limit_text} tokens"
    percentage = f"{sample.percentage:5.1f}%"
    status = sample.status.upper()
    status_attr = curses.A_BOLD
    if sample.error:
        status_attr |= curses.color_pair(PAIR_ERROR)
    elif sample.processing:
        status_attr |= curses.color_pair(PAIR_GREEN)
    else:
        status_attr |= curses.color_pair(PAIR_DIM)

    addstr_safe(stdscr, 2, 2, header, curses.A_BOLD)
    addstr_safe(
        stdscr,
        2,
        centred_x(width, percentage),
        percentage,
        curses.A_BOLD
        | curses.color_pair(colour_pair_for_fraction(sample.percentage / 100.0)),
    )
    addstr_safe(
        stdscr,
        2,
        max(2, width - len(status) - 2),
        status,
        status_attr,
    )

    bar_width = min(BAR_MAX_WIDTH, width - 8)
    bar_x = max(3, (width - (bar_width + 2)) // 2)
    draw_progress_bar(stdscr, 4, bar_x, bar_width, sample.percentage / 100.0)

    stats = (
        f"prompt {format_number(sample.prompt_tokens)}   "
        f"generated {format_number(sample.generated_tokens)}   "
        f"remaining {format_number(sample.remaining)}"
    )
    addstr_safe(
        stdscr,
        6,
        centred_x(width, stats),
        stats,
        curses.color_pair(PAIR_DIM),
    )

    if sample.error:
        error_text = f"Last refresh failed: {sample.error}"
        addstr_safe(
            stdscr,
            7,
            2,
            error_text,
            curses.color_pair(PAIR_ERROR),
        )
    else:
        endpoint = (
            "TEST MODE — simulated context sweep"
            if test_mode
            else f"{url}   every {interval:g}s"
        )
        addstr_safe(
            stdscr,
            7,
            centred_x(width, endpoint),
            endpoint,
            curses.color_pair(PAIR_DIM),
        )

    footer = "q / Esc: quit"
    addstr_safe(
        stdscr,
        height - 1,
        centred_x(width, footer),
        footer,
        curses.color_pair(PAIR_DIM),
    )
    stdscr.refresh()


def draw_progress_bar(
    window: curses.window,
    y: int,
    x: int,
    width: int,
    fraction: float,
) -> None:
    fraction=max(0.0,min(1.0,fraction))
    fill_char=("░" if fraction<0.25 else
               "▒" if fraction<0.50 else
               "▓" if fraction<0.75 else
               "█")
    filled=max(0,min(width,round(width*fraction)))
    addstr_safe(window,y,x,"[",curses.A_BOLD)
    for i in range(width):
        if i<filled:
            pair=curses.color_pair(colour_pair_for_fraction((i+1)/max(1,width)))
            addstr_safe(window,y,x+1+i,fill_char,pair|curses.A_BOLD)
        else:
            addstr_safe(window,y,x+1+i,"·",curses.color_pair(PAIR_DIM))
    addstr_safe(window,y,x+width+1,"]",curses.A_BOLD)

def confirm_quit(stdscr: curses.window) -> bool:
    """Display a centred modal confirmation dialog."""
    height, width = stdscr.getmaxyx()
    dialog_width = min(42, max(26, width - 4))
    dialog_height = 7
    start_y = max(0, (height - dialog_height) // 2)
    start_x = max(0, (width - dialog_width) // 2)

    try:
        dialog = curses.newwin(dialog_height, dialog_width, start_y, start_x)
    except curses.error:
        return True

    dialog.keypad(True)
    dialog.bkgd(" ", curses.color_pair(PAIR_DIALOG))
    dialog.box()

    title = " Quit lctop? "
    addstr_safe(
        dialog,
        0,
        centred_x(dialog_width, title),
        title,
        curses.A_BOLD | curses.color_pair(PAIR_DIALOG_ACCENT),
    )

    prompt = "Press y to quit\nAny other key to continue"
    for line_offset, line in enumerate(prompt.splitlines()):
        addstr_safe(
            dialog,
            3 + line_offset,
            centred_x(dialog_width, line),
            line,
            curses.color_pair(PAIR_DIALOG),
        )
    dialog.refresh()

    key = dialog.getch()
    del dialog
    stdscr.touchwin()
    stdscr.refresh()
    return key in (ord("y"), ord("Y"))


def main_loop(stdscr: curses.window, monitor: Monitor) -> None:
    configure_curses(stdscr)

    sample = monitor.fetch()
    next_poll = time.monotonic() + monitor.interval

    while True:
        now = time.monotonic()
        if now >= next_poll:
            sample = monitor.fetch()
            # Avoid cumulative drift after delayed requests or terminal resizing.
            next_poll = now + monitor.interval

        draw(stdscr, sample, monitor.url, monitor.interval)

        timeout_ms = max(25, min(200, int((next_poll - time.monotonic()) * 1000)))
        stdscr.timeout(timeout_ms)
        key = stdscr.getch()

        if key in (ord("q"), ord("Q"), 27):
            if confirm_quit(stdscr):
                return
        elif key == curses.KEY_RESIZE:
            stdscr.erase()


def run_test(stdscr: curses.window, interval: float) -> None:
    configure_curses(stdscr)
    monitor = Monitor("simulated://slots", slot_id=0, interval=interval)

    phase = 0.0
    direction = 1.0
    last_update = 0.0
    test_step = min(max(interval, 0.05), 0.25)

    while True:
        now = time.monotonic()
        if now - last_update >= test_step:
            phase += direction * 0.0125
            if phase >= 1.0:
                phase = 1.0
                direction = -1.0
            elif phase <= 0.0:
                phase = 0.0
                direction = 1.0

            limit = 8192
            used = round(limit * phase)
            prompt = min(used, int(limit * 0.28))
            generated = max(0, used - prompt)
            processing = 0.02 < phase < 0.98

            sample = SlotSample(
                timestamp=time.time(),
                slot_id=0,
                used=used,
                limit=limit,
                prompt_tokens=prompt,
                generated_tokens=generated,
                processing=processing,
                raw_state="processing" if processing else "idle",
            )
            monitor.add_simulated(sample)
            last_update = now
        else:
            sample = monitor.samples[-1] if monitor.samples else SlotSample(
                timestamp=time.time(),
                slot_id=0,
                used=0,
                limit=8192,
                prompt_tokens=0,
                generated_tokens=0,
                processing=False,
                raw_state="idle",
            )

        draw(stdscr, sample, monitor.url, test_step, test_mode=True)
        stdscr.timeout(50)
        key = stdscr.getch()

        if key in (ord("q"), ord("Q"), 27):
            if confirm_quit(stdscr):
                return
        elif key == curses.KEY_RESIZE:
            stdscr.erase()


def configure_curses(stdscr: curses.window) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)
    stdscr.nodelay(False)
    init_colours()


def positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def port_number(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("must be between 1 and 65535")
    return parsed


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="lctop",
        description="Terminal-based llama.cpp context monitor.",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"llama.cpp server URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--port",
        type=port_number,
        metavar="PORT",
        help="llama.cpp server port",
    )
    parser.add_argument(
        "--slot",
        type=non_negative_int,
        default=0,
        metavar="N",
        help="slot ID to monitor (default: 0)",
    )
    parser.add_argument(
        "--interval",
        type=positive_float,
        default=DEFAULT_INTERVAL,
        metavar="SECONDS",
        help=f"polling interval (default: {DEFAULT_INTERVAL:g})",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="run a simulated usage sweep instead of contacting llama.cpp",
    )
    parser.add_argument(
        "--discovery-url",
        default=DISCOVERY_URL,
        help=f"URL to discover models from (default: {DISCOVERY_URL})",
    )
    return parser.parse_args(argv)


def discover_endpoint(discovery_url: str = DISCOVERY_URL) -> tuple[str, int]:
    """Discover the llama.cpp endpoint from the models list."""
    request = urllib.request.Request(
        discovery_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "lctop/1.0",
        },
    )

    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        payload = json.load(response)

    if isinstance(payload, dict) and "data" in payload:
        models = payload["data"]
    elif isinstance(payload, list):
        models = payload
    else:
        raise ValueError(f"Expected dict with 'data' or list from {discovery_url}")

    for model in models:
        status = model.get("status")
        if isinstance(status, dict) and (status.get("value") == "loaded" or status.get("status") == "loaded"):
            args_list = status.get("args")
            if isinstance(args_list, list) and len(args_list) > 5:
                try:
                    url = str(args_list[2])
                    if "://" not in url:
                        url = f"http://{url}"
                    port = int(args_list[5])
                    return url, port
                except (ValueError, TypeError, IndexError):
                    continue

    raise ValueError("No loaded model found in discovery response")


def main(argv: Iterable[str] | None = None) -> int:
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass

    args = parse_args(argv)

    try:
        if args.test:
            # Fully simulated: no endpoint is constructed and no HTTP request is made.
            curses.wrapper(run_test, args.interval)
        else:
            url = args.url
            port = args.port

            if port is None:
                try:
                    url, port = discover_endpoint(args.discovery_url)
                except (ValueError, urllib.error.URLError, TimeoutError) as e:
                    print(f"lctop: discovery failed: {e}", file=sys.stderr)
                    return 1

            endpoint = f"{url.rstrip('/')}:{port}/slots"
            monitor = Monitor(endpoint, args.slot, args.interval)
            curses.wrapper(main_loop, monitor)
    except KeyboardInterrupt:
        return 130
    except curses.error as exc:
        print(f"lctop: terminal/curses error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())