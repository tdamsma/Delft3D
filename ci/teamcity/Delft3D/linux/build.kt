package Delft3D.linux

import jetbrains.buildServer.configs.kotlin.*
import jetbrains.buildServer.configs.kotlin.buildFeatures.*
import jetbrains.buildServer.configs.kotlin.buildSteps.*
import jetbrains.buildServer.configs.kotlin.failureConditions.*
import Delft3D.template.*
import Delft3D.step.*
import Delft3D.linux.containers.*

object LinuxBuild : BuildType({

    description = "CMake build."

    templates(
        TemplateMergeRequest,
        TemplateDetermineProduct,
        TemplatePublishStatus,
        TemplateMonitorPerformance,
        TemplateFailureCondition,
        TemplateDockerRegistry
    )

    name = "Build"
    buildNumberPattern = "%product%: %build.vcs.number%"

    allowExternalStatus = true
    artifactRules = """
        #teamcity:symbolicLinks=as-is
        **/*.log => logging
        build_%product%/install/** => oss_artifacts_lnx64_%build.vcs.number%.tar.gz!lnx64
        unit-test-report-linux.xml
    """.trimIndent()

    outputParams {
        exposeAllParameters = false
        param("product", "%product%")
        param("build_type", "%build_type%")
        param("commit_id", "%build.revisions.revision%")
        param("commit_id_short", "%build.revisions.short%")
        param("build_tools_image_tag", "%dep.${LinuxBuildTools.id}.env.IMAGE_TAG%")
    }

    params {
        param("generator", """"Unix Makefiles"""")
        select("product", "auto-select", display = ParameterDisplay.PROMPT, options = listOf("auto-select", "all-testbench", "fm-suite", "d3d4-suite", "fm-testbench", "d3d4-testbench", "waq-testbench", "part-testbench", "rr-testbench", "wave-testbench", "swan-testbench"))
        select("build_type", "%dep.${LinuxThirdPartyLibs.id}.build_type%", display = ParameterDisplay.PROMPT, options = listOf("Release", "RelWithDebInfo", "Debug"))
        param("env.CONAN_LOGIN_USERNAME_DELTARESCONAN", DslContext.getParameter("conan.username"))
        param("env.CONAN_PASSWORD_DELTARESCONAN", DslContext.getParameter("conan.password"))
        param("env.CONAN_LOGIN_USERNAME_DELTARESCONANDEV", DslContext.getParameter("conan.username"))
        param("env.CONAN_PASSWORD_DELTARESCONANDEV", DslContext.getParameter("conan.password"))
        param("deltaresconan_url", DslContext.getParameter("conan.deltaresconan"))
        param("deltaresconandev_url", DslContext.getParameter("conan.deltaresconandev"))
      
    }

    vcs {
        root(DslContext.settingsRoot)
        cleanCheckout = true
        checkoutDir = "ossbuild-lnx64"
    }
  
    

    steps {
        mergeTargetBranch {}
        script {
            name = "Add version attributes"
            workingDir = "./src/version_includes"
            scriptContent = """
                #!/usr/bin/env bash
                echo '#define BUILD_NR "%build.vcs.number%"' > checkout_info.h
                echo '#define BRANCH "%teamcity.build.branch%"' >> checkout_info.h
            """.trimIndent()
        }
        script {
          name = "Load, Build, Create, Push, Conan"
          workingDir = "./"
          val recipedirectory = ""
          scriptContent = """
              #!/usr/bin/env bash
              curl -LsSf https://astral.sh/uv/install.sh | sh
              source ~/.local/bin/env
              uv sync 
              source .venv/bin/activate
              conan remote add deltaresconan "%deltaresconan_url%" --force 
              conan remote add deltaresconandev "%deltaresconandev_url%" --force 
              conan remote remove conancenter
              conan profile detect
              for recipedirectory in ./tools/conan/recipes/*/*/ ; do
                 if [ -f "$recipedirectory/conanfile.py" ]; then
                  echo "Adding editable and creating it: $recipedirectory"
                  conan editable add "$recipedirectory" 
                  conan create $recipedirectory --build=missing
                fi
              done
              conan install --build=missing --output-folder=./build/ conanfile.py 
              conan upload "*" -r deltaresconandev --confirm
          """.trimIndent()
          dockerImage = "containers.deltares.nl/delft3d-dev/delft3d-third-party-libs:%dep.${LinuxThirdPartyLibs.id}.env.IMAGE_TAG%"
          dockerImagePlatform = ScriptBuildStep.ImagePlatform.Linux
          dockerRunParameters = "--rm"
          dockerPull = true
        }
        exec {
            name = "Build"
            path = "ci/teamcity/Delft3D/linux/scripts/build.sh"
            arguments = """
                --generator %generator%
                --product %product%
                --build-type %build_type%
            """.trimIndent()
            dockerImage = "containers.deltares.nl/delft3d-dev/delft3d-third-party-libs:%dep.${LinuxThirdPartyLibs.id}.env.IMAGE_TAG%"
            dockerImagePlatform = ExecBuildStep.ImagePlatform.Linux
            dockerRunParameters = "--rm"
            dockerPull = true
        }
        script {
            name = "Run unit tests"
            scriptContent = """
                #!/usr/bin/env bash
                source /opt/bashrc
                ctest --test-dir build_%product% --build-config %build_type% --output-junit ../unit-test-report-linux.xml --output-on-failure
            """.trimIndent()
            dockerImage = "containers.deltares.nl/delft3d-dev/delft3d-third-party-libs:%dep.${LinuxThirdPartyLibs.id}.env.IMAGE_TAG%"
            dockerImagePlatform = ScriptBuildStep.ImagePlatform.Linux
            dockerRunParameters = "--rm"
            dockerPull = true
        }
        script {
            name = "Install"
            scriptContent = """
                #!/usr/bin/env bash
                source /opt/bashrc
                cmake --install build_%product% --config %build_type%
            """.trimIndent()
            dockerImage = "containers.deltares.nl/delft3d-dev/delft3d-third-party-libs:%dep.${LinuxThirdPartyLibs.id}.env.IMAGE_TAG%"
            dockerImagePlatform = ScriptBuildStep.ImagePlatform.Linux
            dockerRunParameters = "--rm"
            dockerPull = true
        }
    }

    features {
        xmlReport {
            reportType = XmlReport.XmlReportType.JUNIT
            rules = "+:unit-test-report-linux.xml"
        }
    }

    dependencies {
        dependency(LinuxThirdPartyLibs) {
            snapshot {
                onDependencyFailure = FailureAction.FAIL_TO_START
                onDependencyCancel = FailureAction.CANCEL
            }
        }
    }

    requirements {
        equals("teamcity.agent.jvm.os.name", "Linux")
    }
})
