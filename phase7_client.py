import base64
import json
import os
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from oidc_probe import request_token

ARTIFACT = b'Approval Autopsy Phase 7 disposable artifact\n'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def main(role):
    endpoint = os.environ['AUTOPSY_PHASE7_URL']
    location = urlsplit(endpoint)
    if (location.scheme != 'https' or not location.hostname
            or not location.hostname.endswith('.trycloudflare.com')
            or location.netloc != location.hostname or location.path or location.query or location.fragment):
        raise ValueError('Unexpected lab endpoint')
    opener = build_opener(NoRedirect())

    def post(case, route, expected, *, token=None, **body):
        headers = {'Content-Type': 'application/json'}
        if token is not None:
            headers['Authorization'] = 'Bearer ' + token
        request = Request(endpoint + route, json.dumps(body).encode(), headers, method='POST')
        try:
            response = opener.open(request, timeout=25)
        except HTTPError as error:
            response = error
        with response:
            actual = json.loads(response.read(1024)).get('decision')
            print(json.dumps({'case': case, 'status': response.code, 'passed': actual == expected}), flush=True)
        if actual != expected:
            raise ValueError('Unexpected verifier decision')

    def build_token():
        return request_token('approval-autopsy-build')

    def release_token():
        return request_token('approval-autopsy-release')

    if os.environ['GITHUB_RUN_ATTEMPT'] != '1':
        if role == 'release':
            post('new attempt old approval', '/release', 'run-attempt-mismatch',
                 token=release_token(), slot='approved')
        return
    if role == 'build':
        post('direct storage route', '/storage', 'unknown-operation', token=build_token())
        post('no bearer', '/release', 'bearer-required', slot='approved')
        post('build with release audience', '/release', 'identity-denied',
             token=release_token(), slot='approved')
        for slot, artifact in (
            ('approved', ARTIFACT), ('revoked', ARTIFACT), ('substituted', ARTIFACT + b'changed'),
        ):
            post('stage '+slot, '/stage', 'staged', token=build_token(), slot=slot,
                 artifact=base64.b64encode(artifact).decode())
        return
    token = release_token()
    post('publish approved bytes', '/release', 'committed', token=token, slot='approved')
    post('replay same bearer', '/release', 'jwt-replay', token=token, slot='approved')
    post('replay approval with fresh token', '/release', 'approval-consumed',
         token=release_token(), slot='approved')
    post('substituted bytes', '/release', 'artifact-mismatch', token=release_token(), slot='substituted')
    time.sleep(12)
    post('operator revoked after staging', '/release', 'revoked', token=release_token(), slot='revoked')


if __name__ == '__main__':
    try:
        main(sys.argv[1])
    except Exception as exc:
        sys.exit('Phase 7 request failed: ' + type(exc).__name__)
