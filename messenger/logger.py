import base64
import io
import json
import os
import sys
from datetime import datetime, timezone


class Tee:
    """A write-through stream that duplicates output to several streams."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)
        return len(text)

    def flush(self):
        for stream in self.streams:
            stream.flush()


class Logger:
    """
    Append-only JSONL logging for a session.

    Two streams, one file each per UTC day:
      - commands: what the operator ran and the output it produced.
      - messages: every protocol Message sent or received, with its values
                  (bytes fields base64-encoded).
    """

    def __init__(self):
        self.log_dir = os.path.join(os.path.expanduser('~'), '.messenger', 'logs')
        self.created = not os.path.isdir(self.log_dir)
        os.makedirs(self.log_dir, exist_ok=True)
        date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        self.command_path = os.path.join(self.log_dir, f'{date}.commands.jsonl')
        self.message_path = os.path.join(self.log_dir, f'{date}.messages.jsonl')

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    def capture(self):
        """
        Context manager that tees stdout to an in-memory buffer while a command
        runs, mirroring output to the terminal and capturing it for the log.
        Yields the buffer; read `.getvalue()` after the block.
        """
        return _Capture()

    def record_command(self, timestamp, command, output):
        self._append(self.command_path, {
            'timestamp': timestamp,
            'command': command,
            'output': output,
        })

    def record_message(self, direction, messenger_id, message):
        values = {}
        for key, value in message._asdict().items():
            if isinstance(value, (bytes, bytearray)):
                values[key] = base64.b64encode(value).decode('ascii')
            else:
                values[key] = value
        self._append(self.message_path, {
            'timestamp': self.now(),
            'direction': direction,
            'messenger_id': messenger_id,
            'message_type': type(message).__name__,
            'values': values,
        })

    @staticmethod
    def _append(path, entry):
        try:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, default=str) + '\n')
        except Exception:
            pass


class _Capture:
    def __init__(self):
        self.buffer = io.StringIO()

    def __enter__(self):
        self._stdout = sys.stdout
        sys.stdout = Tee(self._stdout, self.buffer)
        return self.buffer

    def __exit__(self, *exc):
        sys.stdout = self._stdout
        return False
