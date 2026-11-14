"""Request and verify GitHub job tokens, emitting only selected verified claims."""
import json
import os
import sys
from copy import deepcopy
from time import perf_counter
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


from oidc_verifier import Denied, GITHUB, github_keys, verify_token


def request_token(audience):
    endpoint = os.environ['ACTIONS_ID_TOKEN_REQUEST_URL']
    location = urlsplit(endpoint)
    if (location.scheme != 'https' or not location.hostname
            or not location.hostname.endswith('.actions.githubusercontent.com')
            or location.username or location.password or location.fragment):
        raise RuntimeError('Unexpected GitHub token request endpoint')
    separator = '&' if location.query else '?'
    url = endpoint + separator + urlencode({'audience': audience})
    request = Request(url, headers={
        'Authorization': 'Bearer ' + os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN'],
    })
    with urlopen(request, timeout=15) as response:
        if response.geturl() != url:
            raise RuntimeError('Unexpected token endpoint redirect')
        return json.load(response)['value']


def probe(policy, role):
    expected = policy[role]
    start = perf_counter()
    token = request_token(expected['audience'])
    obtained = perf_counter()
    keys = github_keys()

    def verify(value, comparison, required_role):
        return verify_token(value, comparison, required_role, github_jwks=keys)

    identity = verify(token, policy, role)
    if identity['run']['sha'] != expected['workflow_sha']:
        raise RuntimeError('The lab expects the source and workflow at the same commit')
    verified = perf_counter()
    print(json.dumps({
        'decision': 'accepted', 'role': role, 'issuer': GITHUB,
        'audience': expected['audience'], 'repository_owner_id': expected['repository_owner_id'],
        'run': identity['run'], 'expires': identity['expires'],
        'event': expected['event_name'], 'job_workflow_ref': expected.get('job_workflow_ref'), 'job_workflow_sha': expected.get('job_workflow_sha'),
        'environment': expected.get('environment'),
        'token_request_ms': round((obtained-start)*1000),
        'discovery_and_verify_ms': round((verified-obtained)*1000),
    }), flush=True)

    def reject(case, value, comparison, required_role):
        try:
            verify(value, comparison, required_role)
        except Denied:
            print(json.dumps({'case': case, 'decision': 'denied'}), flush=True)
        else:
            raise RuntimeError('Expected rejection: ' + case)

    if role == 'build':
        # A job can request the other audience. Keep that audience and remove
        # only the distinguishing job context in a control policy.
        release_audience = policy['release']['audience']
        cross_role = request_token(release_audience)
        control = deepcopy(policy)
        control['build']['audience'], control['release']['audience'] = (
            release_audience, expected['audience'],
        )
        verify(cross_role, control, 'build')
        reject('valid build token with release audience', cross_role, policy, 'release')
    reject('wrong audience', request_token('approval-autopsy-wrong'), policy, role)
    for field, replacement in (
        ('repository_id', '999999999999'),
        ('workflow_sha', '0'*40),
        ('environment', 'other-environment'),
    ):
        control = deepcopy(policy)
        control[role][field] = replacement
        reject('policy mismatch: ' + field, token, control, role)


if __name__ == '__main__':
    try:
        probe(json.loads(os.environ['AUTOPSY_POLICY']), sys.argv[1])
    except Exception:
        # Exception strings from network and JWT parsing are excluded from logs.
        sys.exit('OIDC lab failed before all expected results were recorded')

