"""Local worker entry for rechecks; no import-time network IO."""
import argparse
import signal

from ..core.config import load_config
from .rechecks import run_recheck


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--project-dir', required=True)
    parser.add_argument('--data-dir', required=True)
    args = parser.parse_args()
    def terminate(signum, frame):
        raise SystemExit(128+signum)
    signal.signal(signal.SIGTERM, terminate)
    config = load_config()
    config.update(PROJECT_DIR=args.project_dir, DATA_DIR=args.data_dir)
    run_recheck(config, args.task_id)


if __name__ == '__main__':
    main()
