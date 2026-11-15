"""Hosted lab client. Keep OIDC bearers in memory."""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from oidc_probe import request_token

CASES = ('approved', 'revoked', 'substituted', 'forged', 'mismatched')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def main(role):
    url = os.environ['AUTOPSY_ALPHA_URL']
    location = urlsplit(url)
    if (location.scheme != 'https' or not location.hostname
            or not location.hostname.endswith('.trycloudflare.com')
            or location.netloc != location.hostname or location.path or location.query or location.fragment):
        raise ValueError('Unexpected gateway URL')

    def post(path, body, audience):
        token = request_token('approval-autopsy-' + audience)
        msg = Request(url + path, json.dumps(body).encode(),
                      {'Authorization': 'Bearer ' + token}, method='POST')
        try:
            response = build_opener(NoRedirect()).open(msg, timeout=45)
        except HTTPError as exc:
            response = exc
        with response:
            if response.code in (502, 504):
                return 503, {'decision': 'verification-unavailable', 'result': None}
            return response.code, json.load(response)

    def expect(case, result, status, decision):
        actual, body = result
        if (actual, body.get('decision')) != (status, decision):
            raise ValueError(f'{case} yielded unexpected status {actual}')
        print(json.dumps({'case': case, 'status': actual, 'decision': decision}), flush=True)
        return body['result']

    if role == 'build':
        if os.environ['GITHUB_RUN_ATTEMPT'] != '1':
            return
        approvals = {}
        for case in CASES:
            for _ in range(30):
                result = post('/approval', {'case': case}, 'build')
                if result[0] != 503:
                    break
                time.sleep(1)
            approval = expect(case + ' approval', result, 200, 'accepted')
            approvals[case] = approval
            request = {'approval': approval, 'operation': approval['body']['claims']['operation']}
            ticket = expect(case + ' consume', post('/consume', request, 'build'), 200, 'accepted')
            expect(case + ' start', post('/start', {**request, 'ticket': ticket}, 'build'),
                   200, 'accepted')
        request = {'approval': approvals['approved']}
        expect('direct storage', post('/storage', request, 'build'), 404, 'unknown-operation')
        expect('same-audience build publication', post('/release', request, 'release'),
               403, 'authorization-denied')
        return

    approvals = {case: expect(case + ' lookup', post(
        '/release-approval', {'case': case}, 'release'), 200, 'accepted') for case in CASES}
    request = {'approval': approvals['approved']}
    if os.environ['GITHUB_RUN_ATTEMPT'] != '1':
        expect('changed attempt', post('/release', request, 'release'), 403, 'authorization-denied')
        return
    # Operator completes staging and fault injection before allowing this job.
    for case, decision in (('revoked', 'authorization-denied'), ('substituted', 'attestation-denied'),
                           ('forged', 'attestation-denied'), ('mismatched', 'authorization-denied')):
        for _ in range(75):
            result = post('/release', {'approval': approvals[case]}, 'release')
            if result[0] != 503:
                break
            time.sleep(1)
        expect(case, result, 403, decision)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: post('/release', request, 'release'), range(2)))
    for result, (status, decision) in zip(sorted(results, key=lambda item: item[0]),
                                          ((200, 'accepted'), (403, 'authorization-denied'))):
        expect('concurrent release', result, status, decision)
    expect('approval replay', post('/release', request, 'release'), 403, 'authorization-denied')


if __name__ == '__main__':
    try:
        main(sys.argv[1])
    except Exception as exc:
        sys.exit('Alpha lab failed: ' + type(exc).__name__)
