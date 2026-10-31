import json
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.schemas import Alternative
from app.main import app
from app.services.github import (
    GITHUB_API_ORIGIN, LIST_PAGE_SIZE, MAX_IMPORTED_BYTES,
    GitHubIntegrationError, GitHubService,
    parse_public_repository_url,
)
from app.services.memory import DecisionMemory


REPOSITORY_URL = "https://github.com/acme/decora"


def repo_payload():
    return {
        "full_name": "acme/decora", "html_url": REPOSITORY_URL,
        "description": "Decision recovery", "default_branch": "main",
        "stargazers_count": 12, "open_issues_count": 8,
    }


def issue_payload(number=7, **overrides):
    payload = {
        "number": number, "title": "Choose Redis cache", "body": "The team accepts Redis cache.",
        "state": "closed", "user": {"login": "alice"},
        "created_at": "2026-01-02T10:00:00Z", "updated_at": "2026-01-03T10:00:00Z",
        "html_url": "https://github.com/acme/decora/issues/{}".format(number),
        "comments": 1,
    }
    payload.update(overrides)
    return payload


def comment_payload(comment_id, body, created_at, html_url, user=None, **extra):
    payload = {
        "id": comment_id, "body": body, "created_at": created_at,
        "html_url": html_url, "user": {"login": user} if user else None,
    }
    payload.update(extra)
    return payload


def transport_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_github_repository_url_validation_and_extraction():
    assert parse_public_repository_url(REPOSITORY_URL + "/") == (
        "acme", "decora", REPOSITORY_URL)


@pytest.mark.parametrize("value", [
    "http://github.com/acme/decora",
    "https://github.com.evil.test/acme/decora",
    "https://evil.test/acme/decora",
    "https://user@github.com/acme/decora",
    "https://github.com:443/acme/decora",
    "https://github.com/acme/decora/issues/1",
    "https://github.com/acme/decora?tab=issues",
    "https://github.com/acme/decora#readme",
    "https://github.com/acme/%2fetc",
    "https://github.com/acme/decora?",
    "https://github.com/acme/decora#",
    "https://github.com/acme/decora//",
    "https://github.com/acme/de\ncora",
    "https://github.com/acme/de\tcora",
    "https://github.com/acme/de\rcora",
    "https://github.com/acme/de\x00cora",
    "not a url",
])
def test_invalid_or_unsupported_repository_urls_are_rejected(value):
    with pytest.raises(GitHubIntegrationError) as error:
        parse_public_repository_url(value)
    assert error.value.status_code == 422


def test_repository_url_accepts_canonical_url_and_single_trailing_slash():
    assert parse_public_repository_url(REPOSITORY_URL) == (
        "acme", "decora", REPOSITORY_URL)
    assert parse_public_repository_url(REPOSITORY_URL + "/") == (
        "acme", "decora", REPOSITORY_URL)


def test_repository_metadata_uses_fixed_public_api_origin():
    requested = []

    def handler(request):
        requested.append(request)
        assert request.method == "GET"
        return httpx.Response(200, json=repo_payload())

    with GitHubService(client=transport_client(handler)) as service:
        result = service.repository_info(REPOSITORY_URL)

    assert result.full_name == "acme/decora"
    assert result.default_branch == "main"
    assert str(requested[0].url) == GITHUB_API_ORIGIN + "/repos/acme/decora"


def test_repository_names_are_case_insensitive_but_return_canonical_source_url():
    def handler(request):
        return httpx.Response(200, json=repo_payload())

    with GitHubService(client=transport_client(handler)) as service:
        result = service.repository_info("https://github.com/ACME/DECORA")
    assert result.full_name == "acme/decora"
    assert result.html_url == REPOSITORY_URL


def test_issue_listing_excludes_pull_requests_and_paginates():
    requests = []
    issue_page_1 = [issue_payload(number=i) for i in range(1, LIST_PAGE_SIZE + 1)]
    issue_page_2 = [issue_payload(number=LIST_PAGE_SIZE + 1)]
    issue_page_1[0]["pull_request"] = {"url": "https://api.github.com/repos/acme/decora/pulls/1"}

    def handler(request):
        requests.append(request)
        path = request.url.path
        if path == "/repos/acme/decora":
            return httpx.Response(200, json=repo_payload())
        if path == "/repos/acme/decora/issues":
            page = int(parse_qs(request.url.query.decode())["page"][0])
            return httpx.Response(200, json=issue_page_1 if page == 1 else issue_page_2)
        if path == "/repos/acme/decora/pulls":
            return httpx.Response(200, json=[{
                **issue_payload(number=44),
                "html_url": "https://github.com/acme/decora/pull/44",
                "draft": True,
            }])
        raise AssertionError("Unexpected GitHub route: {}".format(path))

    with GitHubService(client=transport_client(handler)) as service:
        result = service.list_discussions(REPOSITORY_URL)

    assert len(result.issues) == LIST_PAGE_SIZE
    assert all(item.kind == "issue" for item in result.issues)
    assert len(result.pull_requests) == 1
    assert result.pull_requests[0].kind == "pull_request"
    assert result.pull_requests[0].draft is True
    issue_pages = [request for request in requests if request.url.path.endswith("/issues")]
    assert [parse_qs(item.url.query.decode())["page"][0] for item in issue_pages] == ["1", "2"]
    assert all(request.method == "GET" for request in requests)


def test_pull_request_fetches_discussion_review_and_review_comment_data():
    requested_paths = []

    def handler(request):
        path = request.url.path
        requested_paths.append(path)
        if path == "/repos/acme/decora/pulls/7":
            return httpx.Response(200, json={
                **issue_payload(number=7),
                "html_url": "https://github.com/acme/decora/pull/7",
                "draft": False,
            })
        if path == "/repos/acme/decora/issues/7/comments":
            return httpx.Response(200, json=[comment_payload(
                101, "Discussion reply", "2026-01-04T10:00:00Z",
                "https://github.com/acme/decora/pull/7#issuecomment-101", "bob")])
        if path == "/repos/acme/decora/pulls/7/comments":
            return httpx.Response(200, json=[comment_payload(
                201, "Review inline comment", "2026-01-05T10:00:00Z",
                "https://github.com/acme/decora/pull/7#discussion_r201", "carol")])
        if path == "/repos/acme/decora/pulls/7/reviews":
            return httpx.Response(200, json=[{
                "id": 301, "body": "Review summary", "submitted_at": "2026-01-06T10:00:00Z",
                "user": {"login": "dave"},
                "_links": {"html": {"href": "https://github.com/acme/decora/pull/7#pullrequestreview-301"}},
            }])
        if path == "/repos/acme/decora":
            return httpx.Response(200, json=repo_payload())
        raise AssertionError("Unexpected route: {}".format(path))

    with GitHubService(client=transport_client(handler)) as service:
        detail = service.get_discussion(REPOSITORY_URL, "pull_request", 7)
        messages = service.to_messages(detail)

    assert set(requested_paths) == {
        "/repos/acme/decora/pulls/7", "/repos/acme/decora/issues/7/comments",
        "/repos/acme/decora/pulls/7/comments", "/repos/acme/decora/pulls/7/reviews",
        "/repos/acme/decora",
    }
    assert detail.discussion.kind == "pull_request"
    assert {comment.kind for comment in detail.comments} == {
        "issue_comment", "review_comment", "review",
    }
    assert [message.author for message in messages] == ["alice", "bob", "carol", "dave"]
    assert messages[0].message_id == "github:pull_request:7:opening"
    assert messages[1].message_id == "github:pull_request:7:issue_comment:101"
    assert messages[1].timestamp == "2026-01-04T10:00:00Z"
    assert messages[2].source_url == "https://github.com/acme/decora/pull/7#discussion_r201"
    assert [message.content for message in messages] == [
        "The team accepts Redis cache.", "Discussion reply", "Review inline comment", "Review summary",
    ]


def test_comment_retrieval_paginates_with_a_hard_page_limit():
    requested_pages = []

    def handler(request):
        path = request.url.path
        if path == "/repos/acme/decora/issues/7":
            return httpx.Response(200, json=issue_payload(body="Opening"))
        if path == "/repos/acme/decora/issues/7/comments":
            page = int(parse_qs(request.url.query.decode())["page"][0])
            requested_pages.append(page)
            count = 50 if page == 1 else 1
            start = 1000 if page == 1 else 1050
            return httpx.Response(200, json=[comment_payload(
                start + index, "comment", "2026-01-03T10:00:00Z",
                "https://github.com/acme/decora/issues/7#issuecomment-{}".format(start + index),
                "bob") for index in range(count)])
        if path == "/repos/acme/decora":
            return httpx.Response(200, json=repo_payload())
        raise AssertionError(path)

    with GitHubService(client=transport_client(handler)) as service:
        detail = service.get_discussion(REPOSITORY_URL, "issue", 7)

    assert len(detail.comments) == 51
    assert requested_pages == [1, 2]


def test_issue_conversion_preserves_missing_metadata_without_inventing_it():
    def handler(request):
        path = request.url.path
        if path == "/repos/acme/decora/issues/7":
            return httpx.Response(200, json=issue_payload(
                user=None, created_at=None, body="Original issue body"))
        if path == "/repos/acme/decora/issues/7/comments":
            return httpx.Response(200, json=[comment_payload(
                100, "A comment without author", "2026-01-03T10:00:00Z",
                "https://github.com/acme/decora/issues/7#issuecomment-100", None)])
        if path == "/repos/acme/decora":
            return httpx.Response(200, json=repo_payload())
        raise AssertionError(path)

    with GitHubService(client=transport_client(handler)) as service:
        detail = service.get_discussion(REPOSITORY_URL, "issue", 7)
        messages = service.to_messages(detail)

    assert detail.discussion.kind == "issue"
    opening = next(message for message in messages if message.message_id.endswith(":opening"))
    comment = next(message for message in messages if message.message_id.endswith(":100"))
    assert opening.author is None
    assert opening.timestamp is None
    assert opening.source_url == "https://github.com/acme/decora/issues/7"
    assert comment.author is None
    assert comment.content == "A comment without author"


@pytest.mark.parametrize("status,headers,body,expected,retry", [
    (429, {"Retry-After": "30"}, {"message": "slow down"}, 429, "30"),
    (403, {"X-RateLimit-Remaining": "0"}, {"message": "rate limit exceeded"}, 429, None),
    (403, {}, {"message": "Forbidden"}, 403, None),
    (404, {}, {"message": "Not Found"}, 404, None),
])
def test_github_status_and_rate_limit_mapping(status, headers, body, expected, retry):
    def handler(request):
        return httpx.Response(status, headers=headers, json=body)

    with GitHubService(client=transport_client(handler)) as service:
        with pytest.raises(GitHubIntegrationError) as error:
            service.repository_info(REPOSITORY_URL)

    assert error.value.status_code == expected
    assert error.value.retry_after == retry


def test_zero_remaining_on_successful_final_request_is_not_an_error():
    def handler(request):
        return httpx.Response(200, headers={"X-RateLimit-Remaining": "0"}, json=repo_payload())

    with GitHubService(client=transport_client(handler)) as service:
        result = service.repository_info(REPOSITORY_URL)
    assert result.full_name == "acme/decora"


def test_network_and_malformed_json_errors_are_clear():
    def network_error(request):
        raise httpx.ConnectError("connection failed", request=request)

    with GitHubService(client=transport_client(network_error)) as service:
        with pytest.raises(GitHubIntegrationError) as error:
            service.repository_info(REPOSITORY_URL)
    assert error.value.status_code == 502
    assert "connect" in error.value.detail.lower()

    def malformed(request):
        return httpx.Response(200, content=b"not json")

    with GitHubService(client=transport_client(malformed)) as service:
        with pytest.raises(GitHubIntegrationError, match="malformed JSON"):
            service.repository_info(REPOSITORY_URL)


def test_oversized_discussion_is_rejected_before_analysis():
    def handler(request):
        if request.url.path == "/repos/acme/decora/issues/7":
            return httpx.Response(200, json=issue_payload(body="x" * (MAX_IMPORTED_BYTES + 1)))
        if request.url.path == "/repos/acme/decora/issues/7/comments":
            return httpx.Response(200, json=[])
        if request.url.path == "/repos/acme/decora":
            return httpx.Response(200, json=repo_payload())
        raise AssertionError(request.url.path)

    with GitHubService(client=transport_client(handler)) as service:
        with pytest.raises(GitHubIntegrationError) as error:
            service.get_discussion(REPOSITORY_URL, "issue", 7)
    assert error.value.status_code == 413


def test_api_rejects_invalid_url_without_making_network_request(monkeypatch):
    from app.api import github as github_api
    requested = []

    def handler(request):
        requested.append(request)
        raise AssertionError("URL validation must happen before any request")

    monkeypatch.setattr(github_api, "GitHubService", lambda: GitHubService(
        client=transport_client(handler)))
    response = TestClient(app).get(
        "/api/github/repository", params={"repository_url": "https://evil.test/acme/decora"})

    assert response.status_code == 422
    assert requested == []


def test_api_returns_retry_after_for_rate_limit(monkeypatch):
    from app.api import github as github_api

    def handler(request):
        return httpx.Response(429, headers={"Retry-After": "20"}, json={"message": "rate limit"})

    monkeypatch.setattr(github_api, "GitHubService", lambda: GitHubService(
        client=transport_client(handler)))
    response = TestClient(app).get(
        "/api/github/repository", params={"repository_url": REPOSITORY_URL})

    assert response.status_code == 429
    assert response.headers["retry-after"] == "20"


def test_github_analysis_reuses_extractor_verification_memory_and_history(monkeypatch, tmp_path):
    monkeypatch.setenv("DECORA_DB_PATH", str(tmp_path / "github.db"))
    memory = DecisionMemory()
    prior = Alternative(
        decision_id="prior", proposal="Use Redis cache", status="rejected",
        outcome_basis="explicit_rejection", reason="memory pressure",
    )
    memory.save("Prior thread", "old body", [prior], "https://github.com/acme/decora/issues/2",
                "https://github.com/acme/decora")

    requests = []

    def github_handler(request):
        requests.append(request)
        path = request.url.path
        if path == "/repos/acme/decora/issues/7":
            return httpx.Response(200, json=issue_payload(
                body="The team accepts Redis cache."))
        if path == "/repos/acme/decora/issues/7/comments":
            return httpx.Response(200, json=[])
        if path == "/repos/acme/decora":
            return httpx.Response(200, json=repo_payload())
        raise AssertionError(path)

    from app.api import github as github_api
    monkeypatch.setattr(github_api, "GitHubService", lambda: GitHubService(
        client=transport_client(github_handler)))

    class MockProvider:
        model = "qwen3:8b"

        def generate(self, prompt):
            assert "untrusted source data" in prompt
            return json.dumps({"decisions": [{
                "proposal": "Use Redis cache", "status": "accepted",
                "outcome_basis": "explicit_acceptance",
                "outcome_evidence": [{
                    "segment_id": "github:issue:7:opening",
                    "quote": "The team accepts Redis cache.", "supports_claim": True,
                }],
            }]})

    from app.services.extractor import DecisionExtractor
    monkeypatch.setattr(github_api, "DecisionExtractor", lambda: DecisionExtractor(MockProvider()))
    client = TestClient(app)
    request = {"repository_url": REPOSITORY_URL, "kind": "issue", "number": 7}
    first = client.post("/api/github/analyze", json=request)
    second = client.post("/api/github/analyze", json=request)

    assert first.status_code == second.status_code == 200
    result = first.json()
    assert result["model"] == "qwen3:8b"
    assert result["decisions"][0]["verified"] is True
    assert result["decisions"][0]["outcome_evidence"][0]["source_url"] == result["discussion"]["html_url"]
    assert result["historical_decisions"][0]["status"] == "rejected"
    assert result["historical_decisions"][0]["potential_conflict"] is True
    assert first.json()["memory_decision_ids"] == second.json()["memory_decision_ids"]
    saved = client.get("/api/memory/search", params={"q": "Redis"}).json()
    imported = next(row for row in saved if row["source_reference"].endswith("/issues/7"))
    assert sum(row["source_reference"].endswith("/issues/7") for row in saved) == 1
    assert imported["source_repository"] == REPOSITORY_URL
    assert imported["evidence"][0]["author"] == "alice"
    assert all(request.method == "GET" for request in requests)


def test_github_analysis_request_validation():
    client = TestClient(app)
    assert client.post("/api/github/analyze", json={
        "repository_url": REPOSITORY_URL, "kind": "comment", "number": 3,
    }).status_code == 422
    assert client.post("/api/github/analyze", json={
        "repository_url": REPOSITORY_URL, "kind": "issue", "number": 0,
    }).status_code == 422


def test_unexpected_analysis_error_is_logged_without_exposing_details(monkeypatch, caplog):
    from app.api import github as github_api

    def fail_unexpectedly():
        raise RuntimeError("private internal diagnostic")

    monkeypatch.setattr(github_api, "GitHubService", fail_unexpectedly)
    response = TestClient(app).post("/api/github/analyze", json={
        "repository_url": REPOSITORY_URL, "kind": "issue", "number": 7,
    })

    assert response.status_code == 500
    assert "private internal diagnostic" not in response.text
    assert response.json()["detail"] == (
        "GitHub discussion analysis failed due to an unexpected server error.")
    assert "Unexpected error analyzing GitHub discussion" in caplog.text
    assert "private internal diagnostic" in caplog.text

