FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home agent && mkdir data && chown agent:agent data
USER agent
VOLUME ["/app/data"]
ENTRYPOINT ["aws-cost-agent"]
CMD ["--config", "/app/config.toml", "run"]
