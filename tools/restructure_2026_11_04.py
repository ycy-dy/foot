"""一次性目录重构（2026-11-04）：用 git mv 移动，生成 docs/migration-2026-11-04.md 旧→新对照表。

用法：python3 -I tools/restructure_2026_11_04.py [--apply]（不带 --apply 只预览）
规则：
- 活动入口保持原位：AGENTS.md、README.md、V6 体系 md/yaml、.env*、.gitignore、.specify、.claude、specs、tools。
- 历史日期目录（analysis_*/review_*/daily_*/evidence_*/dream_*/football_v23_*）→ history/daily/
- 体系升级目录 system_upgrade_* → history/system_upgrades/
- 旧版体系文档 analysis_recommendation_system_v3/v4/v5* → history/system_versions/
- 台账：ledger_data/ → ledger/data/，ledger_*.md/csv、recommendation_hit_rate_ledger.md、review_ledger_* → ledger/
- 根目录其余散落文件 → history/legacy_root/
- archive/ → history/archive/
- web_system_prompt.md → specs/001-web-console/source-prompt.md
- web/ 由后续步骤改造成 src/foot_web（本脚本不处理）
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEEP = {'AGENTS.md', 'README.md', 'CLAUDE.md', '.env', '.env.example', '.gitignore', 'analysis_recommendation_system_v6_0.md',
        'analysis_recommendation_system_v6_0.yaml'}
KEEP_DIRS = {'.git', '.specify', '.claude', 'specs', 'tools', 'web', 'history', 'ledger', 'docs', 'src', 'tests', 'deploy', 'runs', 'var', '.venv'}
DAILY_PREFIX = ('analysis_', 'review_', 'daily_', 'evidence_', 'dream_', 'football_v23_')


def plan():
    moves = []
    for p in sorted(ROOT.iterdir()):
        n = p.name
        if p.is_dir():
            if n in KEEP_DIRS:
                continue
            if n.startswith('system_upgrade_'):
                moves.append((n, f'history/system_upgrades/{n}'))
            elif n == 'ledger_data':
                moves.append((n, 'ledger/data'))
            elif n == 'archive':
                moves.append((n, 'history/archive'))
            elif n.startswith(DAILY_PREFIX):
                moves.append((n, f'history/daily/{n}'))
            else:
                moves.append((n, f'history/legacy_root/{n}'))
            continue
        if n in KEEP:
            continue
        if n == 'web_system_prompt.md':
            moves.append((n, 'specs/001-web-console/source-prompt.md'))
        elif n.startswith('analysis_recommendation_system_'):
            moves.append((n, f'history/system_versions/{n}'))
        elif n.startswith(('ledger_', 'review_ledger_')) or n == 'recommendation_hit_rate_ledger.md':
            moves.append((n, f'ledger/{n}'))
        else:
            moves.append((n, f'history/legacy_root/{kind(n)}/{n}'))
    return moves


def kind(name):
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if ext in ('py', 'mjs', 'js', 'sh'):
        return 'scripts'
    if ext in ('html', 'png', 'md', 'pdf', 'jpg', 'svg'):
        return 'reports'
    return 'data'


def tracked(path):
    return subprocess.run(['git', 'ls-files', '--error-unmatch', path], cwd=ROOT, capture_output=True).returncode == 0 or \
        bool(subprocess.run(['git', 'ls-files', path], cwd=ROOT, capture_output=True, text=True).stdout.strip())


def main(apply):
    moves = plan()
    for src, dst in moves:
        print(f'{src} -> {dst}')
    print(f'共 {len(moves)} 项')
    if not apply:
        return
    for src, dst in moves:
        (ROOT / dst).parent.mkdir(parents=True, exist_ok=True)
        if tracked(src):
            subprocess.run(['git', 'mv', src, dst], cwd=ROOT, check=True)
        else:
            (ROOT / src).rename(ROOT / dst)
    lines = ['# 目录迁移对照表（2026-11-04）', '',
             '由 `tools/restructure_2026_11_04.py` 用 `git mv` 生成，文件内容未改动。历史报告正文里出现的旧路径，按本表换算到新位置。', '',
             '| 旧路径 | 新路径 |', '| --- | --- |']
    lines += [f'| `{s}` | `{d}` |' for s, d in moves]
    (ROOT / 'docs').mkdir(exist_ok=True)
    (ROOT / 'docs/migration-2026-11-04.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main('--apply' in sys.argv)
