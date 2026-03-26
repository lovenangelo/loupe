import json
import logging
import os
import re
import subprocess
from urllib.request import urlopen, Request

from django.db import close_old_connections
from django.db.models import Count
from django.shortcuts import get_object_or_404

from .models import (
    PullRequest, Issue, DraftComment, ChatMessage,
    DEFAULT_REVIEW_PROMPT, RESPONSE_FORMAT_INSTRUCTIONS, EXISTING_ISSUES_CONTEXT,
)

logger = logging.getLogger(__name__)

HOST_RELAY_URL = os.environ.get("HOST_RELAY_URL", "")
RELAY_AUTH_TOKEN = os.environ.get("RELAY_AUTH_TOKEN", "")


def _run_cmd(cmd, args, stdin_data=None, timeout=300):
    """Run a command locally or via host relay if inside Docker."""
    if HOST_RELAY_URL:
        payload = json.dumps({
            "cmd": cmd,
            "args": args,
            "stdin": stdin_data,
            "timeout": timeout,
        }).encode()
        headers = {"Content-Type": "application/json"}
        if RELAY_AUTH_TOKEN:
            headers["Authorization"] = f"Bearer {RELAY_AUTH_TOKEN}"
        req = Request(
            HOST_RELAY_URL,
            data=payload,
            headers=headers,
        )
        with urlopen(req, timeout=timeout + 10) as resp:
            result = json.loads(resp.read())
        if "error" in result:
            raise RuntimeError(result["error"])
        return result
    else:
        result = subprocess.run(
            [cmd] + args,
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }


# ---------------------------------------------------------------------------
# Review CRUD
# ---------------------------------------------------------------------------

def get_reviews():
    return (
        PullRequest.objects.annotate(issue_count=Count("issues"))
        .order_by("-created_at")
    )


def get_review(review_id):
    return get_object_or_404(
        PullRequest.objects.prefetch_related("issues"),
        pk=review_id,
    )


def save_review(repo, pr_number, review_prompt=""):
    return PullRequest.objects.create(
        repo=repo,
        pr_number=pr_number,
        status="pending",
        review_prompt=review_prompt,
    )


def update_review_status(review_id, status):
    review = get_object_or_404(PullRequest, pk=review_id)
    review.status = status
    review.save(update_fields=["status"])
    return review


def delete_review(review_id):
    review = get_object_or_404(PullRequest, pk=review_id)
    review.delete()


# ---------------------------------------------------------------------------
# Issue CRUD
# ---------------------------------------------------------------------------

def get_issues_for_review(review_id):
    return Issue.objects.filter(review_id=review_id).select_related("review").order_by("file_path", "line_number")


def get_issue(issue_id):
    return get_object_or_404(
        Issue.objects.select_related("review").prefetch_related("comments"),
        pk=issue_id,
    )


def save_issues(review_id, issues_data):
    review = get_object_or_404(PullRequest, pk=review_id)
    issues = [Issue(review=review, **data) for data in issues_data]
    return Issue.objects.bulk_create(issues)


def update_issue_status(issue_id, status):
    issue = get_object_or_404(Issue, pk=issue_id)
    issue.status = status
    issue.save(update_fields=["status"])
    return issue


# ---------------------------------------------------------------------------
# Comment CRUD
# ---------------------------------------------------------------------------

def save_comment_draft(issue_id, body):
    issue = get_object_or_404(Issue, pk=issue_id)
    return DraftComment.objects.create(issue=issue, body=body)


def get_comment(comment_id):
    return get_object_or_404(
        DraftComment.objects.select_related("issue__review"),
        pk=comment_id,
    )


def update_comment(comment_id, body):
    comment = get_object_or_404(DraftComment, pk=comment_id)
    comment.body = body
    comment.save(update_fields=["body"])
    return comment


def add_comment_to_github_pr(comment_id, github_comment_id):
    comment = get_object_or_404(DraftComment, pk=comment_id)
    comment.posted = True
    comment.github_comment_id = github_comment_id
    comment.save(update_fields=["posted", "github_comment_id"])
    return comment


# ---------------------------------------------------------------------------
# Claude + GitHub integration
# ---------------------------------------------------------------------------

def _annotate_diff(raw_diff):
    """Add real line numbers to each diff line so Claude doesn't miscalculate.

    Transforms unified diff lines like:
        +    new code
    Into:
        L42 +    new code

    Context and added lines get the new-file line number.
    Removed lines get the old-file line number prefixed with OLD-.
    """
    annotated = []
    new_line = 0
    old_line = 0
    hunk_re = re.compile(r'^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@')

    for line in raw_diff.splitlines():
        if line.startswith('diff --git') or line.startswith('index ') or \
           line.startswith('---') or line.startswith('+++'):
            annotated.append(line)
            continue

        hunk_match = hunk_re.match(line)
        if hunk_match:
            old_line = int(hunk_match.group(1))
            new_line = int(hunk_match.group(2))
            annotated.append(line)
            continue

        if line.startswith('+'):
            annotated.append(f"L{new_line} {line}")
            new_line += 1
        elif line.startswith('-'):
            annotated.append(f"OLD-L{old_line} {line}")
            old_line += 1
        else:
            # Context line — both counters advance
            annotated.append(f"L{new_line} {line}")
            old_line += 1
            new_line += 1

    return '\n'.join(annotated)


def fetch_pr_data(repo, pr_number):
    """Fetch PR description and annotated diff from GitHub CLI."""
    view_result = _run_cmd("gh", ["pr", "view", str(pr_number), "--repo", repo], timeout=60)
    if view_result["returncode"] != 0:
        raise RuntimeError(f"gh pr view failed: {view_result['stderr']}")
    diff_result = _run_cmd("gh", ["pr", "diff", str(pr_number), "--repo", repo], timeout=60)
    if diff_result["returncode"] != 0:
        raise RuntimeError(f"gh pr diff failed: {diff_result['stderr']}")
    annotated_diff = _annotate_diff(diff_result["stdout"])
    return view_result["stdout"] + "\n---\n" + annotated_diff


def analyze_with_claude(pr_data, prompt):
    """Send PR data to Claude CLI and get structured response."""
    result = _run_cmd("claude", ["-p", prompt], stdin_data=pr_data, timeout=300)
    if result["returncode"] != 0:
        raise RuntimeError(f"claude failed: {result['stderr']}")
    return result["stdout"]


def parse_review_response(text):
    """Extract JSON array of issues from Claude's response."""
    # Try to find a JSON array in the response
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if not match:
        raise ValueError("No JSON array found in Claude response")
    return json.loads(match.group())


VALID_SEVERITIES = {"bug", "security", "style", "perf"}


def _build_existing_issues_context(review):
    """Build a prompt section with existing issues so Claude stays consistent."""
    existing = list(review.issues.all().values(
        "file_path", "line_number", "severity", "title", "body", "suggestion",
    ))
    if not existing:
        return ""
    return EXISTING_ISSUES_CONTEXT.format(
        existing_issues_json=json.dumps(existing, indent=2),
    )


def _reconcile_issues(review, new_issues_data):
    """Match new Claude results against existing issues.

    - Existing issues that match (by title + file_path) are kept as-is.
    - Existing issues NOT in the new results are marked dismissed (resolved).
    - New issues not matching any existing one are created.
    """
    existing_issues = {
        (issue.title, issue.file_path): issue
        for issue in review.issues.all()
    }
    seen_keys = set()
    to_create = []

    for item in new_issues_data:
        severity = item.get("severity", "style")
        if severity not in VALID_SEVERITIES:
            severity = "style"
        title = item.get("title", "Untitled")[:255]
        file_path = item.get("file_path", "unknown")
        key = (title, file_path)
        seen_keys.add(key)

        if key in existing_issues:
            # Update existing issue in place (line number or details may change)
            issue = existing_issues[key]
            issue.line_number = item.get("line_number", 0)
            issue.severity = severity
            issue.body = item.get("body", "")
            issue.suggestion = item.get("suggestion", "")
            if issue.status == "dismissed":
                issue.status = "pending"
            issue.save()
        else:
            to_create.append(Issue(
                review=review,
                file_path=file_path,
                line_number=item.get("line_number", 0),
                severity=severity,
                title=title,
                body=item.get("body", ""),
                suggestion=item.get("suggestion", ""),
                status="pending",
            ))

    # Mark issues that Claude no longer reports as dismissed
    for key, issue in existing_issues.items():
        if key not in seen_keys and issue.status != "dismissed":
            issue.status = "dismissed"
            issue.save(update_fields=["status"])

    if to_create:
        Issue.objects.bulk_create(to_create)

    return len(seen_keys & set(existing_issues.keys())), len(to_create)


def run_pr_review(review_id):
    """Background task: fetch PR, analyze with Claude, save issues."""
    try:
        close_old_connections()
        review = PullRequest.objects.get(pk=review_id)
        review.status = "analyzing"
        review.save(update_fields=["status"])

        if review.review_prompt:
            prompt = review.review_prompt + "\n\n" + RESPONSE_FORMAT_INSTRUCTIONS
        else:
            prompt = DEFAULT_REVIEW_PROMPT

        # Include existing issues as context for consistency
        prompt += _build_existing_issues_context(review)

        pr_data = fetch_pr_data(review.repo, review.pr_number)
        response = analyze_with_claude(pr_data, prompt)
        issues_data = parse_review_response(response)

        is_rerun = review.issues.exists()

        if is_rerun:
            kept, created = _reconcile_issues(review, issues_data)
            logger.info(
                "Re-review %s: %d kept, %d new, resolved issues dismissed",
                review_id, kept, created,
            )
        else:
            issues = []
            for item in issues_data:
                severity = item.get("severity", "style")
                if severity not in VALID_SEVERITIES:
                    severity = "style"
                issues.append(Issue(
                    review=review,
                    file_path=item.get("file_path", "unknown"),
                    line_number=item.get("line_number", 0),
                    severity=severity,
                    title=item.get("title", "Untitled")[:255],
                    body=item.get("body", ""),
                    suggestion=item.get("suggestion", ""),
                    status="pending",
                ))
            Issue.objects.bulk_create(issues)
            logger.info("Review %s completed with %d issues", review_id, len(issues))

        review.status = "complete"
        review.save(update_fields=["status"])

    except Exception as e:
        logger.exception("Review %s failed", review_id)
        try:
            close_old_connections()
            review = PullRequest.objects.get(pk=review_id)
            review.status = "error"
            review.error_message = str(e)[:1000]
            review.save(update_fields=["status", "error_message"])
        except Exception:
            logger.exception("Failed to update review %s to error state", review_id)


def _get_pr_head_sha(repo, pr_number):
    """Get the latest commit SHA on the PR head branch."""
    result = _run_cmd("gh", [
        "pr", "view", str(pr_number), "--repo", repo,
        "--json", "headRefOid", "--jq", ".headRefOid",
    ], timeout=30)
    if result["returncode"] != 0:
        raise RuntimeError(f"Failed to get PR head SHA: {result['stderr']}")
    return result["stdout"].strip()


def post_comment_to_github(repo, pr_number, body, file_path, line_number):
    """Post a review comment on a specific file/line in a GitHub PR."""
    commit_id = _get_pr_head_sha(repo, pr_number)
    payload = json.dumps({
        "body": body,
        "commit_id": commit_id,
        "path": file_path,
        "line": line_number,
        "side": "RIGHT",
    })
    result = _run_cmd("gh", [
        "api", f"repos/{repo}/pulls/{pr_number}/comments",
        "--method", "POST",
        "--input", "-",
    ], stdin_data=payload, timeout=30)
    if result["returncode"] != 0:
        raise RuntimeError(f"gh api comment failed: {result['stderr']}")
    response = json.loads(result["stdout"])
    return str(response.get("id", ""))


# ---------------------------------------------------------------------------
# Issue Chat
# ---------------------------------------------------------------------------

def get_chat_messages(issue_id):
    return ChatMessage.objects.filter(issue_id=issue_id).order_by("created_at")


def send_chat_message(issue_id, user_message):
    """Save user message, send to Claude with issue context + history, save response."""
    issue = get_object_or_404(
        Issue.objects.select_related("review"),
        pk=issue_id,
    )

    ChatMessage.objects.create(issue=issue, role="user", content=user_message)

    # Build context: issue details + conversation history
    history = list(issue.chat_messages.all().values_list("role", "content"))
    conversation = "\n".join(f"{role}: {content}" for role, content in history)

    prompt = (
        f"You are helping a developer understand a code review issue.\n\n"
        f"Issue: {issue.title}\n"
        f"File: {issue.file_path}:{issue.line_number}\n"
        f"Severity: {issue.severity}\n"
        f"Description: {issue.body}\n"
        f"Suggestion: {issue.suggestion}\n\n"
        f"Conversation so far:\n{conversation}\n\n"
        f"Respond helpfully and concisely to the user's latest message."
    )

    result = _run_cmd("claude", ["-p", prompt], timeout=120)
    if result["returncode"] != 0:
        raise RuntimeError(f"claude failed: {result['stderr']}")

    assistant_content = result["stdout"].strip()
    msg = ChatMessage.objects.create(issue=issue, role="assistant", content=assistant_content)
    return msg
