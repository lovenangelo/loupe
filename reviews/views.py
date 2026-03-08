from django.shortcuts import render


def index(request):
    return render(request, "reviews/dashboard.html")


def store(request):
    return render("Should save a review")


def show(request, review_id):
    return render("Should get a review")


def issues(request):
    return render("Should show list of issues from review")
