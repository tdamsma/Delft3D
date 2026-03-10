# Conan

## Docker container 
The build container can be used to load all the other dependencies and add conan otherwise you are responsible yourself for converting the commands to the OS of your choice.
The build container can either be retrieved from the build / artifact server or be build manually by executing the ci/dockerfiles/linux/third-party-libs.Dockerfile 
- See [these instructions](../ci/dockerfiles/linux/README.md) for setting up the rest of the prerequisites: a container for the base build environment and one with the build environment including all third party dependencies.
``` 
docker run -it -v ./:/work  containers.deltares.nl/delft3d-dev/delft3d-third-party-libs:YOUR_BRANCH_HERE
cd /work
```
## Prerequisites 
``` Install Git + Uv and activate venv python
dnf install git -y
wget -qO- https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env
uv sync 
source .venv/bin/activate
```
## Installation of conan

Add Environment variables for the connan repository login. IF you dont have access to these deltares repositories please only add the local and do not remove conancenter.
This will mean you have to build all the packages.
```
export CONAN_PASSWORD_DELTARESCONAN='YOUR_NEXUS_PASSWORD'
export CONAN_LOGIN_USERNAME_DELTARESCONAN=YOUR_NEXUS_USERNAME
export CONAN_PASSWORD_DELTARESCONANDEV='YOUR_NEXUS_PASSWORD'
export CONAN_LOGIN_USERNAME_DELTARESCONANDEV=YOUR_NEXUS_USERNAME

conan remote add local-recipes /work/tools/conan/ --type=local-recipes-index --force --index=0
conan remote add deltaresconan https://artifacts.deltares.nl/repository/conan-internal/ --force --index=2
conan remote add deltaresconandev https://artifacts.deltares.nl/repository/conan-dev/ --force --index=1
conan remote remove conancenter
```
Fix Conan settings to include 2024.2 version of intel compilers 
```
sed -i 's/"2024.1",/"2024.1","2024.2",/g' ~/.conan2/settings.yml
conan profile detect
```

## Install / building of packages
``` Release
conan install --profile:build=tools/conan/default_linux --profile:host=tools/conan/default_linux --build=missing --output-folder=./build/ conanfile.py 
```
``` Debug 
conan install --profile:build=tools/conan/debug_linux --profile:host=tools/conan/debug_linux --build=missing --output-folder=./build/ conanfile.py 
```

## Building with CMAKE


```
source /etc/bashrc
export PKG_CONFIG_PATH=/usr/local/lib/pkgconfig:$PKG_CONFIG_PATH
export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH
export CMAKE_PREFIX_PATH=/usr/local:$CMAKE_PREFIX_PATH
export CMAKE_INCLUDE_PATH=/usr/local/include:$CMAKE_INCLUDE_PATH
export CMAKE_LIBRARY_PATH=/usr/local/lib:$CMAKE_LIBRARY_PATH
```
``` Release
cmake -S ./src/cmake -G "Unix Makefiles" -D CONFIGURATION_TYPE:STRING=all-testbench -D CMAKE_BUILD_TYPE=Release -B build_all-testbench -D CMAKE_INSTALL_PREFIX=build_all-testbench/install -DCMAKE_TOOLCHAIN_FILE=../build/build/Release/generators/conan_toolchain.cmake
cmake --build build_all-testbench --parallel --config Release
```
``` Debug
cmake -S ./src/cmake -G "Unix Makefiles" -D CONFIGURATION_TYPE:STRING=all-testbench -D CMAKE_BUILD_TYPE=Debug -B build_all-testbench -D CMAKE_INSTALL_PREFIX=build_all-testbench/install -DCMAKE_TOOLCHAIN_FILE=../build/build/Debug/generators/conan_toolchain.cmake 
cmake --build build_all-testbench --parallel --config Release
```