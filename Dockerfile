FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app

# Run as an unprivileged user, so a bug in the app cannot become root in the container.
RUN useradd --system --uid 10001 appuser
USER appuser

EXPOSE 8000
# Apply any pending migrations, then start the server. `exec` hands the process over to
# uvicorn so it receives shutdown signals. If a migration fails the container stops and
# the error is in `docker compose logs api`, instead of running on an out-of-date schema.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]