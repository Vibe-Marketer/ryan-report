"""R2 credentials baked into the installed app for the feedback uploader.

These are populated at build time by .github/workflows/build.yml from
GitHub Actions secrets. In dev (and in the source tree) the values are empty
strings, which causes feedback.py to fall back to env vars.

This file is NOT gitignored — it ships in source as empty stubs so the import
in feedback.py always succeeds. CI overwrites it during the Windows build.
"""

R2_ACCESS_KEY_ID:     str = ""
R2_SECRET_ACCESS_KEY: str = ""
R2_ENDPOINT_URL:      str = ""
R2_BUCKET:            str = "catom-updates"
