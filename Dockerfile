FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TRADEVAULT_ENV=production \
    PORT=3000
WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --create-home app
COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip && pip install -r requirements.txt
COPY --chown=app:app . .
RUN mkdir -p /app/instance && chown -R app:app /app/instance
USER app
EXPOSE 3000
CMD ["/bin/sh", "-c", "flask --app app:app db upgrade && exec gunicorn --bind 0.0.0.0:${PORT:-3000} --workers 2 --threads 4 --timeout 120 --access-logfile - --error-logfile - app:app"]
