import os

# Keep the suite hermetic: no spans leave the process while tests run.
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("OTEL_CONSOLE_EXPORT", "false")
