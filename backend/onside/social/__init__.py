"""The social feed: public posts about the matches Onside is showing.

Sources are adapters behind one small interface (`base.Source`). Mastodon works
with no credentials; Bluesky needs a free app password; Reddit needs an
approved app; X is pay-per-read and stays off unless a budget is set. Each
source says what state it is in, so the dashboard can explain an empty column
instead of showing one.
"""
