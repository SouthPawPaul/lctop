"""Debug logger module for lctop.

Provides a simple file-based debug logger that only writes when
the --debug flag is active. All log output goes to lctop_debug.log
in the current working directory.
"""

from __future__ import annotations

import datetime
import os
import sys
import traceback
from typing import Any


class DebugLogger:
    """Writes timestamped log messages to a file in the current folder.

    Only writes to disk when enabled (via --debug flag).
    All other methods become no-ops when disabled.
    """

    LOG_FILE = "lctop_debug.log"

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.log_path: str | None = None

        if enabled:
            self.log_path = os.path.join(os.getcwd(), self.LOG_FILE)
            # Start a fresh log file each run
            try:
                with open(self.log_path, "w") as f:
                    f.write(f"=== lctop debug log started at {self._timestamp()} ===\n")
            except OSError:
                pass  # Best effort; don't crash the app

    def _timestamp(self) -> str:
        """Return a human-readable timestamp string."""
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    def log(self, message: str, level: str = "INFO") -> None:
        """Write a timestamped message to the log file.

        Args:
            message: The log message to write.
            level: Log level string (DEBUG, INFO, WARNING, ERROR).
        """
        if not self.enabled or self.log_path is None:
            return

        timestamp = self._timestamp()
        line = f"[{timestamp}] [{level:>7}] {message}\n"

        try:
            with open(self.log_path, "a") as f:
                f.write(line)
        except OSError:
            # If we can't write to the log file, print to stderr as fallback
            print(f"[DEBUG] {message}", file=sys.stderr, flush=True)

    def debug(self, message: str) -> None:
        """Log a debug-level message."""
        self.log(message, "DEBUG")

    def info(self, message: str) -> None:
        """Log an informational message."""
        self.log(message, "INFO")

    def warning(self, message: str) -> None:
        """Log a warning message."""
        self.log(message, "WARNING")

    def error(self, message: str) -> None:
        """Log an error message."""
        self.log(message, "ERROR")

    def exception(self, message: str, exc: BaseException | None = None) -> None:
        """Log an error message along with full exception traceback.

        Args:
            message: A descriptive message about what went wrong.
            exc: The exception object to log. If None, uses sys.exc_info().
        """
        if not self.enabled or self.log_path is None:
            return

        self.error(message)

        timestamp = self._timestamp()
        try:
            with open(self.log_path, "a") as f:
                if exc is not None:
                    f.write(f"[{timestamp}] EXCEPTION:\n")
                    f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
                else:
                    tb_lines = traceback.format_exc()
                    if tb_lines.strip():
                        f.write(f"[{timestamp}] EXCEPTION:\n")
                        f.write(tb_lines)
        except OSError:
            if exc is not None:
                print(f"[DEBUG] Exception: {exc}", file=sys.stderr, flush=True)
            else:
                print(f"[DEBUG] Exception: {sys.exc_info()[1]}", file=sys.stderr, flush=True)

    def close(self) -> None:
        """Write a closing marker to the log file."""
        if self.enabled and self.log_path:
            try:
                with open(self.log_path, "a") as f:
                    f.write(f"\n=== lctop debug log ended at {self._timestamp()} ===\n\n")
            except OSError:
                pass
