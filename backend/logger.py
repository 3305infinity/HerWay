import logging


# Logging setup
class CustomFormatter(logging.Formatter):
    """Custom formatter with colors for different log levels.

    Each line carries the request's trace ID (see ``backend.trace``) so the log
    output for one user's request can be reassembled out of the interleaved
    output of every concurrent request.

    The ID is read defensively rather than via a ``%(trace_id)s`` format
    placeholder: records emitted by third-party libraries, or before the trace
    filter is installed, do not carry the attribute, and a formatter that
    raises would lose the log line entirely.
    """

    gray, yellow, red, bold_red, reset = (
        "\x1b[38;20m",
        "\x1b[33;20m",
        "\x1b[31;20m",
        "\x1b[31;1m",
        "\x1b[0m",
    )
    FORMATS = {
        logging.DEBUG: gray + "[%(asctime)s] %(levelname)s [%(trace)s]: %(message)s" + reset,
        logging.INFO: gray + "[%(asctime)s] %(levelname)s [%(trace)s]: %(message)s" + reset,
        logging.WARNING: yellow + "[%(asctime)s] %(levelname)s [%(trace)s]: %(message)s" + reset,
        logging.ERROR: red + "[%(asctime)s] %(levelname)s [%(trace)s]: %(message)s" + reset,
        logging.CRITICAL: bold_red + "[%(asctime)s] %(levelname)s [%(trace)s]: %(message)s" + reset,
    }

    def format(self, record):
        # Prefer the attribute set by TraceIdFilter, but fall back to reading
        # the context variable directly.
        #
        # The fallback is what actually carries most lines: a logging.Filter
        # attached to a logger does NOT run for records propagated up from its
        # child loggers, so records from e.g. `backend.routes.cases` would
        # otherwise reach this formatter with no trace_id attribute at all.
        # Reading the ContextVar here runs on the same task that emitted the
        # record, so it sees the right value.
        trace_id = getattr(record, "trace_id", None)
        if not trace_id:
            from backend.trace import get_trace_id

            trace_id = get_trace_id() or "-"

        # Short form keeps the prefix readable; the full ID is still returned to
        # the client in the X-Trace-Id header and in error bodies.
        record.trace = trace_id[:8] if trace_id != "-" else "-"
        log_fmt = self.FORMATS.get(record.levelno, self.gray)
        return logging.Formatter(log_fmt, datefmt="%Y-%m-%d %H:%M:%S").format(record)
