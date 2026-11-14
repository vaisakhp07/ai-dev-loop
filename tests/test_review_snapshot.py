import unittest
from unittest.mock import patch
from agent import review_snapshot, gh_json, pr_threads

@patch('agent.gh_json')
@patch('agent.pr_threads')
def test_review_snapshot(mock_pr_threads, mock_gh_json):
    # Test case: A CodeRabbit check run from the coderabbitai app for the current commit SHA is selected
    mock_gh_json.return_value = {
        'check_runs': [
            {'name': 'CodeRabbit', 'app': {'slug': 'coderabbitai'}, 'head_sha': 'HEAD', 'status': 'completed', 'conclusion': 'success'}
        ]
    }
    mock_pr_threads.return_value = [
        {'isResolved': False, 'isOutdated': False, 'comments': {'nodes': [{'body': 'coderabbit comment', 'author': {'login': 'coderabbit'}}]}}
    ]
    result = review_snapshot('owner', 'repo', 123, 'HEAD')
    assert result == ('clear', 'CodeRabbit check passed for current HEAD; no unresolved CodeRabbit threads')

    # Test case: An incomplete run returns 'pending'
    mock_gh_json.return_value = {
        'check_runs': [
            {'name': 'CodeRabbit', 'app': {'slug': 'coderabbitai'}, 'head_sha': 'HEAD', 'status': 'in_progress'}
        ]
    }
    result = review_snapshot('owner', 'repo', 123, 'HEAD')
    assert result == ('pending', 'CodeRabbit review running')

    # Test case: A completed run with 'failure', 'timed_out', or 'cancelled' returns 'blocked'
    for conclusion in ['failure', 'timed_out', 'cancelled']:
        mock_gh_json.return_value = {
            'check_runs': [
                {'name': 'CodeRabbit', 'app': {'slug': 'coderabbitai'}, 'head_sha': 'HEAD', 'status': 'completed', 'conclusion': conclusion}
            ]
        }
        result = review_snapshot('owner', 'repo', 123, 'HEAD')
        assert result == ('blocked', f'CodeRabbit: {conclusion}')

    # Test case: An unresolved outdated thread that contains a CodeRabbit comment is included
    mock_pr_threads.return_value = [
        {'isResolved': False, 'isOutdated': True, 'comments': {'nodes': [{'body': 'coderabbit comment', 'author': {'login': 'coderabbit'}}]}}
    ]
    result = review_snapshot('owner', 'repo', 123, 'HEAD')
    assert result == ('issues', 'coderabbit comment')

    # Test case: A resolved thread is excluded
    mock_pr_threads.return_value = [
        {'isResolved': True, 'isOutdated': False, 'comments': {'nodes': [{'body': 'coderabbit comment', 'author': {'login': 'coderabbit'}}]}}
    ]
    result = review_snapshot('owner', 'repo', 123, 'HEAD')
    assert result == ('clear', 'CodeRabbit check passed for current HEAD; no unresolved CodeRabbit threads')

    # Test case: The original CodeRabbit comment is retained after several later human replies
    mock_pr_threads.return_value = [
        {'isResolved': False, 'isOutdated': False, 'comments': {'nodes': [{'body': 'coderabbit comment', 'author': {'login': 'coderabbit'}}, {'body': 'human reply 1'}, {'body': 'human reply 2'}]}}
    ]
    result = review_snapshot('owner', 'repo', 123, 'HEAD')
    assert result == ('issues', 'coderabbit comment\nhuman reply 1\nhuman reply 2')

    # Test case: Wrong app/name/SHA is ignored
    mock_gh_json.return_value = {
        'check_runs': [
            {'name': 'CodeRabbit', 'app': {'slug': 'wrongapp'}, 'head_sha': 'HEAD', 'status': 'completed', 'conclusion': 'success'}
        ]
    }
    result = review_snapshot('owner', 'repo', 123, 'HEAD')
    assert result == ('pending', 'No CodeRabbit check for current HEAD')

    # Test case: Pending and failed conclusions are handled correctly
    for conclusion in ['pending', 'blocked']:
        mock_gh_json.return_value = {
            'check_runs': [
                {'name': 'CodeRabbit', 'app': {'slug': 'coderabbitai'}, 'head_sha': 'HEAD', 'status': 'completed', 'conclusion': conclusion}
            ]
        }
        result = review_snapshot('owner', 'repo', 123, 'HEAD')
        assert result == (conclusion, f'CodeRabbit: {conclusion}')

    # Test case: Outdated unresolved and resolved threads are handled correctly
    mock_pr_threads.return_value = [
        {'isResolved': False, 'isOutdated': True, 'comments': {'nodes': [{'body': 'coderabbit comment', 'author': {'login': 'coderabbit'}}]}}
    ]
    result = review_snapshot('owner', 'repo', 123, 'HEAD')
    assert result == ('issues', 'coderabbit comment')

    mock_pr_threads.return_value = [
        {'isResolved': True, 'isOutdated': False, 'comments': {'nodes': [{'body': 'coderabbit comment', 'author': {'login': 'coderabbit'}}]}}
    ]
    result = review_snapshot('owner', 'repo', 123, 'HEAD')
    assert result == ('clear', 'CodeRabbit check passed for current HEAD; no unresolved CodeRabbit threads')

    # Test case: Expect 'pending' for an unrecognized conclusion
    mock_gh_json.return_value = {
        'check_runs': [
            {'name': 'CodeRabbit', 'app': {'slug': 'coderabbitai'}, 'head_sha': 'HEAD', 'status': 'completed', 'conclusion': 'blocked'}
        ]
    }
    result = review_snapshot('owner', 'repo', 123, 'HEAD')
    assert result == ('pending', 'CodeRabbit: blocked')
