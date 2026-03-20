from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.urls import reverse

from .models import PullRequest, Issue, DraftComment
from . import services
from .forms import CreateReviewForm, UpdateStatusForm, IssueStatusForm, DraftCommentForm


class ServiceTests(TestCase):
    def setUp(self):
        self.review = PullRequest.objects.create(repo="acme/app", pr_number=42, status="pending")
        self.issue = Issue.objects.create(
            review=self.review,
            file_path="src/main.py",
            line_number=10,
            severity="bug",
            title="Test bug",
            body="A test bug",
            suggestion="Fix it",
            status="pending",
        )

    def test_get_reviews_returns_queryset_with_annotation(self):
        reviews = services.get_reviews()
        self.assertEqual(reviews.count(), 1)
        self.assertEqual(reviews.first().issue_count, 1)

    def test_get_reviews_ordered_by_created_at_desc(self):
        PullRequest.objects.create(repo="acme/app", pr_number=43, status="complete")
        reviews = list(services.get_reviews())
        self.assertEqual(reviews[0].pr_number, 43)

    def test_get_review_returns_review(self):
        review = services.get_review(self.review.id)
        self.assertEqual(review.pr_number, 42)

    def test_get_review_404(self):
        from django.http import Http404
        import uuid

        with self.assertRaises(Http404):
            services.get_review(uuid.uuid4())

    def test_save_review(self):
        review = services.save_review("acme/app", 99)
        self.assertEqual(review.pr_number, 99)
        self.assertEqual(review.status, "pending")
        self.assertEqual(review.repo, "acme/app")

    def test_save_review_with_prompt(self):
        review = services.save_review("acme/app", 99, review_prompt="Custom prompt")
        self.assertEqual(review.review_prompt, "Custom prompt")

    def test_update_review_status(self):
        services.update_review_status(self.review.id, "complete")
        self.review.refresh_from_db()
        self.assertEqual(self.review.status, "complete")

    def test_delete_review(self):
        services.delete_review(self.review.id)
        self.assertEqual(PullRequest.objects.count(), 0)

    def test_get_issues_for_review(self):
        issues = services.get_issues_for_review(self.review.id)
        self.assertEqual(issues.count(), 1)

    def test_get_issue(self):
        issue = services.get_issue(self.issue.id)
        self.assertEqual(issue.title, "Test bug")

    def test_save_issues_bulk(self):
        data = [
            {
                "file_path": "a.py",
                "line_number": 1,
                "severity": "style",
                "title": "T1",
                "body": "B1",
                "suggestion": "S1",
                "status": "pending",
            },
            {
                "file_path": "b.py",
                "line_number": 2,
                "severity": "bug",
                "title": "T2",
                "body": "B2",
                "suggestion": "S2",
                "status": "pending",
            },
        ]
        created = services.save_issues(self.review.id, data)
        self.assertEqual(len(created), 2)

    def test_update_issue_status(self):
        services.update_issue_status(self.issue.id, "approved")
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.status, "approved")

    def test_save_comment_draft(self):
        comment = services.save_comment_draft(self.issue.id, "Nice catch")
        self.assertEqual(comment.body, "Nice catch")
        self.assertFalse(comment.posted)

    def test_get_comment(self):
        comment = DraftComment.objects.create(issue=self.issue, body="Test")
        fetched = services.get_comment(comment.id)
        self.assertEqual(fetched.body, "Test")

    def test_update_comment(self):
        comment = DraftComment.objects.create(issue=self.issue, body="Old")
        services.update_comment(comment.id, "New")
        comment.refresh_from_db()
        self.assertEqual(comment.body, "New")

    def test_add_comment_to_github_pr(self):
        comment = DraftComment.objects.create(
            issue=self.issue, body="Test", posted=False
        )
        services.add_comment_to_github_pr(comment.id, "gh-123")
        comment.refresh_from_db()
        self.assertTrue(comment.posted)
        self.assertEqual(comment.github_comment_id, "gh-123")


class ParseReviewResponseTests(TestCase):
    def test_parse_valid_json(self):
        text = '[{"file_path": "a.py", "line_number": 1, "severity": "bug", "title": "T", "body": "B", "suggestion": "S"}]'
        result = services.parse_review_response(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["file_path"], "a.py")

    def test_parse_json_with_surrounding_text(self):
        text = 'Here are the issues:\n[{"file_path": "a.py", "line_number": 1}]\nDone.'
        result = services.parse_review_response(text)
        self.assertEqual(len(result), 1)

    def test_parse_no_json_raises(self):
        with self.assertRaises(ValueError):
            services.parse_review_response("No issues found.")


class RunPrReviewTests(TestCase):
    @patch("reviews.services.analyze_with_claude")
    @patch("reviews.services.fetch_pr_data")
    def test_run_pr_review_success(self, mock_fetch, mock_claude):
        mock_fetch.return_value = "PR data"
        mock_claude.return_value = (
            '[{"file_path": "x.py", "line_number": 5, "severity": "bug",'
            ' "title": "Bad code", "body": "Explanation", "suggestion": "Fix"}]'
        )
        review = PullRequest.objects.create(repo="acme/app", pr_number=1, status="pending")
        services.run_pr_review(review.id)

        review.refresh_from_db()
        self.assertEqual(review.status, "complete")
        self.assertEqual(review.issues.count(), 1)
        self.assertEqual(review.issues.first().title, "Bad code")

    @patch("reviews.services.fetch_pr_data")
    def test_run_pr_review_fetch_error(self, mock_fetch):
        mock_fetch.side_effect = RuntimeError("gh failed")
        review = PullRequest.objects.create(repo="acme/app", pr_number=1, status="pending")
        services.run_pr_review(review.id)

        review.refresh_from_db()
        self.assertEqual(review.status, "error")
        self.assertIn("gh failed", review.error_message)

    @patch("reviews.services.analyze_with_claude")
    @patch("reviews.services.fetch_pr_data")
    def test_run_pr_review_invalid_severity_defaults_to_style(self, mock_fetch, mock_claude):
        mock_fetch.return_value = "data"
        mock_claude.return_value = (
            '[{"file_path": "x.py", "line_number": 1, "severity": "critical",'
            ' "title": "T", "body": "B", "suggestion": "S"}]'
        )
        review = PullRequest.objects.create(repo="acme/app", pr_number=1, status="pending")
        services.run_pr_review(review.id)

        issue = review.issues.first()
        self.assertEqual(issue.severity, "style")


class ViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.review = PullRequest.objects.create(repo="acme/app", pr_number=42, status="pending")
        self.issue = Issue.objects.create(
            review=self.review,
            file_path="src/main.py",
            line_number=10,
            severity="bug",
            title="Test bug",
            body="A test bug",
            suggestion="Fix it",
            status="pending",
        )

    def test_index(self):
        response = self.client.get(reverse("reviews:index"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reviews/dashboard.html")
        self.assertContains(response, "#42")

    def test_create_review_get(self):
        response = self.client.get(reverse("reviews:create"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reviews/create.html")

    @patch("reviews.services.run_pr_review")
    def test_create_review_post_starts_background(self, mock_run):
        response = self.client.post(reverse("reviews:create"), {"repo": "acme/app", "pr_number": 99})
        review = PullRequest.objects.get(pr_number=99)
        self.assertRedirects(response, reverse("reviews:show", args=[review.id]))

    def test_show_review(self):
        response = self.client.get(reverse("reviews:show", args=[self.review.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reviews/show.html")
        self.assertContains(response, "#42")

    def test_show_review_analyzing_message(self):
        self.review.status = "analyzing"
        self.review.save()
        response = self.client.get(reverse("reviews:show", args=[self.review.id]))
        self.assertContains(response, "Claude is analyzing")

    def test_show_review_error_message(self):
        self.review.status = "error"
        self.review.error_message = "Something went wrong"
        self.review.save()
        response = self.client.get(reverse("reviews:show", args=[self.review.id]))
        self.assertContains(response, "Something went wrong")

    def test_delete_review(self):
        response = self.client.post(reverse("reviews:delete", args=[self.review.id]))
        self.assertRedirects(response, reverse("reviews:index"))
        self.assertEqual(PullRequest.objects.count(), 0)

    def test_delete_review_get_not_allowed(self):
        response = self.client.get(reverse("reviews:delete", args=[self.review.id]))
        self.assertEqual(response.status_code, 405)

    def test_update_status(self):
        response = self.client.post(
            reverse("reviews:update_status", args=[self.review.id]),
            {"status": "complete"},
        )
        self.assertRedirects(response, reverse("reviews:show", args=[self.review.id]))
        self.review.refresh_from_db()
        self.assertEqual(self.review.status, "complete")

    def test_review_issues(self):
        response = self.client.get(reverse("reviews:issues", args=[self.review.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reviews/issues.html")

    def test_show_issue(self):
        response = self.client.get(reverse("reviews:issue_detail", args=[self.issue.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reviews/issue_detail.html")
        self.assertContains(response, "Test bug")

    def test_update_issue_status(self):
        response = self.client.post(
            reverse("reviews:issue_update_status", args=[self.issue.id]),
            {"status": "approved"},
        )
        self.assertRedirects(response, reverse("reviews:issue_detail", args=[self.issue.id]))
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.status, "approved")

    def test_create_comment(self):
        response = self.client.post(
            reverse("reviews:create_comment", args=[self.issue.id]),
            {"body": "A comment"},
        )
        self.assertRedirects(response, reverse("reviews:issue_detail", args=[self.issue.id]))
        self.assertEqual(DraftComment.objects.count(), 1)

    def test_edit_comment_get(self):
        comment = DraftComment.objects.create(issue=self.issue, body="Draft text")
        response = self.client.get(reverse("reviews:edit_comment", args=[comment.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reviews/edit_comment.html")
        self.assertContains(response, "Draft text")

    def test_edit_comment_post(self):
        comment = DraftComment.objects.create(issue=self.issue, body="Old")
        response = self.client.post(
            reverse("reviews:edit_comment", args=[comment.id]),
            {"body": "Updated"},
        )
        self.assertRedirects(response, reverse("reviews:issue_detail", args=[self.issue.id]))
        comment.refresh_from_db()
        self.assertEqual(comment.body, "Updated")

    @patch("reviews.services.post_comment_to_github")
    def test_post_comment_success(self, mock_post):
        mock_post.return_value = "https://github.com/comment/1"
        comment = DraftComment.objects.create(issue=self.issue, body="Post me")
        response = self.client.post(reverse("reviews:post_comment", args=[comment.id]))
        self.assertRedirects(response, reverse("reviews:issue_detail", args=[self.issue.id]))
        comment.refresh_from_db()
        self.assertTrue(comment.posted)

    @patch("reviews.services.post_comment_to_github")
    def test_post_comment_failure(self, mock_post):
        mock_post.side_effect = RuntimeError("gh failed")
        comment = DraftComment.objects.create(issue=self.issue, body="Post me")
        response = self.client.post(reverse("reviews:post_comment", args=[comment.id]))
        self.assertRedirects(response, reverse("reviews:issue_detail", args=[self.issue.id]))
        comment.refresh_from_db()
        self.assertFalse(comment.posted)

    def test_post_comment_get_not_allowed(self):
        comment = DraftComment.objects.create(issue=self.issue, body="Post me")
        response = self.client.get(reverse("reviews:post_comment", args=[comment.id]))
        self.assertEqual(response.status_code, 405)

    def test_poll_status(self):
        response = self.client.get(reverse("reviews:poll_status", args=[self.review.id]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["issue_count"], 1)

    def test_poll_status_analyzing(self):
        self.review.status = "analyzing"
        self.review.save()
        response = self.client.get(reverse("reviews:poll_status", args=[self.review.id]))
        data = response.json()
        self.assertEqual(data["status"], "analyzing")


class FormTests(TestCase):
    def test_create_review_form_valid(self):
        form = CreateReviewForm(data={"repo": "acme/app", "pr_number": 42})
        self.assertTrue(form.is_valid())

    def test_create_review_form_with_prompt(self):
        form = CreateReviewForm(data={"repo": "acme/app", "pr_number": 42, "review_prompt": "Check for bugs"})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["review_prompt"], "Check for bugs")

    def test_create_review_form_invalid_zero(self):
        form = CreateReviewForm(data={"repo": "acme/app", "pr_number": 0})
        self.assertFalse(form.is_valid())

    def test_create_review_form_invalid_empty(self):
        form = CreateReviewForm(data={})
        self.assertFalse(form.is_valid())

    def test_create_review_form_missing_repo(self):
        form = CreateReviewForm(data={"pr_number": 42})
        self.assertFalse(form.is_valid())

    def test_update_status_form_valid(self):
        form = UpdateStatusForm(data={"status": "complete"})
        self.assertTrue(form.is_valid())

    def test_update_status_form_invalid(self):
        form = UpdateStatusForm(data={"status": "invalid"})
        self.assertFalse(form.is_valid())

    def test_issue_status_form_valid(self):
        form = IssueStatusForm(data={"status": "approved"})
        self.assertTrue(form.is_valid())

    def test_issue_status_form_invalid(self):
        form = IssueStatusForm(data={"status": "pending"})
        self.assertFalse(form.is_valid())

    def test_draft_comment_form_valid(self):
        form = DraftCommentForm(data={"body": "Hello"})
        self.assertTrue(form.is_valid())

    def test_draft_comment_form_invalid(self):
        form = DraftCommentForm(data={"body": ""})
        self.assertFalse(form.is_valid())
