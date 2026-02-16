package Delft3D.linux

import jetbrains.buildServer.configs.kotlin.*
import jetbrains.buildServer.configs.kotlin.buildFeatures.*
import jetbrains.buildServer.configs.kotlin.buildSteps.*
import Delft3D.template.*
import Delft3D.step.*
import Delft3D.linux.containers.*

object LinuxBuild2D3DSP : BuildType({

    description = "CMake build 2D3D single-precision. This is necessary for Delft3D 4."

    templates(
        TemplateMergeRequest,
        TemplateDetermineProduct,
        TemplatePublishStatus,
        TemplateMonitorPerformance,
        TemplateDockerRegistry
    )

    name = "Build 2D3D single-precision"
    buildNumberPattern = "%product%: %build.vcs.number%"

    allowExternalStatus = true
    artifactRules = """
        #teamcity:symbolicLinks=as-is
        build_flow2d3d/install/lib/libflow2d3d_sp.so => oss_artifacts_lnx64_%build.vcs.number%.tar.gz!lnx64/lib
    """.trimIndent()

    outputParams {
        exposeAllParameters = false
    }

    params {
        param("generator", """"Unix Makefiles"""")
        param("product", "auto-select")
        select("build_type", "%dep.${LinuxThirdPartyLibs.id}.build_type%", display = ParameterDisplay.PROMPT, options = listOf("Release", "RelWithDebInfo", "Debug"))
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
            name = "Set single-precision"
            workingDir = "./src/utils_lgpl/deltares_common/scripts"
            scriptContent = """
                #!/usr/bin/env bash
                ./singleprecision.sh
            """.trimIndent()
        }
        script {
            name = "Build"
            conditions {
                matches("product", """^(d3d4-(suite|testbench))|(all-testbench)$""")
            }
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
                set -eo pipefail
                export PKG_CONFIG_PATH=/usr/local/lib/pkgconfig:${'$'}PKG_CONFIG_PATH
                export LD_LIBRARY_PATH=/usr/local/lib:${'$'}LD_LIBRARY_PATH
                export CMAKE_PREFIX_PATH=/usr/local:${'$'}CMAKE_PREFIX_PATH
                export CMAKE_INCLUDE_PATH=/usr/local/include:${'$'}CMAKE_INCLUDE_PATH
                export CMAKE_LIBRARY_PATH=/usr/local/lib:${'$'}CMAKE_LIBRARY_PATH
                cmake -S ./src/cmake -G %generator% -D CONFIGURATION_TYPE:STRING=flow2d3d -D CMAKE_BUILD_TYPE=%build_type% -B build_flow2d3d -D CMAKE_INSTALL_PREFIX=build_flow2d3d/install -D CMAKE_TOOLCHAIN_FILE=../build/build/%build_type%/generators/conan_toolchain.cmake
                cmake --build build_flow2d3d --parallel --config %build_type%
            """.trimIndent()
            dockerImage = "containers.deltares.nl/delft3d-dev/delft3d-third-party-libs:%dep.${LinuxThirdPartyLibs.id}.env.IMAGE_TAG%"
            dockerImagePlatform = ScriptBuildStep.ImagePlatform.Linux
            dockerRunParameters = "--rm"
            dockerPull = true
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
