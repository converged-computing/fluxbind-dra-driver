import logging
import os

log = logging.getLogger(__name__)


def remove(filepath):
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            log.info(f"Successfully removed cpuset file {filepath}.")
        except OSError as e:
            log.warning(f"Failed to remove cpuset file {filepath}: {e}")


def write_file(filename, content):
    with open(filename, "w") as f:
        f.write(content)
