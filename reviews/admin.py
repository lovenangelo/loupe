from django.contrib import admin
from .models import PullRequest, Issue, DraftComment


class IssueInline(admin.TabularInline):
    model = Issue
    extra = 0
    fields = ("title", "severity", "status", "file_path", "line_number")
    readonly_fields = ("title",)


class DraftCommentInline(admin.TabularInline):
    model = DraftComment
    extra = 0
    fields = ("body", "posted", "github_comment_id")


@admin.register(PullRequest)
class PullRequestAdmin(admin.ModelAdmin):
    list_display = ("pr_number", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("pr_number",)
    ordering = ("-created_at",)
    inlines = [IssueInline]


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = ("title", "review", "severity", "status", "file_path", "line_number")
    list_filter = ("severity", "status")
    search_fields = ("title", "file_path")
    inlines = [DraftCommentInline]


@admin.register(DraftComment)
class DraftCommentAdmin(admin.ModelAdmin):
    list_display = ("issue", "body_preview", "posted", "github_comment_id")
    list_filter = ("posted",)

    @admin.display(description="Body")
    def body_preview(self, obj):
        return obj.body[:80] + "..." if len(obj.body) > 80 else obj.body
