#!/bin/python

if __name__ == '__main__':
    import sys
    import time
    import requests
    from pathlib import Path

    lines = []
    lines.append('<script src="./time.js"></script>')
    lines.append('# Mirror status')
    lines.append(f'Last check: <script type="text/javascript">localize({time.time()});</script>')
    lines.append('')
    lines.append('|Country|Mirror|Last update|')
    lines.append('|:------|:-----|:----------|')

    mirrorlist = Path(sys.argv[1]) / 'mirrorlist.arch4edu'
    with open(mirrorlist) as f:
        _lines = f.readlines()

    session = requests.session()
    for _line in _lines:
        _line = _line.strip('\n')
        if _line.startswith('## '):
            country = _line[3:]
        elif _line.startswith('#Server = '):
            mirror = _line[10:-5]
            print('Checking', mirror)
            try:
                last_update = session.get(f'{mirror}/lastupdate', timeout=10)
                if last_update.status_code != 200:
                    status = f'Response {last_update.status_code}'
                else:
                    last_update = last_update.content.decode('utf-8').strip('\n')
                    status = f'<script type="text/javascript">localize({last_update});</script>'
            except Exception as e:
                status = type(e).__name__
            lines.append('|'.join(['', country, mirror, status, '']))

    lines.append('')
    lines.append('<script src="./tablefilter/tablefilter.js"></script>')
    lines.append('<script src="./table.js"></script>')


    with open('mirrors.md', 'w') as f:
        f.write('\n'.join(lines))
