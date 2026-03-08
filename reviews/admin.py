from django.contrib import admin

from .models import PullRequest, Issue, DraftComment

admin.site.register(PullRequest)
admin.site.register(Issue)
admin.site.register(DraftComment)
