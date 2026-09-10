FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home cos
COPY --chown=cos:cos src ./src
COPY --chown=cos:cos web ./web
ENV PYTHONUNBUFFERED=1
USER cos
EXPOSE 5087
CMD ["gunicorn", "--bind", "0.0.0.0:5087", "--workers", "2", "--threads", "4", "--timeout", "120", "web.app:app"]
