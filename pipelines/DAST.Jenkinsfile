// DAST — запускает Kargo (верификация стейджа uat) и ждёт статус сборки:
// SUCCESS → Freight verified на uat и может идти в prod; FAILURE → нет.
// Чтобы сымитировать провал: Configure → FAIL_REPOS = qa-at-core (значение по умолчанию попадёт в вызов Kargo).

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
      image: python:3.14-slim
      command: ["sleep"]
      args: ["infinity"]
'''
    }
  }

  parameters {
    string(name: 'REPOS', defaultValue: '', description: 'Список репозиториев через запятую (передаёт Kargo)')
    string(name: 'ENVIRONMENT', defaultValue: 'uat', description: 'Окружение')
    string(name: 'RELEASE', defaultValue: '', description: 'Коммит ветки ФП (Freight)')
    string(name: 'FAIL_REPOS', defaultValue: '', description: 'Эмуляция: подстроки репозиториев, по которым DAST упадёт')
  }

  options {
    buildDiscarder(logRotator(numToKeepStr: '50'))
    timeout(time: 15, unit: 'MINUTES')
  }

  stages {
    stage('DAST (эмуляция)') {
      steps {
        script {
          currentBuild.displayName = "#${env.BUILD_NUMBER} ${params.ENVIRONMENT} ${params.RELEASE.take(7)}"
        }
        sh 'python3 scripts/release_tool.py dast --repos "$REPOS" --environment "$ENVIRONMENT" --release "$RELEASE" --fail-repos "$FAIL_REPOS" --out reports/dast.json'
      }
    }
  }

  post {
    always {
      archiveArtifacts artifacts: 'reports/**', allowEmptyArchive: true
    }
  }
}
