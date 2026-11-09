import json
from pathlib import Path
import subprocess

from foot_web.engine.tasks import analysis_action


def test_actual_analysis_controller_keeps_server_action_state():
    tasks = [None]
    for status, attempts in [('queued', []), ('running', []), ('succeeded', [{'status': 'succeeded'}]),
                             ('failed', []), ('failed', [{'status': 'failed'}]), ('cancelled', []),
                             ('cancelled', [{'status': 'failed'}]), ('partial', [{'status': 'failed'}])]:
        task = {'id': 'isolated', 'business_date': '2026-11-09', 'status': status, 'attempts': attempts,
                'progress': {}, 'provider': 'codex', 'logs_url': '/api/analysis/isolated/logs',
                'message': status, 'created_at': '2026-11-09T09:00:00+08:00', 'result_url': '/analysis/isolated'}
        task['action'] = analysis_action(task)
        tasks.append(task)
    cases = [{'task': task, 'action': analysis_action(task)} for task in tasks]
    completed = subprocess.run(['node', 'tests/ui/analysis_action_state.cjs'],
        input=json.dumps(cases), text=True, capture_output=True,
        cwd=Path(__file__).resolve().parents[1], timeout=15)
    assert completed.returncode == 0, completed.stdout + completed.stderr
