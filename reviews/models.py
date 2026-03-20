import hashlib
import uuid
from django.db import models


DEFAULT_REVIEW_PROMPT = (
    "Review this PR. The first part is the PR description/comments, the second part is the diff. "
    "Check for: use of any, console.log, bad aggregation patterns. "
    "Always suggest what is the better approach.\n\n"
    "Return your findings as a JSON array with this exact format and nothing else:\n"
    "[\n"
    '  {\n'
    '    "file_path": "path/to/file",\n'
    '    "line_number": 42,\n'
    '    "severity": "bug|security|perf",\n'
    '    "title": "Short descriptive title",\n'
    '    "body": "Detailed explanation of the issue",\n'
    '    "suggestion": "What the better approach would be"\n'
    '  }\n'
    "]\n"
    "Only output the JSON array, no other text."
)


class PullRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo = models.CharField(
        max_length=255,
        default="",
        help_text="GitHub repo in owner/name format, e.g. django/django",
    )
    pr_number = models.IntegerField()
    status = models.CharField(
        choices=[
            ("pending", "Pending"),
            ("analyzing", "Analyzing"),
            ("complete", "Complete"),
            ("error", "Error"),
        ],
        max_length=9,
    )
    review_prompt = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.repo} PR #{self.pr_number}"


class Issue(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    review = models.ForeignKey(
        PullRequest, on_delete=models.CASCADE, related_name="issues"
    )
    file_path = models.CharField(max_length=255)
    line_number = models.IntegerField()
    severity = models.CharField(
        choices=[
            ("bug", "Bug"),
            ("security", "Security"),
            ("style", "Style"),
            ("perf", "Performance"),
        ],
        max_length=8,
    )
    title = models.CharField(max_length=255)
    body = models.TextField()
    suggestion = models.TextField()
    status = models.CharField(
        choices=[
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("dismissed", "Dismissed"),
        ],
        max_length=9,
    )

    @property
    def github_diff_url(self):
        file_hash = hashlib.sha256(self.file_path.encode()).hexdigest()
        return (
            f"https://github.com/{self.review.repo}/pull/"
            f"{self.review.pr_number}/files#diff-{file_hash}R{self.line_number}"
        )

    def __str__(self):
        return self.title


class DraftComment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    issue = models.ForeignKey(
        Issue, on_delete=models.CASCADE, related_name="comments"
    )
    body = models.TextField()
    posted = models.BooleanField(default=False)
    github_comment_id = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"Comment on {self.issue.title}"
