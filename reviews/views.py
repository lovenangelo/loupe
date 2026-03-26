import threading

from django.core.paginator import Paginator
from django.contrib import messages
from django.shortcuts import redirect, render
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from . import services
from .forms import CreateReviewForm, UpdateStatusForm, IssueStatusForm, DraftCommentForm


def index(request):
    reviews = services.get_reviews()
    paginator = Paginator(reviews, 10)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "reviews/dashboard.html", {"reviews": page})


def create_review(request):
    if request.method == "POST":
        form = CreateReviewForm(request.POST)
        if form.is_valid():
            review = services.save_review(
                repo=form.cleaned_data["repo"],
                pr_number=form.cleaned_data["pr_number"],
                review_prompt=form.cleaned_data.get("review_prompt", ""),
            )
            # Run Claude review in background thread
            thread = threading.Thread(
                target=services.run_pr_review,
                args=(review.id,),
                daemon=True,
            )
            thread.start()
            messages.success(
                request,
                f"Review for PR #{review.pr_number} started. Refresh to see results.",
            )
            return redirect("reviews:show", review_id=review.id)
    else:
        form = CreateReviewForm()
    return render(request, "reviews/create.html", {"form": form})


@require_POST
def rerun_review(request, review_id):
    review = services.get_review(review_id)
    if review.status == "analyzing":
        messages.warning(request, "Review is already in progress.")
        return redirect("reviews:show", review_id=review_id)
    thread = threading.Thread(
        target=services.run_pr_review,
        args=(review.id,),
        daemon=True,
    )
    thread.start()
    messages.success(request, "Re-review started. Refresh to see results.")
    return redirect("reviews:show", review_id=review_id)


def show_review(request, review_id):
    review = services.get_review(review_id)
    status_form = UpdateStatusForm(initial={"status": review.status})
    return render(request, "reviews/show.html", {
        "review": review,
        "status_form": status_form,
    })


@require_POST
def delete_review(request, review_id):
    services.delete_review(review_id)
    messages.success(request, "Review deleted.")
    return redirect("reviews:index")


@require_POST
def update_status(request, review_id):
    form = UpdateStatusForm(request.POST)
    if form.is_valid():
        services.update_review_status(review_id, form.cleaned_data["status"])
        messages.success(request, "Status updated.")
    return redirect("reviews:show", review_id=review_id)


def poll_status(request, review_id):
    review = services.get_review(review_id)
    return JsonResponse({
        "status": review.status,
        "issue_count": review.issues.count(),
    })


def review_issues(request, review_id):
    review = services.get_review(review_id)
    issues = services.get_issues_for_review(review_id)
    paginator = Paginator(issues, 10)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "reviews/issues.html", {
        "review": review,
        "issues": page,
    })


def show_issue(request, issue_id):
    issue = services.get_issue(issue_id)
    status_form = IssueStatusForm()
    initial_body = f"**{issue.file_path}:{issue.line_number}**\n\n"
    comment_form = DraftCommentForm(initial={"body": initial_body})
    return render(request, "reviews/issue_detail.html", {
        "issue": issue,
        "status_form": status_form,
        "comment_form": comment_form,
    })


@require_POST
def update_issue_status(request, issue_id):
    form = IssueStatusForm(request.POST)
    if form.is_valid():
        services.update_issue_status(issue_id, form.cleaned_data["status"])
        messages.success(request, f"Issue marked as {form.cleaned_data['status']}.")
    return redirect("reviews:issue_detail", issue_id=issue_id)


@require_POST
def create_comment(request, issue_id):
    form = DraftCommentForm(request.POST)
    if form.is_valid():
        services.save_comment_draft(issue_id, form.cleaned_data["body"])
        messages.success(request, "Comment saved as draft.")
    return redirect("reviews:issue_detail", issue_id=issue_id)


def edit_comment(request, comment_id):
    comment = services.get_comment(comment_id)
    if request.method == "POST":
        form = DraftCommentForm(request.POST)
        if form.is_valid():
            services.update_comment(comment_id, form.cleaned_data["body"])
            messages.success(request, "Comment updated.")
            return redirect("reviews:issue_detail", issue_id=comment.issue_id)
    else:
        form = DraftCommentForm(initial={"body": comment.body})
    return render(request, "reviews/edit_comment.html", {
        "comment": comment,
        "form": form,
    })


@require_POST
def post_comment(request, comment_id):
    comment = services.get_comment(comment_id)
    try:
        result = services.post_comment_to_github(
            comment.issue.review.repo,
            comment.issue.review.pr_number,
            comment.body,
            comment.issue.file_path,
            comment.issue.line_number,
        )
        services.add_comment_to_github_pr(comment_id, result)
        messages.success(request, "Comment posted to GitHub.")
    except RuntimeError as e:
        messages.error(request, f"Failed to post: {e}")
    return redirect("reviews:issue_detail", issue_id=comment.issue_id)


def download_report(request, review_id):
    review = services.get_review(review_id)
    issues = services.get_issues_for_review(review_id)
    html = render_to_string("reviews/report.html", {
        "review": review,
        "issues": issues,
    })
    response = HttpResponse(html, content_type="text/html")
    filename = f"loupe-{review.repo.replace('/', '-')}-PR{review.pr_number}.html"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
