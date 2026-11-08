# Контроллер Jenkins стенда с плагинами внутри образа.
# Зачем: чарт по умолчанию качает плагины с updates.jenkins.io при каждом старте pod'а —
# после перезапуска ПК (сбой DNS в kind, недоступные зеркала) Jenkins не поднимался.
# Версия Jenkins = appVersion чарта jenkins 5.10.5, tagLabel чарта = jdk25.
ARG JENKINS_VERSION=2.580.2
FROM jenkins/jenkins:${JENKINS_VERSION}-jdk25

# jenkins-plugin-cli ставит плагины с зависимостями в /usr/share/jenkins/ref/plugins;
# при старте jenkins.sh копирует их в JENKINS_HOME
COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt --latest true

LABEL org.opencontainers.image.source="https://github.com/PonamaryovMV/jenkins" \
      org.opencontainers.image.title="jenkins-controller"
