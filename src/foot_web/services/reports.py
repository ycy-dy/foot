"""读取项目里最新一次分析报告的“最终推荐汇总”（第一阶段只读展示；第四阶段由 Agent 任务产出版本化结果）。"""
import re
import json
import sqlite3
from pathlib import Path

import markdown as md

# 新产出写入 runs/<业务日>/<run_id>/；历史产出在 history/daily/
DIR_PATTERNS = ('runs/*/*', 'history/daily/analysis_*', 'history/daily/review_*_and_analysis_*', 'history/daily/daily_analysis_*')


def latest_report(project_dir, business_date=None, data_dir=None):
    root = Path(project_dir)
    db_path = Path(data_dir or root / 'var') / 'app.db'
    if db_path.exists():
        with sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='publication_current'").fetchone():
                row = db.execute('''SELECT p.payload FROM publication_current c JOIN publications p
                    ON c.publication_id=p.id''' + (' WHERE c.business_date=?' if business_date else '')
                    + ' ORDER BY p.created_at DESC LIMIT 1', (business_date,) if business_date else ()).fetchone()
                if row:
                    publication = json.loads(row[0])
                    path = root / 'runs' / publication['business_date'] / publication['id'] / 'report.md'
                    if publication['status'] != 'published' or not path.is_file():
                        return None
                    from .drafts import render_draft
                    text = path.read_text(encoding='utf-8')
                    return {'path': str(path.relative_to(root)), 'mtime': path.stat().st_mtime,
                            'summary_html': render_draft(text.split('\n---\n', 1)[0]),
                            'full_html': render_draft(text), 'publication': publication}
    cands = []
    for pat in DIR_PATTERNS:
        for d in root.glob(pat):
            if d.name.startswith('publication-'):
                continue  # Files alone cannot promote an interrupted publication.
            f = d / 'report.md'
            if f.is_file():
                cands.append(f)
    if business_date:
        tag = business_date
        dated = [f for f in cands if tag in str(f.parent.relative_to(root))]
        cands = dated or []
    if not cands:
        return None
    f = max(cands, key=lambda p: p.stat().st_mtime)
    text = f.read_text()
    summary = text.split('\n---\n', 1)[0] if text.lstrip().startswith('# 最终推荐汇总') else None
    return {'path': str(f.relative_to(root)), 'mtime': f.stat().st_mtime,
            'summary_html': md.markdown(summary, extensions=['tables']) if summary else None,
            'full_html': md.markdown(text, extensions=['tables'])}


def safe_slug(value):
    return re.sub(r'[^0-9A-Za-z_\-]', '', value)
