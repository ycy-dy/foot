"""Read current promoted dream ticket only; never invent or expand a score bet."""
import json
from decimal import Decimal
from pathlib import Path

from .audit import audit
from .versions import rules_manifest, same_version


def published_dream(service, config, day):
    publication = service.store.current(day)
    unavailable = {'legs': [], 'reason': '暂无按当前政策审核发布的比分4串1；需四场证据达标、路径一致、可售CRS并支持4x1。'}
    if not publication or publication['status'] != 'published':
        return unavailable
    try:
        manifest, _ = rules_manifest(config['PROJECT_DIR'])
        if manifest['compatibility'] != 'supported_subset' or not same_version(manifest, publication.get('manifest', {})):
            return unavailable | {'reason': '已发布版本属于旧政策或程序，仅供历史复盘，不展示为当前梦想推荐。'}
        folder = Path(config['PROJECT_DIR']) / 'runs' / day / publication['id']
        bundle = json.loads((folder / 'recommendations.json').read_text())
        legs = bundle.get('dream_legs') or []
        if not legs:
            return unavailable | {'reason': bundle.get('dream_reason') or unavailable['reason']}
        errors, _ = audit(bundle['audit_input'])
        if errors:
            return unavailable | {'reason': '冻结梦想单审核契约不可用，请核对原发布；不会补造比分。'}
        product, joint = Decimal(1), 1.0
        for leg in legs:
            product *= Decimal(str(leg['options'][0]['odds']))
            joint *= leg['p_mkt']
        return {'legs': legs, 'product': str(product), 'joint_market': joint,
                'publication_id': publication['id'], 'published_at': publication['created_at'],
                'model_probability': None, 'EV': None, 'reason': None}
    except (OSError, ValueError, KeyError, TypeError):
        return unavailable | {'reason': '冻结梦想记录缺失或无效，不能作为当前推荐。'}
