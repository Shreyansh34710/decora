import json
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from app.core.schemas import (
    DiscussionMessage, GitHubDiscussionComment, GitHubDiscussionDetail,
    GitHubDiscussionKind, GitHubDiscussionListing, GitHubDiscussionSummary,
    GitHubRepositoryInfo,
)


GITHUB_API_ORIGIN = "https://api.github.com"
HTTP_TIMEOUT_SECONDS = 10.0
LIST_PAGE_SIZE = 25
MAX_LIST_RESULTS = 100
MAX_LIST_PAGES = 4
COMMENT_PAGE_SIZE = 50
MAX_COMMENTS_PER_KIND = 100
MAX_COMMENT_PAGES = 2
MAX_IMPORTED_BYTES = 512 * 1024
MAX_API_RESPONSE_BYTES = 2 * 1024 * 1024

_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class GitHubIntegrationError(Exception):
    def __init__(self, status_code: int, detail: str, retry_after: Optional[str] = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.retry_after = retry_after


def parse_public_repository_url(value: str) -> Tuple[str, str, str]:
    """Validate a public github.com repository URL; return owner, repo, canonical URL."""
    if not isinstance(value, str) or not value or len(value) > 500:
        raise GitHubIntegrationError(422, "Enter a valid public GitHub repository URL.")
    # urlsplit strips some control characters while parsing, so reject them
    # before parsing to avoid accepting a different URL than the user supplied.
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise GitHubIntegrationError(422, "Enter a valid public GitHub repository URL.")
    # urlsplit exposes only non-empty query/fragment values; reject delimiters
    # themselves as well so URLs ending in '?' or '#' are not normalized in.
    if "?" in value or "#" in value:
        raise GitHubIntegrationError(
            422, "Only public https://github.com/{owner}/{repository} URLs are supported.")
    try:
        parsed = urlsplit(value.strip())
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise GitHubIntegrationError(422, "Enter a valid public GitHub repository URL.") from error
    if (parsed.scheme.lower() != "https" or hostname is None
            or hostname.lower() != "github.com" or parsed.username or parsed.password
            or port is not None or parsed.query or parsed.fragment):
        raise GitHubIntegrationError(
            422, "Only public https://github.com/{owner}/{repository} URLs are supported.")
    if len(parsed.path) - len(parsed.path.rstrip("/")) > 1:
        raise GitHubIntegrationError(
            422, "Use a repository URL in the form https://github.com/{owner}/{repository}.")
    path = parsed.path.rstrip("/")
    parts = path.split("/")
    if len(parts) != 3 or parts[0] != "":
        raise GitHubIntegrationError(
            422, "Use a repository URL in the form https://github.com/{owner}/{repository}.")
    owner, repository = parts[1:]
    if (not _OWNER_PATTERN.fullmatch(owner) or not _REPOSITORY_PATTERN.fullmatch(repository)
            or repository in (".", "..")):
        raise GitHubIntegrationError(422, "The GitHub owner or repository name is invalid.")
    canonical = "https://github.com/{}/{}".format(owner, repository)
    return owner, repository, canonical


class GitHubService:
    """Read-only, bounded client for public GitHub REST endpoints."""

    def __init__(self, client: Optional[httpx.Client] = None,
                 timeout: float = HTTP_TIMEOUT_SECONDS):
        self._owns_client = client is None
        self.timeout = timeout
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=False)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._owns_client:
            self.client.close()

    @staticmethod
    def _coordinates(repository_url: str) -> Tuple[str, str, str]:
        return parse_public_repository_url(repository_url)

    @staticmethod
    def _safe_web_url(value, owner: str, repository: str,
                      expected_suffix: Optional[str] = None) -> Optional[str]:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError:
            return None
        prefix = "/{}/{}".format(owner, repository).casefold()
        path = parsed.path.rstrip("/")
        repository_or_child = path.casefold() == prefix or path.casefold().startswith(prefix + "/")
        if (parsed.scheme.lower() != "https" or parsed.hostname is None
                or parsed.hostname.lower() != "github.com" or parsed.username
                or parsed.password or port is not None or parsed.query
                or not repository_or_child):
            return None
        if expected_suffix is not None and path.casefold() != (prefix + expected_suffix).casefold():
            return None
        return value

    @staticmethod
    def _rate_limit(status_code: int, headers, data) -> Tuple[bool, Optional[str]]:
        message = ""
        if isinstance(data, dict) and isinstance(data.get("message"), str):
            message = data["message"].lower()
        retry_after = headers.get("Retry-After")
        remaining = headers.get("X-RateLimit-Remaining")
        limited = status_code == 429 or (
            status_code == 403
            and (remaining == "0" or retry_after is not None or "rate limit" in message))
        if limited:
            if not retry_after and headers.get("X-RateLimit-Reset"):
                try:
                    seconds = max(0, int(headers["X-RateLimit-Reset"])
                                  - int(datetime.now(timezone.utc).timestamp()))
                    retry_after = str(seconds)
                except ValueError:
                    retry_after = None
            return True, retry_after
        return False, None

    def _get(self, path: str, params: Optional[dict] = None):
        # `path` is always assembled internally from validated names and fixed route templates.
        try:
            with self.client.stream(
                    "GET", GITHUB_API_ORIGIN + path, params=params,
                    headers={
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                        "User-Agent": "Decora-read-only-importer",
                    }, timeout=self.timeout) as response:
                response_body = bytearray()
                for chunk in response.iter_bytes():
                    if len(response_body) + len(chunk) > MAX_API_RESPONSE_BYTES:
                        raise GitHubIntegrationError(
                            502, "GitHub returned an API response that exceeds the import limit.")
                    response_body.extend(chunk)
                status_code = response.status_code
                headers = response.headers
        except httpx.TimeoutException as error:
            raise GitHubIntegrationError(504, "GitHub request timed out. Please retry.") from error
        except httpx.RequestError as error:
            raise GitHubIntegrationError(502, "Could not connect to GitHub.") from error

        try:
            data = json.loads(response_body) if response_body else None
        except (TypeError, ValueError) as error:
            if 200 <= status_code < 300:
                raise GitHubIntegrationError(502, "GitHub returned malformed JSON.") from error
            data = None

        rate_limited, retry_after = self._rate_limit(status_code, headers, data)
        if rate_limited:
            detail = "GitHub rate limit reached. Wait before retrying."
            raise GitHubIntegrationError(429, detail, retry_after)
        if status_code == 404:
            raise GitHubIntegrationError(404, "The public GitHub repository or discussion was not found.")
        if status_code == 403:
            raise GitHubIntegrationError(403, "GitHub denied this public API request.")
        if status_code >= 500:
            raise GitHubIntegrationError(502, "GitHub is temporarily unavailable.")
        if status_code < 200 or status_code >= 300:
            raise GitHubIntegrationError(502, "GitHub returned an unexpected API status.")
        return data

    @staticmethod
    def _object(data, label: str) -> dict:
        if not isinstance(data, dict):
            raise GitHubIntegrationError(502, "GitHub returned malformed {} data.".format(label))
        return data

    def repository_info(self, repository_url: str) -> GitHubRepositoryInfo:
        owner, repository, _ = self._coordinates(repository_url)
        data = self._object(self._get("/repos/{}/{}".format(owner, repository)), "repository")
        if str(data.get("full_name", "")).casefold() != "{}/{}".format(owner, repository).casefold():
            raise GitHubIntegrationError(502, "GitHub returned repository data for a different repository.")
        repository_html_url = self._safe_web_url(
            data.get("html_url"), owner, repository, expected_suffix="")
        if not repository_html_url:
            raise GitHubIntegrationError(502, "GitHub returned an invalid repository URL.")
        try:
            return GitHubRepositoryInfo(
                full_name=data["full_name"], html_url=repository_html_url,
                description=data.get("description"), default_branch=data.get("default_branch"),
                stargazers_count=data.get("stargazers_count", 0),
                open_issues_count=data.get("open_issues_count", 0),
            )
        except (KeyError, ValidationError, TypeError) as error:
            raise GitHubIntegrationError(502, "GitHub returned invalid repository metadata.") from error

    @staticmethod
    def _author(data) -> Optional[str]:
        if data is None:
            return None
        if not isinstance(data, dict):
            raise GitHubIntegrationError(502, "GitHub returned malformed author data.")
        login = data.get("login")
        if login is not None and not isinstance(login, str):
            raise GitHubIntegrationError(502, "GitHub returned malformed author data.")
        return login

    @staticmethod
    def _optional_string(data: dict, key: str, label: str) -> Optional[str]:
        value = data.get(key)
        if value is not None and not isinstance(value, str):
            raise GitHubIntegrationError(502, "GitHub returned malformed {} data.".format(label))
        return value

    def _summary(self, data, kind: GitHubDiscussionKind, owner: str,
                 repository: str, include_body: bool = True) -> GitHubDiscussionSummary:
        data = self._object(data, "discussion")
        try:
            number = data["number"]
            title = data["title"]
            if not isinstance(number, int) or number < 1 or not isinstance(title, str):
                raise ValueError("invalid number/title")
            suffix = "/issues/{}".format(number) if kind == "issue" else "/pull/{}".format(number)
            url = self._safe_web_url(data.get("html_url"), owner, repository, suffix)
            if not url:
                raise ValueError("invalid discussion url")
            body = self._optional_string(data, "body", "discussion body") if include_body else None
            state = self._optional_string(data, "state", "discussion state")
            created_at = self._optional_string(data, "created_at", "discussion timestamp")
            updated_at = self._optional_string(data, "updated_at", "discussion timestamp")
            comments = data.get("comments", 0)
            if not isinstance(comments, int) or comments < 0:
                raise ValueError("invalid comment count")
            draft = data.get("draft") if kind == "pull_request" else None
            if draft is not None and not isinstance(draft, bool):
                raise ValueError("invalid draft state")
            return GitHubDiscussionSummary(
                kind=kind, number=number, title=title, body=body, state=state,
                author=self._author(data.get("user")), created_at=created_at,
                updated_at=updated_at, html_url=url, comments_count=comments, draft=draft,
            )
        except (KeyError, ValidationError, TypeError, ValueError) as error:
            raise GitHubIntegrationError(502, "GitHub returned malformed discussion data.") from error

    def _paginate(self, path: str, page_size: int, max_results: int,
                  max_pages: int, params: Optional[dict] = None) -> list:
        collected = []
        for page in range(1, max_pages + 1):
            request_params = dict(params or {})
            request_params.update({"per_page": page_size, "page": page})
            data = self._get(path, request_params)
            if not isinstance(data, list):
                raise GitHubIntegrationError(502, "GitHub returned malformed paginated data.")
            collected.extend(data[:max_results - len(collected)])
            if len(data) < page_size or len(collected) >= max_results:
                break
        return collected

    def list_discussions(self, repository_url: str) -> GitHubDiscussionListing:
        owner, repository, _ = self._coordinates(repository_url)
        info = self.repository_info(repository_url)
        issues_path = "/repos/{}/{}/issues".format(owner, repository)
        pulls_path = "/repos/{}/{}/pulls".format(owner, repository)
        issue_data = self._paginate(
            issues_path, LIST_PAGE_SIZE, MAX_LIST_RESULTS, MAX_LIST_PAGES,
            params={"state": "all", "sort": "updated", "direction": "desc"},
        )
        pull_data = self._paginate(
            pulls_path, LIST_PAGE_SIZE, MAX_LIST_RESULTS, MAX_LIST_PAGES,
            params={"state": "all", "sort": "updated", "direction": "desc"},
        )
        issues = []
        for item in issue_data:
            item = self._object(item, "issue")
            if "pull_request" not in item:
                issues.append(self._summary(item, "issue", owner, repository, include_body=False))
        pulls = [self._summary(item, "pull_request", owner, repository, include_body=False)
                 for item in pull_data]
        return GitHubDiscussionListing(repository=info, issues=issues, pull_requests=pulls)

    def _comments(self, path: str, owner: str, repository: str,
                  kind: str, created_field: str = "created_at") -> List[GitHubDiscussionComment]:
        data = self._paginate(path, COMMENT_PAGE_SIZE, MAX_COMMENTS_PER_KIND, MAX_COMMENT_PAGES)
        comments = []
        for item in data:
            item = self._object(item, "comment")
            comment_id = item.get("id")
            if not isinstance(comment_id, (int, str)) or not str(comment_id):
                raise GitHubIntegrationError(502, "GitHub returned a comment without a stable ID.")
            body = self._optional_string(item, "body", "comment body")
            created_at = item.get(created_field)
            if created_at is None and created_field == "created_at":
                created_at = item.get("submitted_at")
            if created_at is not None and not isinstance(created_at, str):
                raise GitHubIntegrationError(502, "GitHub returned malformed comment timestamp data.")
            raw_url = item.get("html_url")
            if raw_url is None and kind == "review":
                links = item.get("_links")
                raw_url = links.get("html", {}).get("href") if isinstance(links, dict) else None
            source_url = self._safe_web_url(raw_url, owner, repository)
            if raw_url is not None and source_url is None:
                raise GitHubIntegrationError(502, "GitHub returned an invalid comment source URL.")
            comments.append(GitHubDiscussionComment(
                id=str(comment_id), kind=kind, author=self._author(item.get("user")),
                body=body, created_at=created_at, html_url=source_url,
            ))
        return comments

    def get_discussion(self, repository_url: str, kind: GitHubDiscussionKind,
                       number: int) -> GitHubDiscussionDetail:
        owner, repository, _ = self._coordinates(repository_url)
        if kind not in ("issue", "pull_request") or not isinstance(number, int) or number < 1:
            raise GitHubIntegrationError(422, "Choose a valid issue or pull request number.")
        root = "/repos/{}/{}/{}".format(
            owner, repository, "issues" if kind == "issue" else "pulls")
        raw_discussion = self._get(root + "/{}".format(number))
        summary = self._summary(raw_discussion, kind, owner, repository)
        comments = self._comments(
            "/repos/{}/{}/issues/{}/comments".format(owner, repository, number),
            owner, repository, "issue_comment")
        if kind == "pull_request":
            comments.extend(self._comments(
                "/repos/{}/{}/pulls/{}/comments".format(owner, repository, number),
                owner, repository, "review_comment"))
            comments.extend(self._comments(
                "/repos/{}/{}/pulls/{}/reviews".format(owner, repository, number),
                owner, repository, "review"))
        detail = GitHubDiscussionDetail(
            repository=self.repository_info(repository_url),
            discussion=summary, comments=comments,
        )
        self._check_content_size(detail)
        return detail

    @staticmethod
    def _check_content_size(detail: GitHubDiscussionDetail):
        total = len((detail.discussion.body or "").encode("utf-8"))
        total += sum(len((comment.body or "").encode("utf-8")) for comment in detail.comments)
        if total > MAX_IMPORTED_BYTES:
            raise GitHubIntegrationError(
                413, "This discussion is too large to import (maximum 512 KiB of text).")

    @staticmethod
    def to_messages(detail: GitHubDiscussionDetail) -> List[DiscussionMessage]:
        summary = detail.discussion
        messages = []
        if summary.body:
            messages.append(DiscussionMessage(
                message_id="github:{}:{}:opening".format(summary.kind, summary.number),
                author=summary.author, timestamp=summary.created_at,
                content=summary.body, source_url=summary.html_url,
            ))
        for comment in detail.comments:
            if not comment.body:
                continue
            messages.append(DiscussionMessage(
                message_id="github:{}:{}:{}:{}".format(
                    summary.kind, summary.number, comment.kind, comment.id),
                author=comment.author, timestamp=comment.created_at,
                content=comment.body, source_url=comment.html_url,
            ))

        def sort_key(message):
            if message.timestamp:
                try:
                    value = datetime.fromisoformat(message.timestamp.replace("Z", "+00:00"))
                    return (0, value.timestamp(), message.message_id)
                except (ValueError, OverflowError):
                    raise GitHubIntegrationError(502, "GitHub returned an invalid message timestamp.")
            return (1, float("inf"), message.message_id)

        messages.sort(key=sort_key)
        total = sum(len(message.content.encode("utf-8")) for message in messages)
        if total > MAX_IMPORTED_BYTES:
            raise GitHubIntegrationError(
                413, "This discussion is too large to import (maximum 512 KiB of text).")
        return messages
