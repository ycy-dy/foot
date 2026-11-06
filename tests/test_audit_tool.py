import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R2 = ['理由一', '理由二']


def run(tmp_path, groups, dream=()):
    f = tmp_path / 'in.json'
    f.write_text(json.dumps({'groups': groups, 'dream': list(dream)}, ensure_ascii=False))
    return subprocess.run([sys.executable, '-I', str(ROOT / 'tools/audit_recommendations.py'), str(f)], capture_output=True, text=True)


def leg(num, market, key, label, odds, L='0'):
    return {'num': num, 'market': market, 'L': L, 'options': [{'key': key, 'label': label, 'odds': odds}], 'reasons': R2}


def test_blocks_combined_below_2_5(tmp_path):
    r = run(tmp_path, [{'name': 'late', 'sport': 'football', 'legs': [leg('005', 'HAD', 'a', '客胜', '1.35'), leg('008', 'HAD', 'h', '主胜', '1.57')]}])
    assert r.returncode == 1 and '2.1195' in r.stdout


def test_passes_valid_and_checks_dream(tmp_path):
    g = [{'name': 'late', 'sport': 'football', 'legs': [leg('005', 'HAD', 'a', '客胜', '1.35'), leg('012', 'HAD', 'a', '客胜', '1.90')]}]
    assert run(tmp_path, g).returncode == 0
    bad = run(tmp_path, g, [{'num': '012', 'score': '1:1', 'odds': '6.00'}])
    assert bad.returncode == 1 and '矛盾' in bad.stdout


def test_two_branch_uses_effective_multiple(tmp_path):
    dd = {'num': '012', 'market': 'DD', 'L': '1', 'reasons': R2,
          'options': [{'key': 'had_d', 'label': '平', 'odds': '3.18'}, {'key': 'hhad_d', 'label': '让平', 'odds': '3.56'}]}
    r = run(tmp_path, [{'name': 'late', 'sport': 'football', 'legs': [leg('005', 'HAD', 'a', '客胜', '1.35'), dd]}])
    assert r.returncode == 1   # 4.293/2 = 2.15
