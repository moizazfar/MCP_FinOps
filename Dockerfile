# ── SCC-safe for OpenShift (no root, arbitrary UID support) ──
FROM python:3.11-slim

# OpenShift runs containers with arbitrary UIDs (e.g. 1000650000)
# Must NOT use USER root. Give group write perms to /app.
WORKDIR /app

# Install deps first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY server.py .

# OpenShift arbitrary UID fix:
# - files owned by root GROUP (0) so random UID can still read
# - no setuid/setgid binaries
RUN chgrp -R 0 /app && chmod -R g=u /app

# Non-root user (OpenShift will override with random UID anyway)
USER 1001

EXPOSE 8080

ENV PORT=8080
ENV HOST=0.0.0.0
ENV PYTHONUNBUFFERED=1

CMD ["python", "server.py"]
