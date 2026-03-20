from django import forms
from .models import DEFAULT_REVIEW_PROMPT

tw_input = "border border-border rounded-md px-3 py-2 w-full bg-card text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
tw_select = "border border-border rounded-md px-3 py-2 bg-card text-foreground focus:outline-none focus:ring-2 focus:ring-ring"


class CreateReviewForm(forms.Form):
    repo = forms.CharField(
        max_length=255,
        widget=forms.TextInput(
            attrs={"class": tw_input, "placeholder": "owner/repo, e.g. django/django"}
        ),
    )
    pr_number = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(
            attrs={"class": tw_input, "placeholder": "Enter PR number"}
        ),
    )
    review_prompt = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": tw_input,
                "rows": 6,
                "placeholder": DEFAULT_REVIEW_PROMPT,
            }
        ),
    )


class UpdateStatusForm(forms.Form):
    status = forms.ChoiceField(
        choices=[
            ("pending", "Pending"),
            ("analyzing", "Analyzing"),
            ("complete", "Complete"),
            ("error", "Error"),
        ],
        widget=forms.Select(attrs={"class": tw_select}),
    )


class IssueStatusForm(forms.Form):
    status = forms.ChoiceField(
        choices=[
            ("approved", "Approved"),
            ("dismissed", "Dismissed"),
        ],
        widget=forms.Select(attrs={"class": tw_select}),
    )


class DraftCommentForm(forms.Form):
    body = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": tw_input,
                "rows": 3,
                "placeholder": "Write a comment...",
            }
        ),
    )
