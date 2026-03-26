import hashlib
import uuid
from django.db import models


RESPONSE_FORMAT_INSTRUCTIONS = (
    "Line numbers: diff lines are prefixed with L<num> (new file) or OLD-L<num> (removed). "
    "Use the L-prefix number as line_number — never calculate it yourself.\n\n"
    "Output ONLY a JSON array, no other text. Empty array [] if no issues.\n"
    '[{"file_path":"path/to/file","line_number":42,"severity":"bug|security|perf",'
    '"title":"Short title","body":"Explanation","suggestion":"Better approach"}]'
)

EXISTING_ISSUES_CONTEXT = (
    "\n\nRe-review: keep ALL previous issues that still exist (same title + file_path). "
    "Omit only if fixed/removed. Add new issues with new titles.\n\n"
    "Previous issues:\n{existing_issues_json}\n"
)

DEFAULT_REVIEW_PROMPT = (
    "Expert code reviewer. Input: PR description then annotated diff.\n\n"
    "Review all changed files for correctness, reliability, security only. Skip style/formatting.\n\n"
    "Priority: 1) Bugs — logic errors, off-by-one, error swallowing, dead code, race conditions, "
    "ORM misuse (N+1, missing prefetch_related) "
    "2) Quality — unused imports/vars, loose types, missing validation "
    "3) Security — permissions, secrets exposure, CSRF, SQL injection "
    "4) Perf — unnecessary queries, missing indexes\n\n"
    "Be specific. Suggest the fix.\n\n"
    + RESPONSE_FORMAT_INSTRUCTIONS
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
