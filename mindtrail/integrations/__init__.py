"""Third-party, read-only integrations (currently just Google Calendar).

Kept separate from organize/ - these modules talk to an external API and
hold a live OAuth credential on disk, unlike everything under organize/,
which only ever touches mindtrail's own SQLite file.
"""
