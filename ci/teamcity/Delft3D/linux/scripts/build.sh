#!/usr/bin/env bash
set -eo pipefail
source /opt/bashrc

while [[ $# -gt 0 ]]; do
    case "$1" in
        --generator)
            GENERATOR="$2"
            shift 2
            ;;
        --product)
            PRODUCT="$2"
            shift 2
            ;;
        --build-type)
            BUILD_TYPE="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

https://artifacts.deltares.nl/repository/conan-internal/
 
  robot-teamcity-delft3d-conan@deltares.nl

  parking.displease.oval.duvet.subway 

  #conan build --build=missing tools/conan/recipes/netcdf-fortran.py
  #conan build tools/conan/recipes/netcdf-fortran.py



pip3 install conan
conan remote add deltaresconan "https://artifacts.deltares.nl/repository/conan-internal/"
conan remote add deltaresconandev "https://artifacts.deltares.nl/repository/conan-dev/"
conan remote remove conancenter
conan editable add tools/conan/recipes/netcdf-fortran/4.6.2
conan create tools/conan/recipes/netcdf-fortran/4.6.2/ --build=missing
conan profile detect
conan install --build=missing conanfile.py
conan upload netcdf-fortran/4.6.2 -r deltaresconandev --confirm
conan upload "*" -r deltaresconandev -c

cmake -S ./src/cmake -G "${GENERATOR}" -D CONFIGURATION_TYPE:STRING="${PRODUCT}" -D CMAKE_BUILD_TYPE="${BUILD_TYPE}" -B "build_${PRODUCT}" -D CMAKE_INSTALL_PREFIX="build_${PRODUCT}/install"
cmake --build "build_${PRODUCT}" --parallel --config "${BUILD_TYPE}"
