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
- **`config_loader.py`** — standalone JSON config loader utility.
- **`debug_logger.py`** — file-based debug logger that writes to `lctop_debug.log` when `--debug` is active.

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

## License

This project is licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.html).
