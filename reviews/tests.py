from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.urls import reverse

from .models import PullRequest, Issue, DraftComment, ChatMessage
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
        services.update_issue_status(self.issue.id, "valid")
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.status, "valid")

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

def test_show_issue(self):
        response = self.client.get(reverse("reviews:issue_detail", args=[self.issue.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reviews/issue_detail.html")
        self.assertContains(response, "Test bug")

    def test_update_issue_status(self):
        response = self.client.post(
            reverse("reviews:issue_update_status", args=[self.issue.id]),
            {"status": "valid"},
        )
        self.assertRedirects(response, reverse("reviews:issue_detail", args=[self.issue.id]))
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.status, "valid")

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
        form = UpdateStatusForm(data={"status": "bogus"})
        self.assertFalse(form.is_valid())

    def test_issue_status_form_valid(self):
        form = IssueStatusForm(data={"status": "valid"})
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


class AnnotateDiffTests(TestCase):
    def test_annotate_added_lines(self):
        raw = (
            "diff --git a/foo.py b/foo.py\n"
            "index abc..def 100644\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,3 +1,4 @@\n"
            " existing\n"
            "+added\n"
            " more\n"
            " end\n"
        )
        result = services._annotate_diff(raw)
        lines = result.splitlines()
        # Header lines pass through unchanged
        self.assertTrue(lines[0].startswith("diff --git"))
        # Find annotated lines after the hunk header
        annotated = [l for l in lines if l.startswith("L") or l.startswith("OLD-L")]
        self.assertTrue(annotated[0].startswith("L1 "))
        self.assertIn("L2 +added", annotated[1])
        self.assertTrue(annotated[2].startswith("L3 "))

    def test_annotate_removed_lines(self):
        raw = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -5,3 +5,2 @@\n"
            " context\n"
            "-removed\n"
            " end\n"
        )
        result = services._annotate_diff(raw)
        annotated = [l for l in result.splitlines() if l.startswith("L") or l.startswith("OLD-L")]
        self.assertIn("OLD-L6 -removed", annotated[1])

    def test_annotate_hunk_start_numbers(self):
        raw = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -10,3 +20,3 @@\n"
            " line\n"
        )
        result = services._annotate_diff(raw)
        lines = result.splitlines()
        self.assertIn("L20 ", lines[4])

    def test_annotate_empty_diff(self):
        self.assertEqual(services._annotate_diff(""), "")


class ReconcileIssuesTests(TestCase):
    def setUp(self):
        self.review = PullRequest.objects.create(repo="acme/app", pr_number=42, status="complete")
        self.issue1 = Issue.objects.create(
            review=self.review, file_path="a.py", line_number=10,
            severity="bug", title="Bug one", body="B1", suggestion="S1", status="pending",
        )
        self.issue2 = Issue.objects.create(
            review=self.review, file_path="b.py", line_number=20,
            severity="security", title="Sec issue", body="B2", suggestion="S2", status="pending",
        )

    def test_matching_issues_kept(self):
        new_data = [
            {"file_path": "a.py", "line_number": 10, "severity": "bug",
             "title": "Bug one", "body": "B1 updated", "suggestion": "S1"},
        ]
        kept, created = services._reconcile_issues(self.review, new_data)
        self.assertEqual(kept, 1)
        self.assertEqual(created, 0)
        self.issue1.refresh_from_db()
        self.assertEqual(self.issue1.body, "B1 updated")

    def test_missing_issues_invalid(self):
        new_data = [
            {"file_path": "a.py", "line_number": 10, "severity": "bug",
             "title": "Bug one", "body": "B1", "suggestion": "S1"},
        ]
        services._reconcile_issues(self.review, new_data)
        self.issue2.refresh_from_db()
        self.assertEqual(self.issue2.status, "invalid")

    def test_new_issues_created(self):
        new_data = [
            {"file_path": "a.py", "line_number": 10, "severity": "bug",
             "title": "Bug one", "body": "B1", "suggestion": "S1"},
            {"file_path": "c.py", "line_number": 30, "severity": "perf",
             "title": "New issue", "body": "B3", "suggestion": "S3"},
        ]
        kept, created = services._reconcile_issues(self.review, new_data)
        self.assertEqual(kept, 1)
        self.assertEqual(created, 1)
        self.assertEqual(self.review.issues.count(), 3)

    def test_invalid_issue_reopened_on_match(self):
        self.issue1.status = "invalid"
        self.issue1.save()
        new_data = [
            {"file_path": "a.py", "line_number": 10, "severity": "bug",
             "title": "Bug one", "body": "B1", "suggestion": "S1"},
        ]
        services._reconcile_issues(self.review, new_data)
        self.issue1.refresh_from_db()
        self.assertEqual(self.issue1.status, "pending")

    def test_already_invalid_stays_invalid(self):
        self.issue1.status = "invalid"
        self.issue1.save()
        new_data = []  # Claude reports no issues
        services._reconcile_issues(self.review, new_data)
        self.issue1.refresh_from_db()
        self.assertEqual(self.issue1.status, "invalid")


class RerunReviewTests(TestCase):
    def setUp(self):
        self.review = PullRequest.objects.create(repo="acme/app", pr_number=42, status="complete")
        self.issue = Issue.objects.create(
            review=self.review, file_path="a.py", line_number=10,
            severity="bug", title="Existing", body="B", suggestion="S", status="pending",
        )

    @patch("reviews.services.analyze_with_claude")
    @patch("reviews.services.fetch_pr_data")
    def test_rerun_reconciles_issues(self, mock_fetch, mock_claude):
        mock_fetch.return_value = "PR data"
        mock_claude.return_value = (
            '[{"file_path": "a.py", "line_number": 10, "severity": "bug",'
            ' "title": "Existing", "body": "Updated body", "suggestion": "S"},'
            ' {"file_path": "new.py", "line_number": 5, "severity": "perf",'
            ' "title": "New issue", "body": "NB", "suggestion": "NS"}]'
        )
        services.run_pr_review(self.review.id)
        self.review.refresh_from_db()
        self.assertEqual(self.review.status, "complete")
        self.assertEqual(self.review.issues.count(), 2)
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.body, "Updated body")

    @patch("reviews.services.analyze_with_claude")
    @patch("reviews.services.fetch_pr_data")
    def test_rerun_includes_existing_issues_in_prompt(self, mock_fetch, mock_claude):
        mock_fetch.return_value = "PR data"
        mock_claude.return_value = '[]'
        services.run_pr_review(self.review.id)
        prompt_sent = mock_claude.call_args[0][1]
        self.assertIn("Existing", prompt_sent)
        self.assertIn("a.py", prompt_sent)


class RerunViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.review = PullRequest.objects.create(repo="acme/app", pr_number=42, status="complete")

    @patch("reviews.services.run_pr_review")
    def test_rerun_post(self, mock_run):
        response = self.client.post(reverse("reviews:rerun", args=[self.review.id]))
        self.assertRedirects(response, reverse("reviews:show", args=[self.review.id]))

    def test_rerun_get_not_allowed(self):
        response = self.client.get(reverse("reviews:rerun", args=[self.review.id]))
        self.assertEqual(response.status_code, 405)

    def test_rerun_while_analyzing(self):
        self.review.status = "analyzing"
        self.review.save()
        response = self.client.post(reverse("reviews:rerun", args=[self.review.id]))
        self.assertRedirects(response, reverse("reviews:show", args=[self.review.id]))


class InlineIssueStatusTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.review = PullRequest.objects.create(repo="acme/app", pr_number=42, status="complete")
        self.issue = Issue.objects.create(
            review=self.review, file_path="a.py", line_number=10,
            severity="bug", title="Bug", body="B", suggestion="S", status="pending",
        )

    def test_ajax_returns_json(self):
        response = self.client.post(
            reverse("reviews:issue_update_status", args=[self.issue.id]),
            {"status": "valid"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "valid")
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.status, "valid")

    def test_non_ajax_redirects(self):
        response = self.client.post(
            reverse("reviews:issue_update_status", args=[self.issue.id]),
            {"status": "invalid"},
        )
        self.assertRedirects(response, reverse("reviews:issue_detail", args=[self.issue.id]))


class ChatMessageTests(TestCase):
    def setUp(self):
        self.review = PullRequest.objects.create(repo="acme/app", pr_number=42, status="complete")
        self.issue = Issue.objects.create(
            review=self.review, file_path="a.py", line_number=10,
            severity="bug", title="Bug", body="Description", suggestion="Fix", status="pending",
        )

    def test_get_chat_messages_empty(self):
        messages = services.get_chat_messages(self.issue.id)
        self.assertEqual(messages.count(), 0)

    def test_get_chat_messages_ordered(self):
        ChatMessage.objects.create(issue=self.issue, role="user", content="First")
        ChatMessage.objects.create(issue=self.issue, role="assistant", content="Second")
        messages = list(services.get_chat_messages(self.issue.id))
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].content, "First")
        self.assertEqual(messages[1].content, "Second")

    @patch("reviews.services._run_cmd")
    def test_send_chat_message(self, mock_cmd):
        mock_cmd.return_value = {"returncode": 0, "stdout": "Here is my answer", "stderr": ""}
        reply = services.send_chat_message(self.issue.id, "Why is this a bug?")
        self.assertEqual(reply.role, "assistant")
        self.assertEqual(reply.content, "Here is my answer")
        # Should have 2 messages: user + assistant
        self.assertEqual(ChatMessage.objects.filter(issue=self.issue).count(), 2)
        user_msg = ChatMessage.objects.filter(issue=self.issue, role="user").first()
        self.assertEqual(user_msg.content, "Why is this a bug?")

    @patch("reviews.services._run_cmd")
    def test_send_chat_message_includes_context(self, mock_cmd):
        mock_cmd.return_value = {"returncode": 0, "stdout": "Answer", "stderr": ""}
        services.send_chat_message(self.issue.id, "Explain more")
        prompt = mock_cmd.call_args[0][1][1]  # second arg to _run_cmd is args list, [1] is prompt
        self.assertIn("Bug", prompt)
        self.assertIn("a.py", prompt)
        self.assertIn("Description", prompt)

    @patch("reviews.services._run_cmd")
    def test_send_chat_message_claude_error(self, mock_cmd):
        mock_cmd.return_value = {"returncode": 1, "stdout": "", "stderr": "timeout"}
        with self.assertRaises(RuntimeError):
            services.send_chat_message(self.issue.id, "Hello")
        # User message should still be saved
        self.assertEqual(ChatMessage.objects.filter(issue=self.issue, role="user").count(), 1)


class ChatViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.review = PullRequest.objects.create(repo="acme/app", pr_number=42, status="complete")
        self.issue = Issue.objects.create(
            review=self.review, file_path="a.py", line_number=10,
            severity="bug", title="Bug", body="B", suggestion="S", status="pending",
        )

    @patch("reviews.services._run_cmd")
    def test_send_chat_post(self, mock_cmd):
        mock_cmd.return_value = {"returncode": 0, "stdout": "Response", "stderr": ""}
        response = self.client.post(
            reverse("reviews:send_chat", args=[self.issue.id]),
            {"message": "Why?"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["role"], "assistant")
        self.assertEqual(data["content"], "Response")

    def test_send_chat_empty_message(self):
        response = self.client.post(
            reverse("reviews:send_chat", args=[self.issue.id]),
            {"message": ""},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_send_chat_get_not_allowed(self):
        response = self.client.get(reverse("reviews:send_chat", args=[self.issue.id]))
        self.assertEqual(response.status_code, 405)

    @patch("reviews.services._run_cmd")
    def test_send_chat_claude_failure(self, mock_cmd):
        mock_cmd.return_value = {"returncode": 1, "stdout": "", "stderr": "error"}
        response = self.client.post(
            reverse("reviews:send_chat", args=[self.issue.id]),
            {"message": "Hello"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 500)
        self.assertIn("error", response.json())

    def test_issue_detail_shows_chat(self):
        ChatMessage.objects.create(issue=self.issue, role="user", content="Question")
        ChatMessage.objects.create(issue=self.issue, role="assistant", content="Answer")
        response = self.client.get(reverse("reviews:issue_detail", args=[self.issue.id]))
        self.assertContains(response, "Question")
        self.assertContains(response, "Answer")
        self.assertContains(response, "Ask Claude")


class DownloadReportTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.review = PullRequest.objects.create(repo="acme/app", pr_number=42, status="complete")
        Issue.objects.create(
            review=self.review, file_path="a.py", line_number=10,
            severity="bug", title="Bug", body="B", suggestion="S", status="pending",
        )

    @patch("weasyprint.HTML")
    def test_download_report_returns_pdf(self, mock_html_cls):
        mock_html_cls.return_value.write_pdf.return_value = b"%PDF-1.4 fake"
        response = self.client.get(reverse("reviews:download_report", args=[self.review.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(".pdf", response["Content-Disposition"])
        self.assertEqual(response.content, b"%PDF-1.4 fake")
