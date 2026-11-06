"""Short scheduler ticks: dispatch rechecks, collect meaningful events and send one queued notice."""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..core.config import id_set
from ..services.recommendations import all_directions
from ..services.research import moment
from ..storage.publications import PublicationsStore

TZ = ZoneInfo('Asia/Shanghai')


class Operations:
    def __init__(self, config, rechecks, notifications):
        self.config, self.rechecks, self.notifications = config, rechecks, notifications
        self.publications = PublicationsStore(config['DATA_DIR'])
        self.deadlines = {}

    def tick(self, now=None):
        now = moment(now or datetime.now(TZ))
        prefs = self.rechecks.store.preferences()
        if prefs['enabled'] and prefs['actor'] in id_set(self.config.get('FOOT_ADMIN_USER_IDS')):
            for publication in self.publications.list():
                current = self.publications.current(publication['business_date'])
                if not current or current['id'] != publication['id'] or current['status'] != 'published':
                    continue
                try:
                    if publication['id'] not in self.deadlines:
                        path = Path(self.config['PROJECT_DIR']) / 'runs' / publication['business_date'] / publication['id'] / 'recommendations.json'
                        bundle = json.loads(path.read_text(encoding='utf-8'))
                        self.deadlines[publication['id']] = sorted({leg['kickoff'] for leg in all_directions(bundle)})
                    near = any(0 < (moment(kickoff)-now).total_seconds() <= prefs['lead_minutes']*60
                               for kickoff in self.deadlines[publication['id']])
                    if near:
                        bucket = int(now.timestamp() // (prefs['interval_minutes']*60))
                        _, reused = self.rechecks.start(publication['id'], prefs['actor'],
                            lineup_enabled=bool(prefs['lineup_enabled']), trigger_key='scheduled:' + str(bucket))
                        if not reused:
                            break
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    self.rechecks.store.store.event('recheck_dispatch_failed', prefs['actor'],
                        detail={'publication_id': publication['id'], 'error_type': type(exc).__name__})
        self.notifications.collect(now)
        self.notifications.process_one(now)
