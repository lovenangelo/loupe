from django.urls import path
from . import views

app_name = "reviews"

urlpatterns = [
    path("", views.index, name="index"),
    path("reviews/create/", views.create_review, name="create"),
    path("reviews/<uuid:review_id>/", views.show_review, name="show"),
    path("reviews/<uuid:review_id>/rerun/", views.rerun_review, name="rerun"),
    path("reviews/<uuid:review_id>/delete/", views.delete_review, name="delete"),
    path("reviews/<uuid:review_id>/status/", views.update_status, name="update_status"),
    path("reviews/<uuid:review_id>/issues/", views.review_issues, name="issues"),
    path("issues/<uuid:issue_id>/", views.show_issue, name="issue_detail"),
    path("issues/<uuid:issue_id>/status/", views.update_issue_status, name="issue_update_status"),
    path("issues/<uuid:issue_id>/comment/", views.create_comment, name="create_comment"),
    path("reviews/<uuid:review_id>/poll/", views.poll_status, name="poll_status"),
    path("comments/<uuid:comment_id>/edit/", views.edit_comment, name="edit_comment"),
    path("comments/<uuid:comment_id>/post/", views.post_comment, name="post_comment"),
    path("reviews/<uuid:review_id>/report/", views.download_report, name="download_report"),
]
