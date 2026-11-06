"""Versioned policy/runtime identity. Missing or incompatible policy fails closed."""
import hashlib
from pathlib import Path

import yaml

from .research import WORKFLOW_VERSION, fingerprint
from .audit import GATE, MIN_FB, ALLOWED, SAME_ALLOWED

POLICY_BASE = 'specs/014-evidence-gated-recommendations/policy'
RULE_FILES = ('AGENTS.md', POLICY_BASE + '.md', POLICY_BASE + '.yaml',
              'specs/014-evidence-gated-recommendations/scoring.md')


def rules_manifest(project_dir):
    root = Path(project_dir)
    texts = {name: (root / name).read_text(encoding='utf-8') for name in RULE_FILES}
    config = yaml.safe_load(texts[POLICY_BASE + '.yaml'])
    structures = {tuple(sorted(row)) for row in config['football']['allowed_structures']}
    expected = {tuple(sorted(row)) for row in ALLOWED} | {(code, code) for code in SAME_ALLOWED}
    from .evidence_confidence import VERSION, THRESHOLD
    checks = [
        ('评分实现版本', config['evidence']['score_version'] == VERSION and THRESHOLD == 70),
        ('政策启用', config.get('enabled') is True),
        ('证据门槛70%', config['evidence']['threshold_percent'] == 70),
        ('缺评分不推荐', config['evidence']['missing_score_action'] == 'no_recommendation'),
        ('足球单项', str(config['football']['minimum_selection_odds']) == str(MIN_FB)),
        ('每分支整单倍数', str(config['arithmetic']['effective_multiple_strictly_greater_than']) == str(GATE)),
        ('八结构', structures == expected),
        ('真实AI', config['decision']['ai_required'] is True),
        ('不强制条件票', config['decision']['conditional_pair_required'] is False),
        ('冻结每日台账', config['publication']['daily_frozen_ledger'] is True),
        ('不投注', config['publication']['execute_bet'] is False),
    ]
    hashes = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in texts.items()}
    package = Path(__file__).resolve().parents[1]
    code = {str(path.relative_to(package)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(package.rglob('*.py'))}
    manifest = {
        'workflow_version': WORKFLOW_VERSION, 'spec_revision': config['spec_revision'],
        'rule_hashes': hashes, 'rules_sha256': fingerprint(hashes), 'code_sha256': fingerprint(code),
        'checks': [{'name': name, 'passed': bool(passed)} for name, passed in checks],
        'compatibility': 'supported_subset' if all(ok for _, ok in checks) else 'unsupported',
        'semantic_validation': '只校验列明机器契约；证据评分非命中概率或事实认证',
        'evidence_threshold_percent': 70,
        'model_status': '未部署独立预测模型', 'model_probability': None, 'EV': None,
    }
    return manifest, texts


def same_version(first, second):
    return all(first.get(key) == second.get(key) for key in ('rules_sha256', 'code_sha256', 'workflow_version'))


def research_rules(texts):
    return texts[POLICY_BASE + '.md'] + '\n\n' + texts['specs/014-evidence-gated-recommendations/scoring.md']
