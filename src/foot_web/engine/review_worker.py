"""独立复盘worker入口，不创建Web应用或调度线程。"""
import argparse

from ..core.config import load_config
from .review_tasks import run_review


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--project-dir', required=True)
    parser.add_argument('--data-dir', required=True)
    args = parser.parse_args()
    config = load_config()
    config.update(PROJECT_DIR=args.project_dir, DATA_DIR=args.data_dir)
    run_review(config, args.task_id)


if __name__ == '__main__':
    main()
