# Conan

## Docker container 
The build container can be used to load all the other dependencies and add conan otherwise you are responsible yourself for converting the commands to the OS of your choice.
The build container can either be retrieved from the build / artifact server or be build manually by executing the ci/dockerfiles/linux/third-party-libs.Dockerfile 
- See [these instructions](../ci/dockerfiles/linux/README.md) for setting up the rest of the prerequisites: a container for the base build environment and one with the build environment including all third party dependencies.
``` 
docker run -it -v ./:c:/work  containers.deltares.nl/delft3d-dev/delft3d-buildtools-windows:vs2022-intel2024
set PATH="C:\Program Files (x86)\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.42.34433\bin\Hostx64\x64";%PATH%
cd work
```
## Prerequisites 
``` Install Git + Uv and activate venv python
rmdir /s /q .venv-windows
pip install uv
set UV_PROJECT_ENVIRONMENT=.venv-windows
uv sync 
.venv-windows\Scripts\activate
```
## Installation of conan

Add Environment variables for the connan repository login. IF you dont have access to these deltares repositories please only add the local and do not remove conancenter.
This will mean you have to build all the packages.
```
set CONAN_PASSWORD_DELTARESCONAN=YOUR_NEXUS_PASSWORD_HERE
set CONAN_LOGIN_USERNAME_DELTARESCONAN=YOUR_NEXUS_USERNAME_HERE
set CONAN_PASSWORD_DELTARESCONANDEV=YOUR_NEXUS_PASSWORD_HERE
set CONAN_LOGIN_USERNAME_DELTARESCONANDEV=YOUR_NEXUS_USERNAME_HERE
## Forward slash is important otherwise it intrepreted as \w and crashes during build
set CONAN_HOME=C:/work/.conan2_win

conan remote add local-recipes C:/work/tools/conan/ --type=local-recipes-index --force --index=0
conan remote add deltaresconan https://artifacts.deltares.nl/repository/conan-internal/ --force --index=2
conan remote add deltaresconandev https://artifacts.deltares.nl/repository/conan-dev/ --force --index=1
conan remote remove conancenter
```
Fix Conan settings to include 2024.2 version of intel compilers 
```
sed -i 's/"2024.1",/"2024.1","2024.2",/g' %CD%/.conan2_win/settings.yml
conan profile detect
```

## Install / building of packages
``` Release
conan install --profile:build=tools/conan/default_msvc --profile:host=tools/conan/default_msvc --build=missing --output-folder=../build/ conanfile.py 
```
``` Debug 
conan install --profile:build=tools/conan/debug_msvc --profile:host=tools/conan/debug_msvc --build=missing --output-folder=../build/ conanfile.py 
```

## Building with CMAKE


``` Environment variables
source /etc/bashrc
export PKG_CONFIG_PATH=/usr/local/lib/pkgconfig:$PKG_CONFIG_PATH
export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH
export CMAKE_PREFIX_PATH=/usr/local:$CMAKE_PREFIX_PATH
export CMAKE_INCLUDE_PATH=/usr/local/include:$CMAKE_INCLUDE_PATH
export CMAKE_LIBRARY_PATH=/usr/local/lib:$CMAKE_LIBRARY_PATH
```
``` Release
cmake ./src/cmake -G "Visual Studio 17 2022" -D CMAKE_BUILD_TYPE=Release -D CONFIGURATION_TYPE:STRING=all-testbench -B build_all-testbench -D CMAKE_INSTALL_PREFIX=build_all-testbench/install -D ENABLE_CODE_COVERAGE=true -D CMAKE_TOOLCHAIN_FILE=../build/build/generators/conan_toolchain.cmake -DCMAKE_POLICY_DEFAULT_CMP0091=NEW
cmake --build ./build_all-testbench -j --target install --config Release
```
``` Debug
cmake ./src/cmake -G "Visual Studio 17 2022" -D CMAKE_BUILD_TYPE=Debug -D CONFIGURATION_TYPE:STRING=all-testbench -B build_all-testbench -D CMAKE_INSTALL_PREFIX=build_all-testbench/install -D ENABLE_CODE_COVERAGE=true -D CMAKE_TOOLCHAIN_FILE=../build/build/generators/conan_toolchain.cmake -DCMAKE_POLICY_DEFAULT_CMP0091=NEW
cmake --build ./build_all-testbench -j --target install --config Debug

```
