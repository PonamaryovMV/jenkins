// Релизный пайплайн тестового стенда.
//
//   Checkout → Тесты → SCA (эмуляция) → Quality Gate → Publish (GitHub Actions → ghcr → Kargo)
//
// SCA не настоящий: qg/sca_scan.py генерирует отчёт по выбранному профилю SCA_PROFILE,
// чтобы можно было проверить поведение Quality Gate на любом исходе.

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
      resources:
        requests: { cpu: 50m, memory: 64Mi }
'''
    }
  }

  parameters {
    choice(name: 'APP', choices: ['hello-api', 'color-web'], description: 'Приложение из gitops-main')
    string(name: 'VERSION', defaultValue: '1.3.0', description: 'Версия X.Y.Z, под которой соберётся образ')
    choice(name: 'SCA_PROFILE', choices: ['clean', 'low', 'medium', 'high', 'critical'],
           description: 'Эмулируемый результат SCA: clean/low/medium проходят QG, high/critical — нет')
    booleanParam(name: 'PUBLISH', defaultValue: false,
                 description: 'После прохождения QG запустить сборку образа в GitHub Actions (дальше подхватит Kargo)')
  }

  options {
    buildDiscarder(logRotator(numToKeepStr: '30'))
    disableConcurrentBuilds()
    timeout(time: 20, unit: 'MINUTES')
  }

  environment {
    REPORTS = 'reports'
    APP_REPO = 'https://github.com/PonamaryovMV/gitops-main.git'
  }

  stages {
    stage('Параметры') {
      steps {
        script {
          if (!(params.VERSION ==~ /^\d+\.\d+\.\d+$/)) {
            error "VERSION должна быть X.Y.Z, получено: ${params.VERSION}"
          }
          currentBuild.displayName = "#${env.BUILD_NUMBER} ${params.APP}:${params.VERSION}"
          currentBuild.description = "SCA=${params.SCA_PROFILE}, publish=${params.PUBLISH}"
        }
        sh 'mkdir -p "$REPORTS"'
      }
    }

    stage('Checkout приложения') {
      steps {
        // в python:slim нет git — клонируем в jnlp-контейнере, workspace общий
        container('jnlp') {
          dir('app-src') {
            git url: env.APP_REPO, branch: 'main'
          }
        }
      }
    }

    stage('Тесты') {
      steps {
        sh 'python3 qg/smoke_test.py --src "app-src/apps/$APP/src/app.py" --out "$REPORTS/tests.json"'
      }
    }

    stage('SCA (эмуляция)') {
      steps {
        sh '''
          python3 qg/sca_scan.py \
            --app "$APP" --version "$VERSION" \
            --src "app-src/apps/$APP/src" \
            --profile "$SCA_PROFILE" \
            --out "$REPORTS/sca.json"
        '''
      }
    }

    stage('Quality Gate') {
      steps {
        script {
          def rc = sh(returnStatus: true,
                      script: 'python3 qg/quality_gate.py --report "$REPORTS/sca.json" --policy qg/policy.json --out "$REPORTS/quality-gate.json"')
          def qg = readJSON file: "${env.REPORTS}/quality-gate.json"
          currentBuild.description = "QG ${qg.status}: ${qg.summary}"
          if (rc != 0) {
            error "Quality Gate не пройден: ${qg.violations.join('; ')}"
          }
        }
      }
    }

    stage('Publish') {
      when { expression { params.PUBLISH } }
      steps {
        withCredentials([string(credentialsId: 'github-token', variable: 'GH_TOKEN')]) {
          sh 'python3 qg/dispatch_build.py --app "$APP" --version "$VERSION"'
        }
        echo "Сборка ${params.APP}:${params.VERSION} запущена в GitHub Actions. Kargo подхватит образ из ghcr за ~30с после сборки."
      }
    }
  }

  post {
    always {
      archiveArtifacts artifacts: 'reports/**', allowEmptyArchive: true
    }
  }
}
