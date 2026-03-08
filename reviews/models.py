import uuid
from django.db import models


class PullRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
    created_at = models.DateTimeField()


class Issue(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    review = models.ForeignKey(PullRequest, on_delete=models.CASCADE)
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
    body = models.CharField(max_length=255)
    suggestion = models.CharField(max_length=255)
    status = models.CharField(
        choices=[
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("dismissed", "Dismissed"),
        ],
        max_length=9,
    )


class DraftComment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE)
    body = models.CharField(max_length=255)
    posted = models.BooleanField()
    github_comment_id = models.CharField(max_length=255)
