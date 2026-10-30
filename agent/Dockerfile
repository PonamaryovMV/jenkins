# Агент для пайплайнов стенда: python + git + pyyaml.
# Небольшой образ вместо полного python:3.14 (~1 ГБ) — под агента стартует за секунды.
FROM python:3.14-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir pyyaml==6.0.3

LABEL org.opencontainers.image.source="https://github.com/PonamaryovMV/jenkins" \
      org.opencontainers.image.title="jenkins-agent-python"

# uid 1000 = пользователь jenkins в jnlp-контейнере: общий workspace без проблем с правами
RUN useradd -m -u 1000 jenkins
USER 1000
WORKDIR /home/jenkins
