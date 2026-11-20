FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash coreutils \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash agent \
    && mkdir -p /shared \
    && chown -R agent:agent /app /shared

COPY --chown=agent:agent requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY --chown=agent:agent agent_main.py /app/agent_main.py
COPY --chown=agent:agent actor_server.py /app/actor_server.py
RUN chmod +x /app/agent_main.py /app/actor_server.py

USER agent

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 80
CMD ["python3", "/app/actor_server.py"]