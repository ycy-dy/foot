"""Frozen document/runtime identity and explicitly bounded policy compatibility checks."""
import hashlib
import re
from pathlib import Path

from .research import WORKFLOW_VERSION, fingerprint

RULE_FILES = ('AGENTS.md',)


def rules_manifest(project_dir):
    root = Path(project_dir)
    texts = {name: (root / name).read_text(encoding='utf-8') for name in RULE_FILES}
    hashes = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in texts.items()}
    package = Path(__file__).resolve().parents[1]
    code = {str(path.relative_to(package)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(package.rglob('*.py'))}
    manifest = {
        'workflow_version': WORKFLOW_VERSION, 'spec_revision': 'policy_removed',
        'rule_hashes': hashes, 'rules_sha256': fingerprint(hashes), 'code_sha256': fingerprint(code),
        'checks': [], 'compatibility': 'policy_unavailable',
        'semantic_validation': '当前未定义业务分析/推荐体系，禁止生成新推荐',
        'model_status': '未部署独立预测模型', 'model_probability': None, 'EV': None,
    }
    return manifest, texts


def same_version(first, second):
    return all(first.get(key) == second.get(key) for key in ('rules_sha256', 'code_sha256', 'workflow_version'))


def research_rules(texts):
    return '当前分析与推荐体系已删除；本任务仅允许事实核验、历史读取和规范设计，不生成新推荐。'
