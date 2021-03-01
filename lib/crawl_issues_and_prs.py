#!/usr/bin/env python
#
# With huge thanks to [Sivel](https://github.com/sivel)
# 99% of this script is his work - Greg
# 
# Takes a GitHub Org and Repo, and fetches the Issues and PRs via GraphQL
# Set $GITHUB_TOKEN to use an authenticated account
#
# Example:
# ./issues_and_prs.py --git-org  'containers' \
#                     --git-repo 'ansible-podman-collections' \
#                     --all

import argparse
import contextlib
import json
import os
import sys
import time

import requests
from requests.exceptions import HTTPError, ConnectionError


RATE_LIMIT = '''
query {
  viewer {
    login
  }
  rateLimit {
    limit
    cost
    remaining
    resetAt
  }
}
'''


QUERY1 = '''
query {
  repository(owner: "%s", name: "%s") {
'''
QUERY2 = '''
%s
%s
  }
}
'''

COMMON = '''
        assignees(first: 100) {
          nodes {
            login
            name
          }
        }
        author {
          login
        }
        authorAssociation
        comments(last: 100) {
          nodes {
            author {
              login
            }
            body
            bodyHTML
            bodyText
            createdAt
            createdViaEmail
            editor {
              login
            }
            lastEditedAt
            publishedAt
          }
        }
        labels(first: 100) {
            nodes {
                name
            }
        }
        projectCards(first: 100) {
          nodes {
            column {
              name
              project {
                body
                name
                closed
              }
            }
          }
        }
        reactions(first: 100) {
          nodes {
            content
            user {
              login
              name
            }
          }
        }
        repository {
          nameWithOwner
        }
        body
        bodyHTML
        bodyText
        closed
        closedAt
        createdAt
        createdViaEmail
        editor {
          login
        }
        lastEditedAt
        locked
        milestone {
          number
          title
          state
          url
        }
        number
        publishedAt
        state
        title
        url
'''

ISSUES = '''
    issues(first: 20, states: %(states)s%(cursor)s) {
      nodes {
%(common)s
      }
      pageInfo {
        endCursor
        hasNextPage
      }
      totalCount
    }
'''

ISSUE = '''
    issue_%(number)d: issue(number: %(number)d) {
%(common)s
    }
'''

PULL_REQUEST_COMMON = '''
        additions
        changedFiles
        deletions
        headRepository {
          name
          url
        }
        headRepositoryOwner {
          login
        }
        isCrossRepository
        mergeable
        merged
        mergedAt
        baseRefName
        commits(first: 100) {
          nodes {
            commit {
              author {
                date
                email
                name
                user {
                  login
                  name
                }
              }
              authoredByCommitter
              committer {
                date
                email
                name
                user {
                  login
                  name
                }
              }
              message
              messageBody
              status {
                state
              }
            }
          }
        }
        files(first: 100) {
            nodes {
                additions
                deletions
                path
            }
        }
        reviewRequests(first: 100) {
          nodes {
            requestedReviewer {
              __typename
              ... on User {
                name
                login
              }
            }
          }
        }
        reviews(first: 100) {
          nodes {
            author {
              login
            }
            bodyText
            state
          }
        }
'''

PULL_REQUESTS = '''
    pullRequests(first: 20, states: %(states)s%(cursor)s) {
      nodes {
%(common)s
%(pr_common)s
      }
      pageInfo {
        endCursor
        hasNextPage
      }
      totalCount
    }
'''

PULL_REQUEST = '''
    pr_%(number)d: pullRequest(number: %(number)d) {
%(common)s
%(pr_common)s
    }
'''


def transform_nodes_of_things(item, key, subkey):
    item[key] = [n[subkey] for n in item[key]['nodes']]


def make_commenters(item):
    nodes = item['comments']['nodes']
    item['commenters'] = [
        n['author']['login'] for n in nodes if n['author']
    ]


def make_reviewers(item):
    nodes = item['reviews']['nodes']
    item['reviewers'] = [
        n['author']['login'] for n in nodes if n['author']
    ]


def transform_project_cards(item):
    nodes = item['projectCards']['nodes']

    project_cards = set()
    for n in nodes:
        if n['column'] and n['column']['project']:
            project_cards.add(
                '%s: %s' % (
                    n['column']['project']['name'],
                    n['column']['name']
                )
            )

    item['projectCards'] = list(project_cards)


def make_committers(item):
    nodes = item['commits']['nodes']

    committers = set()
    for node in nodes:
        if node['commit']['author']['user']:
            committers.add(node['commit']['author']['user']['login'])
        if node['commit']['committer']['user']:
            committers.add(node['commit']['committer']['user']['login'])

    item['committers'] = list(committers)


def transform(items):
    for item in items:
        transform_nodes_of_things(item, 'labels', 'name')
        transform_nodes_of_things(item, 'assignees', 'login')
        make_commenters(item)
        transform_nodes_of_things(item, 'reactions', 'content')
        transform_project_cards(item)
        try:
            make_committers(item)
        except KeyError:
            pass
        try:
            make_reviewers(item)
        except KeyError:
            pass
        try:
            transform_nodes_of_things(item, 'files', 'path')
        except (KeyError, TypeError):
            pass


@contextlib.contextmanager
def lock_file():
    if os.path.exists('/tmp/github.lock'):
        print('Lockfile exists. Exiting...')
        sys.exit(2)
    with open('/tmp/github.lock', 'w+') as f:
        f.write(str(os.getpid()))
    try:
        yield
    except Exception:
        raise
    finally:
        os.unlink('/tmp/github.lock')


def get_previous_numbers(args):
    with open(os.path.join(output_dir, 'pull_requests.json')) as f:
        prs = set([pr['number'] for pr in json.load(f)])

    with open(os.path.join(output_dir, 'issues.json')) as f:
        issues = set([issue['number'] for issue in json.load(f)])

    return issues, prs


def chunker(items, length=250):
    i = 0
    while i * length < len(items):
        yield items[length * i:length * (i + 1)]
        i += 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--git-org')
    parser.add_argument('--git-repo')
    args = parser.parse_args()

    output_dir = args.git_org + '%' + args.git_repo

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    try:
        prev_issues, prev_prs = get_previous_numbers(args)
    except Exception:
        prev_issues = set()
        prev_prs = set()

    cur_issues = set()
    cur_prs = set()

    output = {
        'pull_requests': [],
        'issues': [],
    }

    gql_s = requests.Session()
    gql_s.headers = {
        'User-Agent': 'Awesome-Octocat-App',
        'Authorization': 'bearer %s' % os.getenv('GITHUB_TOKEN')
    }

    rest_s = requests.Session()
    rest_s.headers = {
        'User-Agent': 'Awesome-Octocat-App',
        'Authorization': 'token %s' % os.getenv('GITHUB_TOKEN')
    }

    fetch = True
    pull_requests = None
    issues = None
    loop = 1
    query = QUERY1 % tuple([args.git_org,args.git_repo]) + QUERY2

    if args.all:
        states = {
            'issues': '[OPEN, CLOSED]',
            'pull_requests': '[OPEN, CLOSED, MERGED]'
        }
    else:
        states = {
            'issues': '[OPEN]',
            'pull_requests': '[OPEN]',
        }

    while fetch:
        print('Loop: %d' % loop)
        filters = ['', '']
        if pull_requests:
            if pull_requests['pageInfo']['hasNextPage']:
                filters[0] = (
                    PULL_REQUESTS % dict(
                        states=states['pull_requests'],
                        cursor=', after: "%s"' % (
                            pull_requests['pageInfo']['endCursor']
                        ),
                        common=COMMON,
                        pr_common=PULL_REQUEST_COMMON,
                    )
                )
        else:
            filters[0] = PULL_REQUESTS % dict(
                states=states['pull_requests'],
                cursor='',
                common=COMMON,
                pr_common=PULL_REQUEST_COMMON,
            )

        if issues:
            if issues['pageInfo']['hasNextPage']:
                filters[1] = (
                    ISSUES % dict(
                        states=states['issues'],
                        cursor=(
                            ', after: "%s"' % issues['pageInfo']['endCursor']
                        ),
                        common=COMMON
                    )
                )
        else:
            filters[1] = ISSUES % dict(
                states=states['issues'],
                cursor='',
                common=COMMON
            )

        try:
            pr_had_next_page = (
                True if loop == 1 else pull_requests['pageInfo']['hasNextPage']
            )
        except Exception:
            pr_had_next_page = False
        try:
            issues_had_next_page = (
                True if loop == 1 else issues['pageInfo']['hasNextPage']
            )
        except Exception:
            issues_had_next_page = False

        print('PRs=%s Issues=%s' % (bool(filters[0]), bool(filters[1])))

        try:
            r = gql_s.post(
                'https://api.github.com/graphql',
                data=json.dumps({
                    'query': query % tuple(filters)
                })
            )
            resp = r.json()
        except (HTTPError, ConnectionError, ValueError) as e:
            print(str(e))
            continue

        if 'errors' in resp:
            print('Error: %r' % (resp['errors'],))
            sleep_time = int(r.headers.get('Retry-After', 10))
            print('Sleeping %ds...' % sleep_time)
            time.sleep(sleep_time)
            continue

        repo_data = resp.get('data', {}).get('repository', {})

        if ((pr_had_next_page and
             'pullRequests' not in repo_data) or
                (issues_had_next_page and
                 'issues' not in repo_data)):
            print('Error: %r' % (r.text,))
            sleep_time = int(r.headers.get('Retry-After', 10))
            print('Sleeping %ds...' % sleep_time)
            time.sleep(sleep_time)
            continue

        try:
            pull_requests = repo_data['pullRequests']
        except KeyError:
            pull_requests = {
                'nodes': [],
                'pageInfo': {
                    'hasNextPage': False
                }
            }

        try:
            issues = repo_data['issues']
        except KeyError:
            issues = {
                'nodes': [],
                'pageInfo': {
                    'hasNextPage': False
                }
            }

        if pull_requests:
            transform(pull_requests['nodes'])
            output['pull_requests'].extend(pull_requests['nodes'])
            cur_prs.update([pr['number'] for pr in pull_requests['nodes']])

        if issues:
            transform(issues['nodes'])
            output['issues'].extend(issues['nodes'])
            cur_issues.update(
                [issue['number'] for issue in issues['nodes']]
            )

        fetch = (
            (pull_requests and pull_requests['pageInfo']['hasNextPage']) or
            (issues and issues['pageInfo']['hasNextPage'])
        )
        loop += 1

    extra_prs = list(prev_prs.difference(cur_prs))
    extra_issues = list(prev_issues.difference(cur_issues))

    for i, numbers in enumerate((extra_prs, extra_issues)):
        for chunk in chunker(numbers, 1):
            if i == 0:
                filters = [
                    '\n'.join(PULL_REQUEST % dict(
                        number=number,
                        states='[OPEN, CLOSED, MERGED]',
                        common=COMMON,
                        pr_common=PULL_REQUEST_COMMON,
                    ) for number in chunk),
                    ''
                ]
            else:
                filters = [
                    '',
                    '\n'.join(ISSUE % dict(
                        number=number,
                        states='[OPEN, CLOSED]',
                        common=COMMON
                    ) for number in chunk)
                ]

            while 1:
                if not any(filters):
                    break
                print('Fetching potentially closed issues/prs from previous run')
                if i == 0:
                    print('PRs=%r' % (list(chunk),))
                else:
                    print('Issues=%r' % (list(chunk),))

                try:
                    r = gql_s.post(
                        'https://api.github.com/graphql',
                        data=json.dumps({
                            'query': query % tuple(filters)
                        })
                    )
                    resp = r.json()
                except (HTTPError, ConnectionError, ValueError) as e:
                    continue
                else:
                    if 'errors' in resp:
                        types = [e.get('type') for e in resp['errors']]
                        if 'NOT_FOUND' in types:
                            break
                        print('Error: %r' % (resp['errors'],))
                        sleep_time = int(r.headers.get('Retry-After', 10))
                        print('Sleeping %ds...' % sleep_time)
                        time.sleep(sleep_time)
                        continue
                    try:
                        for k, v in resp['data']['repository'].items():
                            v = [v]
                            transform(v)
                            if k.startswith('issue_'):
                                output['issues'].extend(v)
                            elif k.startswith('pr_'):
                                output['pull_requests'].extend(v)
                    except Exception:
                        print('Unknown error: %r' % (resp,))
                        sleep_time = int(r.headers.get('Retry-After', 10))
                        print('Sleeping %ds...' % sleep_time)
                        time.sleep(sleep_time)
                        continue
                    break

    with open(os.path.join(output_dir, 'pull_requests.json'), 'w+') as f:
        json.dump(output['pull_requests'], f)
    del output['pull_requests']

    with open(os.path.join(output_dir, 'issues.json'), 'w+') as f:
        json.dump(output['issues'], f)
    del output['issues']

    r = gql_s.post(
        'https://api.github.com/graphql',
        data=json.dumps({
            'query': RATE_LIMIT
        })
    )

    print(r.text)


if __name__ == '__main__':
    with lock_file():
        main()
