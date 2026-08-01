# lctop

Terminal-based llama.cpp context monitor.

`lctop` polls the llama.cpp server `/slots` endpoint and displays context usage in a `btop`/`htop`-style curses interface with a colour-coded progress bar.

## Requirements

- Python 3.10+
- A terminal with curses support
- A running llama.cpp server exposing `/slots`
- Access to `/models` when a model name is not supplied explicitly

A 256-colour terminal provides the full colour palette, but the interface falls back to standard terminal colours when necessary.

No third-party Python packages are required. The application uses the Python standard library plus the included `debug_logger.py` module.

## Installation

Keep `lctop.py` and `debug_logger.py` together because `lctop.py` imports the logger module at startup.

```bash
chmod +x lctop.py
sudo install -m 755 lctop.py /usr/local/bin/lctop
sudo install -m 644 debug_logger.py /usr/local/bin/debug_logger.py
```

Alternatively, run it directly from the project directory:

```bash
python3 lctop.py
```

## Usage

```text
lctop [options]
```

### Options

| Flag | Description | Default |
|---|---|---|
| `--url URL` | llama.cpp server URL or host | `http://127.0.0.1` |
| `--port PORT` | llama.cpp server port | `8080` |
| `--slot N` | Slot ID to monitor | `0` |
| `--model NAME` | Model name for the `/slots` query parameter | discovered from `/models` |
| `--interval SECONDS` | Polling interval in seconds | `1.0` |
| `--test` | Run a simulated usage sweep without contacting llama.cpp | off |
| `--debug` | Enable logging to `lctop_debug.log` | off |

The URL may include a scheme and port, for example `http://192.168.1.50:8081`. If the URL contains a port, that port takes precedence over `--port`. A URL without a scheme is normalised to use `http://`.

Unless `--model` is supplied, `lctop` queries `/models` on the resolved host and port and selects the first model whose status is reported as `loaded`. Discovery supplies only the model name; host and port always come from the CLI, the config file, the URL, or built-in defaults.

The final monitoring endpoint is built from the resolved URL and port by appending `/slots` and adding `model=<name>` to the query string.

### Examples

Monitor the default server and discover its active model:

```bash
lctop
```

Monitor a server at a specific address:

```bash
lctop --url http://192.168.1.50 --port 8080
```

The port can also be included in the URL:

```bash
lctop --url http://192.168.1.50:8080
```

Monitor a specific model without calling `/models`:

```bash
lctop --url http://192.168.1.50:8080 --model my-model-name
```

Monitor a specific slot with a custom polling interval:

```bash
lctop --slot 2 --interval 2.0
```

Preview the interface without a server:

```bash
lctop --test
```

Enable debug logging:

```bash
lctop --debug
```

Debug output is written to `lctop_debug.log` in the current working directory.

## Interface

```text
lctop                                                     slot 0

12,345 / 16,384 tokens                75.3%            PROCESSING
              [▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓········]

        prompt 2,296   generated 10,049   remaining 4,039
http://127.0.0.1:8080/slots?model=my-model   every 1s

                         q / Esc: quit
```

- **Header** — current usage, context limit, percentage, and slot status.
- **Progress bar** — green below 50%, yellow from 50% to below 70%, orange from 70% to below 85%, and red from 85% upward.
- **Stats line** — prompt tokens, generated tokens, and remaining capacity.
- **Endpoint line** — the resolved `/slots` URL and polling interval.
- **Footer** — quit hint.

When the terminal is smaller than 60 columns by 10 rows, the interface displays a minimum-size warning instead of the monitor.

### Keyboard

| Key | Action |
|---|---|
| `q`, `Q`, or `Esc` | Open the quit confirmation dialog |
| `y` or `Y` | Confirm quit |
| Any other key | Cancel the dialog and resume monitoring |

Terminal resize events trigger a redraw.

## Configuration

`lctop` reads optional settings from `~/.lctop.json`:

```json
{
  "url": "http://192.168.1.50",
  "port": 8080,
  "slot": 0,
  "model": "my-model-name",
  "interval": 1.0
}
```

CLI arguments override corresponding config-file values. Omitting `model` enables automatic model discovery. An unreadable file or invalid JSON is ignored and built-in defaults are used.

## Architecture

Startup configuration and the interactive polling loop are separate flows.

```text
Startup

┌───────────────┐
│ CLI arguments │
│ + config file │
└───────┬───────┘
        ▼
┌────────────────┐
│ ConfigResolver │── normalises URL and resolves host/port
└───────┬────────┘
        │
        ├── model supplied ───────────────────────────┐
        │                                             │
        └── model missing                             │
                ▼                                     │
        llama.cpp /models                             │
                ▼                                     │
        discover_active_model()                       │
                └─────────────────────────────────────┘
                                      ▼
                               immutable AppConfig
                                      ▼
                            build the /slots endpoint

Runtime

┌───────────┐      ┌─────────────────┐      ┌──────────────────┐
│ main_loop │─────▶│ Monitor.fetch() │─────▶│ llama.cpp /slots │
└─────┬─────┘      └────────┬────────┘      └──────────────────┘
      │                     ▼
      │                 SlotSample
      │                     │
      └─────────────────────▼
                          draw()
```

- **`AppConfig`** — immutable, fully resolved runtime configuration. It constructs the `/models` and `/slots` URLs.
- **`ConfigResolver`** — combines CLI/config values, normalises the URL, resolves and validates the port, and invokes model discovery when required.
- **`discover_active_model()`** — queries `/models` and returns the first model reported as loaded. It does not derive the host or port from the response payload.
- **`Monitor`** — fetches `/slots`, normalises response variants, and keeps a bounded deque of samples.
- **`SlotSample`** — a dataclass containing normalised context data for one slot, plus computed remaining, percentage, and status properties.
- **`main_loop()`** — schedules polling, handles keyboard input and resize events, and calls `draw()`.
- **`draw()`** — renders one interface frame.
- **`draw_progress_bar()`** — renders the colour-coded progress bar.
- **`run_test()`** — generates simulated samples and renders them without network access.
- **`debug_logger.py`** — provides optional file-based diagnostic logging.

## Code walkthrough for beginners

This section follows the approximate order of `lctop.py` and highlights Python features that may be unfamiliar to developers coming from Java, C#, Go, or TypeScript.

1. **Imports and constants.** Python modules are files that are executed when imported. Function bodies may refer to names defined later in the module because those names are looked up when the function is called, although module-level statements and decorators still require referenced names to exist when they execute. Uppercase names such as `DEFAULT_URL` and `PAIR_GREEN` are constants by convention; Python does not enforce immutability. `from __future__ import annotations` postpones evaluation of type annotations.

2. **`SlotSample` and `AppConfig`.** `@dataclass` generates common methods such as `__init__`, `__repr__`, and equality from declared fields. `slots=True` removes the normal per-instance attribute dictionary. `AppConfig` also uses `frozen=True`, which prevents normal field reassignment after construction. Properties such as `sample.percentage` expose computed values using attribute syntax.

3. **`Monitor.fetch()`.** The `with urllib.request.urlopen(...) as response` statement is a context manager, comparable to Java try-with-resources or C# `using`; it closes the response when the block exits. A tuple in an `except` clause catches any listed exception type.

4. **`first_int()`.** The `*keys` parameter collects a variable number of positional arguments into a tuple. Parameters declared after `*keys`, such as `default`, are keyword-only. The helper allows the monitor to support several field names used by different llama.cpp versions.

5. **Truth-value testing.** `if self.debug_logger:` checks the object's truth value. `None`, zero, and empty containers are falsy, but they remain distinct values and can be tested explicitly with `is None`. Expressions such as `a or b or ""` return the first truthy operand rather than a Boolean value.

6. **f-strings.** Expressions inside `{}` are evaluated and inserted into the string. Format specifications follow a colon: `5.1f` means fixed-point with one decimal place and a minimum width of five, while `n` uses locale-aware number formatting.

7. **`curses`.** The drawing functions write directly to terminal coordinates. `addstr_safe()` clips text and suppresses `curses.error` for edge cases such as writing into the bottom-right terminal cell.

8. **Argument parsing and validation.** `argparse` defines the CLI declaratively. Validator functions such as `positive_float()`, `non_negative_int()`, and `port_number()` convert CLI strings and raise `argparse.ArgumentTypeError` for invalid values. Values loaded as parser defaults from the JSON config file are not passed through these `type=` converters, so the config file should use the documented JSON types.

9. **Configuration resolution.** `ConfigResolver.resolve()` converts raw argument values into an `AppConfig`. `dataclasses.replace()` creates a new frozen configuration after model discovery instead of mutating the original object.

10. **`main()` and the entry point.** `main()` coordinates startup, configuration, curses, logging, and exit codes. The final `if __name__ == "__main__":` block runs `main()` only when the file is executed directly rather than imported.

## Server compatibility

The `/slots` response format varies between llama.cpp builds and versions. `lctop` handles this by:

- accepting response payloads that are a list, a dictionary containing `slots`, a dictionary containing `data`, or a single slot object;
- accepting several field-name variants, such as `n_ctx`, `context_size`, and `ctx_size`;
- falling back to prompt plus generated tokens when an explicit used-token count is absent;
- looking in `task`, `result`, and `metrics` for a missing context limit;
- checking `next_token[0]` for generated-token counters used by some builds;
- inferring processing state from Boolean flags, numeric flags, state strings, idle flags, and task IDs.

Model discovery accepts either a top-level list or a dictionary containing a `data` list. A model is considered active when its status object contains `value: "loaded"` or `status: "loaded"`.

## Error handling

- `/slots` HTTP, timeout, JSON, type, and normalisation failures are non-fatal after startup. The monitor retains the last known values and displays the latest error.
- If the first `/slots` request fails, a zero-valued error sample is displayed.
- Model-discovery failures are fatal during startup when no model was supplied; the program writes `lctop: discovery failed: ...` to standard error and exits with status 1.
- Invalid CLI values are rejected by `argparse` before curses starts.
- Terminal/curses failures are reported to standard error and return status 1.
- `Ctrl+C` returns status 130.
- Progress and percentage values are clamped for display, and drawing operations are bounded to the current terminal size.

## Debug logging

When `--debug` is enabled, `lctop` writes diagnostic output to `lctop_debug.log` in the current working directory, including:

- startup and resolved endpoint information;
- model-discovery requests and results;
- `/slots` HTTP request and response details;
- slot selection and normalisation details;
- simulated samples in test mode;
- warnings and exception tracebacks.

The log file should be excluded from version control.

## License

This project is licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.html).
