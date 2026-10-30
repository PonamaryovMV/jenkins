// BuildRelease — релиз ФП qa/at.
//   Образы → SCA (список образов) → SAST (список репозиториев) → Quality Gate → один коммит в ветку ФП qa-at.
// Сборки на стенде нет: образы с тегами release-1-101 / release-2-102 / release-3-103 уже лежат в ghcr.
// Kargo увидит коммит в qa-at и создаст Freight. В Kargo Jenkins не ходит.

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
      image: python:3.14          # полный образ: есть git
      command: ["sleep"]
      args: ["infinity"]
      resources:
        requests: { cpu: 50m, memory: 128Mi }
'''
    }
  }

  parameters {
    string(name: 'TASK', defaultValue: 'TASK-2', description: 'Релизная задача')
    choice(name: 'VERSION', choices: ['release-2-102', 'release-3-103', 'release-1-101'], description: 'Тег образов сервисов')
    string(name: 'SERVICES', defaultValue: 'mgmt,core,api', description: 'Сервисы ФП через запятую: mgmt, core, api')
    choice(name: 'SCA_PROFILE', choices: ['clean', 'low', 'medium', 'high', 'critical'], description: 'Эмуляция SCA: high/critical не проходят QG')
    choice(name: 'SAST_PROFILE', choices: ['clean', 'low', 'medium', 'high', 'critical'], description: 'Эмуляция SAST: high/critical не проходят QG')
  }

  options {
    buildDiscarder(logRotator(numToKeepStr: '50'))
    disableConcurrentBuilds()
    timeout(time: 20, unit: 'MINUTES')
  }

  environment {
    R = 'reports'
  }

  stages {
    stage('Подготовка') {
      steps {
        script {
          currentBuild.displayName = "#${env.BUILD_NUMBER} ${params.TASK} ${params.VERSION}"
          currentBuild.description = "${params.SERVICES} · SCA=${params.SCA_PROFILE} SAST=${params.SAST_PROFILE}"
        }
        sh 'pip install -q pyyaml && mkdir -p "$R"'
      }
    }
    stage('Образы в registry') {
      steps {
        sh 'python3 scripts/release_tool.py images --services "$SERVICES" --version "$VERSION" --out "$R/images.json"'
      }
    }
    stage('SCA (образы)') {
      steps {
        sh 'python3 scripts/release_tool.py sca --images "$R/images.json" --profile "$SCA_PROFILE" --out "$R/sca.json"'
      }
    }
    stage('SAST (репозитории)') {
      steps {
        sh 'python3 scripts/release_tool.py sast --images "$R/images.json" --profile "$SAST_PROFILE" --out "$R/sast.json"'
      }
    }
    stage('Quality Gate') {
      steps {
        sh 'python3 scripts/release_tool.py gate --sca "$R/sca.json" --sast "$R/sast.json" --policy scripts/policy.json --out "$R/gate.json"'
      }
    }
    stage('Коммит в ветку ФП qa-at') {
      steps {
        withCredentials([string(credentialsId: 'github-token', variable: 'GH_TOKEN')]) {
          sh '''
            git config --global --add safe.directory '*'
            python3 scripts/release_tool.py release --images "$R/images.json" --gate "$R/gate.json" \
              --version "$VERSION" --task "$TASK" --build "$BUILD_NUMBER" --out "$R/commit.json"
          '''
        }
        echo 'Kargo создаст Freight из этого коммита (Warehouse qa-at, ~30 с). Промоушен dev → test → uat → prod — в Kargo.'
      }
    }
  }

  post {
    always {
      archiveArtifacts artifacts: 'reports/**', allowEmptyArchive: true
    }
  }
}
