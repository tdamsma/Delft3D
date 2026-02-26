package Delft3D.windows

import jetbrains.buildServer.configs.kotlin.*
import jetbrains.buildServer.configs.kotlin.buildFeatures.*
import jetbrains.buildServer.configs.kotlin.buildSteps.*
import jetbrains.buildServer.configs.kotlin.failureConditions.*
import Delft3D.template.*
import Delft3D.step.*

object WindowsBuild : BuildType({

    description = "CMake build."

    templates(
        TemplateMergeRequest,
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
        build_%product%/install/** => oss_artifacts_x64_%build.vcs.number%.zip!x64
        unit-test-report-windows.xml
    """.trimIndent()

    params {
        param("intel_fortran_compiler", "ifx")
        param("container.tag", "vs2022-intel2024")
        param("generator", """"Visual Studio 17 2022"""")
        param("enable_code_coverage_flag", "OFF")
        select("build_type", "Release", display = ParameterDisplay.PROMPT, options = listOf("Release", "Debug"))
        select("product", "auto-select", display = ParameterDisplay.PROMPT, options = listOf("auto-select", "all-testbench", "fm-suite", "d3d4-suite", "fm-testbench", "d3d4-testbench", "waq-testbench", "part-testbench", "rr-testbench", "wave-testbench", "swan-testbench"))
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
        checkoutDir = "ossbuild-win"
    }

    steps {
        mergeTargetBranch {
            dockerImage = "containers.deltares.nl/delft3d-dev/delft3d-buildtools-windows:%container.tag%"
            dockerImagePlatform = ScriptBuildStep.ImagePlatform.Windows
            dockerPull = true
        }
        python {
            name = "Determine product by branch prefix"
            command = file {
                filename ="""ci\\teamcity\\Delft3D\\windows\\scripts\\determineProduct.py"""
                scriptArguments = "%product% %teamcity.build.branch% %teamcity.build.branch.is_default% %build.vcs.number% %teamcity.pullRequest.source.branch%"
            }
            dockerImage = "containers.deltares.nl/delft3d-dev/delft3d-buildtools-windows:%container.tag%"
            dockerImagePlatform = PythonBuildStep.ImagePlatform.Windows
            dockerPull = true
        }
        script {
            name = "Add version attributes"
            workingDir = "./src/version_includes"
            scriptContent = """
                echo #define BUILD_NR "%build.vcs.number%" > checkout_info.h
                echo #define BRANCH "%teamcity.build.branch%" >> checkout_info.h
            """.trimIndent()
            dockerImage = "containers.deltares.nl/delft3d-dev/delft3d-buildtools-windows:%container.tag%"
            dockerImagePlatform = ScriptBuildStep.ImagePlatform.Windows
            dockerPull = true
        }
        script {
            name = "Build"
            scriptContent = """
              
                pip install uv
                set UV_PROJECT_ENVIRONMENT=.venv-windows
                uv sync 
                .venv-windows\Scripts\activate
                set CONAN_HOME=C:/work/.conan2_win
                
                conan remote add local-recipes C:/work/tools/conan/ --type=local-recipes-index --force --index=0
                conan remote add deltaresconan https://artifacts.deltares.nl/repository/conan-internal/ --force --index=2
                conan remote add deltaresconandev https://artifacts.deltares.nl/repository/conan-dev/ --force --index=1
                conan remote remove conancenter
                
                sed -i 's/"2024.1",/"2024.1","2024.2",/g' %CD%/.conan2_win/settings.yml
                conan profile detect
                
                conan install --profile:build=tools/conan/default_msvc --profile:host=tools/conan/default_msvc --build=missing --output-folder=../build/ conanfile.py 
                conan upload "*" -r deltaresconandev --confirm  
                                              
                call C:/set-env-vs2022.cmd
                cmake ./src/cmake -G %generator% -T fortran=%intel_fortran_compiler% -D CMAKE_BUILD_TYPE=%build_type% -D CONFIGURATION_TYPE:STRING=%product% -B build_%product% -D CMAKE_INSTALL_PREFIX=build_%product%/install -D ENABLE_CODE_COVERAGE=%enable_code_coverage_flag%  -D CMAKE_TOOLCHAIN_FILE=../build/build/generators/conan_toolchain.cmake
                if %%errorlevel%% neq 0 exit /b %%errorlevel%%

                cmake --build ./build_%product% -j --target install --config %build_type%
                if %%errorlevel%% neq 0 exit /b %%errorlevel%%

                ctest --test-dir ./build_%product% --build-config %build_type% --output-junit ../unit-test-report-windows.xml --output-on-failure
                if %%errorlevel%% neq 0 exit /b %%errorlevel%%
            """.trimIndent()
            dockerImage = "containers.deltares.nl/delft3d-dev/delft3d-buildtools-windows:%container.tag%"
            dockerImagePlatform = ScriptBuildStep.ImagePlatform.Windows
            dockerPull = true
            dockerRunParameters = "--memory %teamcity.agent.hardware.memorySizeMb%m --cpus %teamcity.agent.hardware.cpuCount%"
        }
    }

    features {
        xmlReport {
            reportType = XmlReport.XmlReportType.JUNIT
            rules = "+:unit-test-report-windows.xml"
        }
    }
})
