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
          name = "Load, Build, Create, Push, Conan, Build"
          workingDir = "./"
          val recipedirectory = ""
          scriptContent = """
              #!/usr/bin/env bash 
              # Prerequisites 
              dnf install git -y
              wget -qO- https://astral.sh/uv/install.sh | sh
              source ~/.local/bin/env
              ## install conan trough uv
              uv sync 
              source .venv/bin/activate
              export CONAN_HOME=${'$'}PWD/.conan2
              ## setup remote (order is importannt (first dev (picks the right binary), 
              ## then local (build if we dont), 
              ## then proxy (anything we dont build with a local recipe)
              ## remove the default as to always go trough deltares proxy
              conan remote add local-recipes /work/tools/conan/recipes --type=local-recipes-index --force --index=1
              conan remote add deltaresconan "%deltaresconan_url%" --force --index=2
              conan remote add deltaresconandev "%deltaresconandev_url%" --force --index=0
              conan remote remove conancenter
              ## little hack for adding 2024.2 to intel compiles (its not in the settings.yml that get generated)
              sed -i 's/"2024.1",/"2024.1","2024.2",/g' ${'$'}PWD/.conan2/settings.yml
              ## make sure we have a default profile
              conan profile detect
              ## install packages and there dependencies using the default linux profile 
              conan install --profile:build=tools/conan/default_linux --profile:host=tools/conan/default_linux --build=missing --output-folder=./build/ conanfile.py 
              ## pushback packages that we have created so that any update gets into nexus (We dont need the next person then to build it again :) )
              conan upload "*" -r deltaresconandev --confirm
               source /etc/bashrc
              export PKG_CONFIG_PATH=/usr/local/lib/pkgconfig:${'$'}PKG_CONFIG_PATH
              export LD_LIBRARY_PATH=/usr/local/lib:${'$'}LD_LIBRARY_PATH
              export CMAKE_PREFIX_PATH=/usr/local:${'$'}CMAKE_PREFIX_PATH
              export CMAKE_INCLUDE_PATH=/usr/local/include:${'$'}CMAKE_INCLUDE_PATH
              export CMAKE_LIBRARY_PATH=/usr/local/lib:${'$'}CMAKE_LIBRARY_PATH
              cmake -S ./src/cmake -G %generator% -D CONFIGURATION_TYPE:STRING=%product% -D CMAKE_BUILD_TYPE=%build_type% -B build_%product% -D CMAKE_INSTALL_PREFIX=build_%product%/install  -D CMAKE_TOOLCHAIN_FILE=../build/build/%build_type%/generators/conan_toolchain.cmake
              cmake --build build_%product% --parallel --config %build_type%
          """.trimIndent()
          dockerImage = "containers.deltares.nl/delft3d-dev/delft3d-third-party-libs:%dep.${LinuxThirdPartyLibs.id}.env.IMAGE_TAG%"
          dockerImagePlatform = ScriptBuildStep.ImagePlatform.Linux
          dockerRunParameters = "--rm"
          dockerPull = true
        }
//        script {
//            name = "Build"
//            scriptContent = """
//                #!/usr/bin/env bash
//                source /etc/bashrc
//                export CONAN_HOME=${'$'}PWD/.conan2
//                set -eo pipefail
//                export PKG_CONFIG_PATH=/usr/local/lib/pkgconfig:${'$'}PKG_CONFIG_PATH
//                export LD_LIBRARY_PATH=/usr/local/lib:${'$'}LD_LIBRARY_PATH
//                export CMAKE_PREFIX_PATH=/usr/local:${'$'}CMAKE_PREFIX_PATH
//                export CMAKE_INCLUDE_PATH=/usr/local/include:${'$'}CMAKE_INCLUDE_PATH
//                export CMAKE_LIBRARY_PATH=/usr/local/lib:${'$'}CMAKE_LIBRARY_PATH
//                echo " cmake -S ./src/cmake -G %generator% -D CONFIGURATION_TYPE:STRING=%product% -D CMAKE_BUILD_TYPE=%build_type% -B build_%product% -D CMAKE_INSTALL_PREFIX=build_%product%/install  -D CMAKE_TOOLCHAIN_FILE=../build/build/%build_type%/generators/conan_toolchain.cmake"
//                cmake -S ./src/cmake -G %generator% -D CONFIGURATION_TYPE:STRING=%product% -D CMAKE_BUILD_TYPE=%build_type% -B build_%product% -D CMAKE_INSTALL_PREFIX=build_%product%/install  -D CMAKE_TOOLCHAIN_FILE=../build/build/%build_type%/generators/conan_toolchain.cmake
//                cmake --build build_%product% --parallel --config %build_type%
//            """.trimIndent()
//            dockerImage = "containers.deltares.nl/delft3d-dev/delft3d-third-party-libs:%dep.${LinuxThirdPartyLibs.id}.env.IMAGE_TAG%"
//            dockerImagePlatform = ScriptBuildStep.ImagePlatform.Linux
//            dockerRunParameters = "--rm"
//            dockerPull = true
//        }
        script {
            name = "Run unit tests"
            scriptContent = """ 
                #!/usr/bin/env bash
                source /etc/bashrc
                set -eo pipefail

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
                source /etc/bashrc
                set -eo pipefail

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
