"""Single-use yt-dlp process. Private stdin/stdout IPC; never log input/errors."""
import json
import sys
from http.cookiejar import Cookie
from itertools import islice


def execute(raw):
    from .web_dashboard_extraction import (
        DashboardYoutubeDL, ExtractionBudget, ExtractionBudgetExceeded, UnsupportedDashboardURL,
    )
    read_bytes = 0
    try:
        if len(raw) > 8 * 1024 * 1024:
            raise ExtractionBudgetExceeded()
        job = json.loads(raw)
        budget = ExtractionBudget(*job['limits'])
        options = job['options']
        options.update(quiet=True, no_warnings=True, verbose=False, cachedir=False,
                       skip_download=True, socket_timeout=min(10, budget.timeout),
                       retries=1, extractor_retries=1)
        with DashboardYoutubeDL(options) as client:
            client.read_budget = budget
            for cookie in job.get('cookies', []):
                client.cookiejar.set_cookie(Cookie(**cookie))
            data = client.extract_info(job['subject'], **job['kwargs'])
            if isinstance(data, dict) and 'entries' in data:
                data['entries'] = list(islice(data.get('entries') or [], job.get('limit', 201)))
            data = client.sanitize_info(data)
            read_bytes = budget.used
        result = {'data': data, 'read_bytes': read_bytes}
    except UnsupportedDashboardURL:
        result = {'error': 'unsupported'}
    except ExtractionBudgetExceeded:
        result = {'error': 'budget'}
    except BaseException:
        result = {'error': 'provider'}
    return json.dumps(result).encode()


def main():
    output = sys.stdout.buffer
    sys.stdout = sys.stderr
    if '--serve' in sys.argv:
        # Preload imports before announcing readiness, without network or cookies.
        from . import web_dashboard_extraction
        output.write(b'READY\n'); output.flush()
        while True:
            header = sys.stdin.buffer.readline(20)
            if not header:
                return
            if not header.strip().isdigit() or int(header) > 8 * 1024 * 1024:
                return
            size = int(header)
            raw = sys.stdin.buffer.read(size)
            if len(raw) != size:
                return
            result = execute(raw)
            output.write(str(len(result)).encode() + b'\n' + result)
            output.flush()
    else:
        raw = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
        output.write(execute(raw)); output.flush()


if __name__ == '__main__':
    main()
