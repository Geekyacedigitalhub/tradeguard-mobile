# Makes `backend` a regular package so the repo-root FastAPI Cloud entrypoint
# (backend.app.main:app in the root pyproject.toml) is importable when the
# build/deploy context is the repository root.
