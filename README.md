# lctop

Terminal-based llama.cpp context monitor.

Monitors the llama.cpp server `/slots` endpoint and displays slot usage in a `btop`/`htop`-style curses interface with a colour-coded progress bar.

## Requirements

- Python 3.10+
- A terminal that supports curses and at least 256 colours (for full colour support)
- A running llama.cpp server exposing the `/slots` endpoint

No third-party packages are required — the standard library is used exclusively.

## Installation

```bash
# Make executable
chmod +x lctop.py
mv lctop.py /usr/local/bin/lctop
```

Alternatively, run directly:

```bash
python3 lctop.py --port 8080
```

## Usage

```
lctop [options]
```

### Options

| Flag | Description | Default |
|---|---|---|
| `--url URL` | llama.cpp server URL | `http://127.0.0.1` |
| `--port PORT` | llama.cpp server port (optional) | — |
| `--slot N` | Slot ID to monitor | `0` |
| `--model NAME` | Model name for `/slots` query parameter | — |
| `--interval SECONDS` | Polling interval | `1.0` |
| `--test` | Run a simulated usage sweep (no server required) | — |
| `--discovery-url URL` | URL to discover models from | `http://127.0.0.1:8080/models` |
| `--debug` | Enable debug logging to `lctop_debug.log` | — |

If `--port` is not provided, `lctop` attempts to discover the active model and its port from the `--discovery-url`. When discovery finds a loaded model, the `--model` parameter is set automatically.

### Examples

Monitor slot 0 using auto-discovery:

```bash
lctop
```

Monitor slot 0 on a specific server (manual configuration):

```bash
lctop --url http://192.168.1.50 --port 8080
```

Monitor a specific model on a remote server:

```bash
lctop --url http://192.168.1.50 --port 8080 --model my-model-name
```

Monitor slot 0 using a custom discovery endpoint:

```bash
lctop --discovery-url http://another-server:9000/models
```

Monitor a specific slot with a custom polling interval:

```bash
lctop --url http://192.168.1.50 --port 8080 --slot 2 --interval 2.0
```

Run the built-in test mode to preview the UI without a server:

```bash
lctop --test
```

Enable debug logging to trace internal operations:

```bash
lctop --debug
```

Debug output is written to `lctop_debug.log` in the current directory.

## Interface

```
lctop                          slot 0
    12,345 / 8,192 tokens          150.6%              PROCESSING
              ████████████████········································

        prompt 2,296   generated 10,049   remaining 0
    http://127.0.0.1:8080   every 1s

                       q / Esc: quit
```

- **Header** — current usage / context limit, percentage, and slot status.
- **Progress bar** — colour-coded: green (<50 %), yellow (50–70 %), orange (70–85 %), red (85 %+).
- **Stats line** — prompt tokens, generated tokens, and remaining capacity.
- **Footer** — quit hint.

### Keyboard

| Key | Action |
|---|---|
| `q` / `Esc` | Quit (with confirmation dialog) |
| `y` | Confirm quit |
| Any other | Cancel quit and return to monitoring |

## Configuration

`lctop` reads optional settings from `~/.lctop.json`:

```json
{
  "url": "http://192.168.1.50",
  "port": 8080,
  "slot": 0,
  "model": "my-model-name",
  "interval": 1.0,
  "discovery_url": "http://127.0.0.1:8080/models"
}
```

CLI arguments override config file values.

## Architecture

```
┌──────────┐    ┌──────────────┐    ┌───────────────┐    ┌───────────┐
│  Main     │───>│  Monitor     │───>│  Discover     │───>│  Draw     │
│  Loop     │    │  (fetcher)   │    │  (endpoint)   │    │  (curses) │
└──────────┘    └──────────────┘    └───────────────┘    └───────────┘
                                          │                    │
                                          ▼                    ▼
                                   llama.cpp /models     llama.cpp /slots
```

- **`Monitor`** — fetches slot data from the llama.cpp `/slots` endpoint, normalises it across server versions, and keeps a bounded deque of recent samples.
- **`SlotSample`** — a lightweight dataclass holding normalised context data for one slot.
- **`draw()`** — renders a single frame to the terminal.
- **`draw_progress_bar()`** — draws the colour-coded progress bar with fill/empty segments.
- **`main_loop()`** — the polling loop that drives fetch-and-draw, handling input and resizing.
- **`run_test()`** — a simulated mode that sweeps context usage from 0 % to 100 % and back for UI preview.
- **`discover_endpoint()`** — queries the `/models` endpoint to find a loaded model and infer its server URL and port.
- **`debug_logger.py`** — file-based debug logger that writes to `lctop_debug.log` when `--debug` is active.

## Code walkthrough for beginners

This section is for readers who are comfortable programming but new to Python specifically. It's a suggested path through `lctop.py`, in the order the file is actually laid out, with notes on syntax that tends to surprise people coming from Java, C#, Go, or TypeScript. It assumes you already know what the code is *for* (see Architecture above) and just want to know how to read it.

1. **Imports and constants — top of the file.**
   Python has no header/source split: everything is read top-to-bottom by the interpreter, so anything a function uses must already be defined earlier in the file (or imported). `from debug_logger import DebugLogger` reaches into the neighbouring `debug_logger.py` and pulls the class straight in — modules are just files, there's no project/namespace configuration needed. Names in `ALL_CAPS` like `DEFAULT_URL` and `PAIR_GREEN` are a *convention* meaning "treat this as constant" — Python has no `const`/`final` keyword to enforce it. `from __future__ import annotations` near the top is boilerplate that lets type hints like `str | None` be written without Python evaluating them at import time.

2. **`SlotSample` — a `@dataclass`.**
   `@dataclass(slots=True)` auto-generates `__init__`, `__repr__`, and equality for the class from its field list, similar to a C# `record` or Kotlin `data class`. `slots=True` is a memory/speed detail: it stores fields in a fixed layout instead of Python's normal per-instance dictionary. Look at `remaining`, `percentage`, and `status` just below the fields — each is a plain method wearing an `@property` decorator, so callers read `sample.percentage` like a field, no parentheses. That's Python's equivalent of a C#/Kotlin computed property.

3. **`Monitor.fetch()` — the network call.**
   `with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:` is a *context manager* — Python's `with` block, equivalent to Java's try-with-resources or C#'s `using`. It guarantees the connection closes when the block exits, error or not. Just below, notice `except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ...) as exc:` — grouping several exception types in one tuple catches all of them with a single handler, no shared base class required.

4. **`first_int()` — a small variadic helper.**
   `def first_int(mapping, *keys: str, default: int = 0) -> int:` — `*keys` collects any number of positional arguments into a tuple, Python's version of C#'s `params string[]` or Java/C varargs. It's called like `first_int(slot, "n_ctx", "context_size", "ctx_size", default=0)` and just returns the first key that's actually present — this is how the code absorbs llama.cpp's inconsistent field naming across server versions. Note `default=0` sits *after* `*keys`: once a function captures `*args`, anything after it becomes keyword-only, so callers must write `default=0`, never pass it positionally.

5. **Truthy checks instead of null checks.**
   You'll see `if self.debug_logger:` all over `Monitor` and `main()`. Python doesn't distinguish `None` from "falsy" — every object is considered true unless it's specifically empty/zero/`None`, so this reads as "if this is set." The same idiom shows up as `slot.get("state") or slot.get("status") or slot.get("command") or ""` in `_normalise_slot()` — `or` returns its first truthy operand, which is a common Python stand-in for a null-coalescing operator.

6. **f-strings — string formatting.**
   `f"{sample.percentage:5.1f}%"` and `f"{value:n}"` (in `format_number()`) are *f-strings*: the `f` prefix means expressions inside `{}` get evaluated and inserted, roughly like C#'s `$"{value}"` or a JS template literal. The part after the colon (`5.1f`, `n`) is a format spec — `5.1f` means "fixed-point, 1 decimal, padded to width 5"; `n` means "locale-aware thousands separator."

7. **`curses` — direct terminal drawing.**
   `draw()` and `draw_progress_bar()` talk to the terminal through the `curses` module, Python's binding to the classic ncurses C library — there's no higher-level UI framework here, just cursor positioning and character writes (`window.addnstr(y, x, text, ...)`). `addstr_safe()` near the top of the drawing code is worth reading closely: it exists purely to work around a well-known curses quirk (writing into the terminal's very last cell raises an exception on some terminals), and is a good small example of defensively wrapping a quirky C library from Python.

8. **`parse_args()` and the validator functions — command-line parsing.**
   `argparse` is declarative: each `parser.add_argument(...)` call describes one flag, rather than manually looping over `sys.argv`. Look at `positive_float()`, `non_negative_int()`, and `port_number()` just above `parse_args()` — small functions passed in as `type=positive_float`. `argparse` calls them on the raw string the user typed; if they raise `argparse.ArgumentTypeError`, `argparse` turns that into a friendly CLI error message and a clean exit, automatically.

9. **`main()` and the entry point.**
   The very last line of the file, `if __name__ == "__main__":`, is Python's substitute for a `main` method entry point. Every Python file can be both a script and an importable module; this check means "only call `main()` if this file was run directly, not imported elsewhere" — which is also why `main()` itself is defined near the bottom of the file rather than the top.

## Server compatibility

The `/slots` response format varies between llama.cpp builds and versions. `lctop` handles this by:

- Accepting multiple field name variants (e.g. `n_ctx`, `context_size`, `ctx_size`).
- Falling back to prompt + generated token sums when `n_ctx_used` is absent.
- Searching nested objects (`task`, `result`, `metrics`) for missing context size values.
- Inferring processing state from boolean flags, string states, and task IDs.

## Error handling

- HTTP errors, timeouts, and JSON parse failures produce a non-fatal sample that retains the last known values and flags an error message on the status line.
- The progress bar clamps to valid ranges and never crashes on empty data.
- Terminal resize events are handled gracefully — the screen re-erases and redraws on the next cycle.

## Debug logging

When `--debug` is enabled, `lctop` writes detailed diagnostic output to `lctop_debug.log` in the current directory. This includes:

- Application startup and configuration loading
- HTTP request/response details
- Slot selection and data normalization steps
- Exception tracebacks with full stack traces

The log file is excluded from version control via `.gitignore`.

## License

This project is licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.html).
