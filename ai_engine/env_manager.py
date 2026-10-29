"""
Environment variable manager for AI Smart Mail Manager.
Enables runtime updating and persistence of configuration to .env file.
"""
import os
import re
import logging
from pathlib import Path
from django.conf import settings

logger = logging.getLogger(__name__)


def update_env_file(updates: dict) -> bool:
    """
    Safely updates or appends key-value pairs in the project's .env file,
    and simultaneously updates os.environ and django.conf.settings in memory.
    """
    base_dir = getattr(settings, 'BASE_DIR', Path('.'))
    env_path = base_dir / '.env'

    lines = []
    if env_path.exists():
        try:
            with open(env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as exc:
            logger.warning("Could not read .env file (%s); creating new", exc)
            lines = []

    updated_keys = set()
    new_lines = []

    for line in lines:
        matched = False
        for key, val in updates.items():
            pattern = rf'^{re.escape(key)}\s*='
            if re.match(pattern, line):
                new_lines.append(f"{key}={val}\n")
                updated_keys.add(key)
                matched = True
                break
        if not matched:
            new_lines.append(line)

    # Append any keys that were not already present
    for key, val in updates.items():
        if key not in updated_keys:
            if new_lines and not new_lines[-1].endswith('\n'):
                new_lines.append('\n')
            new_lines.append(f"{key}={val}\n")

    # Update in-memory runtime environment and django settings immediately
    for key, val in updates.items():
        os.environ[key] = str(val)
        if hasattr(settings, key):
            setattr(settings, key, val)

    try:
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
    except Exception as exc:
        logger.warning("Could not persist to .env file (serverless/read-only environment): %s", exc)
        return True

    logger.info("Successfully updated .env and runtime settings for keys: %s", list(updates.keys()))
    return True
