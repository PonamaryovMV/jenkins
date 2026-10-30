// ExcludeService — исключение сервиса из релиза ФП qa/at. Без сборки, только git.
//   planned — новый Freight: в ветке ФП qa-at файл сервиса = версия, что сейчас в PROD. Дальше uat → prod в Kargo.
//   urgent  — срочно: запись в gitops-prod qa/at/release-exclude.yaml. Дальше повторный Promote текущего Freight в prod.
//   clear   — снять срочное исключение.

pipeline {
  agent {
    kubernetes {
      defaultContainer 'python'
      yaml '''
apiVersion: v1
kind: Pod
spec:
  containers:
    - name: python
      image: ghcr.io/ponamaryovmv/jenkins-agent-python:1
      command: ["sleep"]
      args: ["infinity"]
      resources:
        requests: { cpu: 50m, memory: 128Mi }
'''
    }
  }

  parameters {
    choice(name: 'SERVICE', choices: ['mgmt', 'core', 'api'], description: 'Сервис ФП')
    choice(name: 'MODE', choices: ['planned', 'urgent', 'clear'], description: 'planned — новый Freight через uat; urgent — срочно в prod; clear — снять срочное исключение')
    string(name: 'TASK', defaultValue: 'TASK-2', description: 'Релизная задача')
    string(name: 'REASON', defaultValue: 'INC-1', description: 'Причина (инцидент)')
  }

  options {
    buildDiscarder(logRotator(numToKeepStr: '50'))
    disableConcurrentBuilds()
    timeout(time: 10, unit: 'MINUTES')
  }

  stages {
    stage('Исключение') {
      steps {
        script {
          currentBuild.displayName = "#${env.BUILD_NUMBER} ${params.MODE} ${params.SERVICE}"
          currentBuild.description = "${params.TASK} · ${params.REASON}"
        }
        withCredentials([string(credentialsId: 'github-token', variable: 'GH_TOKEN')]) {
          sh '''
            git config --global --add safe.directory '*'
            python3 scripts/release_tool.py exclude --mode "$MODE" --service "$SERVICE" --task "$TASK" --reason "$REASON"
          '''
        }
      }
    }
  }
}
