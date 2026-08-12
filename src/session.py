import json
import os
from pathlib import Path
import tempfile


def get_session_file():
    """Return the path to the session file."""
    config_dir = Path.home() / ".conduit"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "session.json"


def write_session(token, host, port):
    """Write session data atomically to prevent torn reads."""
    data = {
        "token": token,
        "host": host,
        "port": port
    }
    
    session_file = get_session_file()
    
    # Write to a temporary file in the same directory, then atomically rename
    fd, temp_path = tempfile.mkstemp(
        dir=session_file.parent,
        prefix=".session_",
        suffix=".json.tmp"
    )
    
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        
        # Atomic rename (POSIX guarantees atomicity)
        os.replace(temp_path, session_file)
    except Exception:
        # Clean up temp file on error
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def read_session():
    """Read session data from the session file."""
    session_file = get_session_file()
    
    if not session_file.exists():
        return None
    
    try:
        with open(session_file, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None
