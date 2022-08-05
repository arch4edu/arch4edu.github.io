#!/bin/python

if __name__ == '__main__':
    import sys
    import json
    import logging
    import shutil
    import time
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    from tornado.log import enable_pretty_logging
    from tornado.options import options
    from . import config
    from .models import Status, Version

    options.logging = 'debug'
    logger = logging.getLogger()
    enable_pretty_logging(options=options, logger=logger)

    latest = Status.objects.latest('timestamp').timestamp.replace(tzinfo=timezone.utc)
    last_update = None
    with open('pages/index.md') as f:
        for line in f.readlines():
            if line.startswith('Last update:'):
                last_update = datetime.fromtimestamp(float(line[line.find('(')+1:line.find(')')]), timezone.utc)
                break
    if last_update and latest < last_update:
        sys.exit()

    lines = []
    lines.append('<script src="./time.js"></script>')
    lines.append('# Build status')
    lines.append('')
    lines.append('|Category|Package|Status|Detail|Workflow|Timestamp|')
    lines.append('|:-------|:------|:-----|:-----|:-------|:--------|')

    url_prefix = f"https://github.com/{config['github']['cactus']}/actions/runs/"
    aur_prefix = 'https://aur.archlinux.org/pkgbase/'
    for record in Status.objects.all():
        data = ['']
        data.append(f'{"/".join(record.key.split("/")[:-1])}')
        data.append(f'[{record.key}]({aur_prefix}{record.key.split("/")[-1]})')
        data.append(record.status)
        data.append(record.detail)
        data.append(f'[{record.workflow}]({url_prefix}{record.workflow})')
        data.append(f'<script type="text/javascript">localize({int(record.timestamp.timestamp())});</script>')
        data.append('')
        lines.append('|'.join(data))

    lines.append('')
    lines.append('<script src="./tablefilter/tablefilter.js"></script>')
    lines.append('<script src="./table.js"></script>')

    lines.insert(2, f'Last update: <script type="text/javascript">localize({time.time()});</script>')

    with open('pages/index.md', 'w') as f:
        f.write('\n'.join(lines))
