"""Validate GitHub Actions JWTs against operator-owned, exact claim policies."""
from urllib.request import urlopen

import jwt

import json
import re

class Denied(ValueError):
    pass

def object_json(raw):
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise Denied('Expected JSON object')
    return value

RUN_FIELDS = {
    'repository': r'[\w.-]+/[\w.-]+',
    'repository_id': r'[1-9][0-9]*',
    'sha': r'[a-f0-9]{40}',
    'workflow_ref': r'[^@]+/\.github/workflows/[^@]+@refs/.+',
    'workflow_sha': r'[a-f0-9]{40}',
    'run_id': r'[1-9][0-9]*',
    'run_attempt': r'[1-9][0-9]*',
}


def validate_run(run):
    if not isinstance(run, dict) or set(run) != set(RUN_FIELDS):
        raise Denied('Invalid CI run schema')
    for key, pattern in RUN_FIELDS.items():
        if not isinstance(run[key], str) or not re.fullmatch(pattern, run[key], re.ASCII):
            raise Denied(f'Invalid CI run field: {key}')
    if not run['workflow_ref'].startswith(run['repository'] + '/.github/workflows/'):
        raise Denied('Workflow belongs to another repository')




GITHUB = 'https://token.actions.githubusercontent.com'
OFFLINE = 'https://offline.approval-autopsy.invalid'


def fetch_json(url):
    with urlopen(url, timeout=10) as response:
        if response.geturl() != url:
            raise Denied('Unexpected OIDC endpoint redirect')
        return object_json(response.read(1024 * 1024))


def github_keys():
    endpoint = GITHUB + '/.well-known/jwks'
    metadata = fetch_json(GITHUB + '/.well-known/openid-configuration')
    if metadata.get('issuer') != GITHUB or metadata.get('jwks_uri') != endpoint:
        raise Denied('Unexpected GitHub OIDC discovery data')
    return fetch_json(endpoint)


def verify_token(token, policy, role, *, offline_keys=None, github_jwks=None):
    if offline_keys is not None and github_jwks is not None:
        raise Denied('Choose one OIDC trust source')
    issuer = GITHUB if offline_keys is None else OFFLINE
    try:
        header = jwt.get_unverified_header(token)
        if header.get('alg') != 'RS256' or not isinstance(header.get('kid'), str):
            raise Denied('Unsupported OIDC signing key or algorithm')
        keys = offline_keys
        if keys is None:
            keys = github_keys() if github_jwks is None else github_jwks
        matches = [key for key in keys['keys'] if key.get('kid') == header['kid']]
        if len(matches) != 1:
            raise Denied('Unknown or ambiguous OIDC signing key')
        key = jwt.PyJWK.from_dict(matches[0], algorithm='RS256').key
        expected = policy[role]
        build, release = policy['build'], policy['release']
        distinct_environment = (release.get('environment')
                                and release['environment'] != build.get('environment'))
        distinct_reusable = (release.get('job_workflow_ref') and release.get('job_workflow_sha')
                             and release['job_workflow_ref'] != build.get('job_workflow_ref'))
        if build['audience'] == release['audience'] or not (distinct_environment or distinct_reusable):
            raise Denied('Release requires a distinct audience and environment or reusable workflow')
        if bool(expected.get('job_workflow_ref')) != bool(expected.get('job_workflow_sha')):
            raise Denied('Reusable workflow policy must pin both ref and SHA')
        claims = jwt.decode(token, key, algorithms=['RS256'], issuer=issuer,
                            audience=expected['audience'], options={
                                'require': ['iss', 'aud', 'exp', 'nbf', 'iat', 'jti', 'sub'],
                                'strict_aud': True,
                            })
    except jwt.PyJWTError as exc:
        raise Denied(f'OIDC verification failed: {exc}') from exc
    pinned = ('repository', 'repository_id', 'repository_owner_id', 'workflow_ref',
              'workflow_sha', 'event_name', 'ref')
    if any(not isinstance(expected.get(k), str) or claims.get(k) != expected[k] for k in pinned):
        raise Denied('OIDC repository, workflow or event context mismatch')
    for field in ('job_workflow_ref', 'job_workflow_sha', 'environment'):
        direct_claim = {'job_workflow_ref': 'workflow_ref', 'job_workflow_sha': 'workflow_sha'}.get(field)
        # A direct job may repeat the caller workflow identity in job claims.
        if (direct_claim and not expected.get('job_workflow_ref')
                and claims.get(field) == claims[direct_claim]):
            continue
        if claims.get(field) != expected.get(field):
            raise Denied(f'OIDC job context mismatch: {field}')
    owner_id, repo_id = claims['repository_owner_id'], claims['repository_id']
    if not owner_id.isascii() or not owner_id.isdecimal() or int(owner_id) < 1:
        raise Denied('Invalid OIDC owner ID')
    owner, repo = claims['repository'].split('/')
    subject_format = expected['subject_format']
    if subject_format == 'immutable':
        prefix = f'repo:{owner}@{owner_id}/{repo}@{repo_id}'
    elif subject_format == 'legacy':
        prefix = f'repo:{owner}/{repo}'
    else:
        raise Denied('Unknown OIDC subject format')
    if expected.get('environment'):
        suffix = 'environment:' + expected['environment'].replace(':', '%3A')
    elif claims['event_name'] == 'pull_request':
        suffix = 'pull_request'
    else:
        suffix = 'ref:' + claims['ref'].replace(':', '%3A')
    if claims['sub'] != f'{prefix}:{suffix}':
        raise Denied('OIDC subject mismatch')
    run = {field: claims[field] for field in RUN_FIELDS}
    validate_run(run)
    if (not isinstance(claims['jti'], str) or not 1 <= len(claims['jti']) <= 128
            or any(type(claims[k]) is not int for k in ('iat', 'nbf', 'exp'))):
        raise Denied('Invalid OIDC token ID or timestamps')
    return {'run': run, 'role': role, 'issued': max(claims['iat'], claims['nbf']),
            'expires': claims['exp'], 'token_id': issuer + ':' + claims['jti']}


if __name__ == '__main__':
    import argparse
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('policy', type=Path)
    parser.add_argument('role', choices=('build', 'release'))
    args = parser.parse_args()
    try:
        verify_token(sys.stdin.read().strip(), object_json(args.policy.read_bytes()), args.role)
    except (ValueError, OSError, KeyError, TypeError):
        sys.exit('GitHub OIDC identity rejected')
    print('GitHub OIDC identity verified')

