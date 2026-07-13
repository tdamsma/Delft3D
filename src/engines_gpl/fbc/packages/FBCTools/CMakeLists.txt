# CMake settings
cmake_minimum_required(VERSION 3.10.0)

set(CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/cmake/macros)

# Project name
project(FBCTools)

if(${CMAKE_SYSTEM_NAME} MATCHES "Linux")
  # when makeing a relocatable / standalone install make sure the libraries can be found in the install dir (or $ORIGIN)
  set(CMAKE_INSTALL_RPATH "$ORIGIN:$ORIGIN/../lib")
  set(CMAKE_INSTALL_RPATH_USE_LINK_PATH TRUE)
endif()

set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Enable position independent code for libraries
set(CMAKE_POSITION_INDEPENDENT_CODE TRUE)

# Enable OpenMP
if(APPLE AND NOT OpenMP_CXX_FOUND)
    # Apple Clang has no bundled OpenMP runtime/headers, and CMake's FindOpenMP
    # cannot auto-detect the right flags for it (its "-Xclang -fopenmp" compile
    # test fails with no hints), unlike GNU/Intel on Linux. Point it at
    # Homebrew's libomp explicitly so find_package(OpenMP) below succeeds for
    # CXX the same way it already does for Fortran.
    find_program(BREW_EXECUTABLE brew)
    if(BREW_EXECUTABLE)
        execute_process(COMMAND ${BREW_EXECUTABLE} --prefix libomp
                         OUTPUT_VARIABLE LIBOMP_PREFIX
                         OUTPUT_STRIP_TRAILING_WHITESPACE)
    endif()
    if(NOT LIBOMP_PREFIX)
        # No `brew` on PATH (or it failed): fall back to the default
        # Homebrew prefix for Apple Silicon. A custom Homebrew prefix
        # without `brew` on PATH is not auto-detectable here; set
        # LIBOMP_PREFIX on the CMake command line in that case.
        set(LIBOMP_PREFIX "/opt/homebrew/opt/libomp")
    endif()
    set(OpenMP_CXX_FLAGS "-Xpreprocessor -fopenmp -I${LIBOMP_PREFIX}/include" CACHE STRING "" FORCE)
    set(OpenMP_CXX_LIB_NAMES "omp" CACHE STRING "" FORCE)
    set(OpenMP_C_FLAGS "-Xpreprocessor -fopenmp -I${LIBOMP_PREFIX}/include" CACHE STRING "" FORCE)
    set(OpenMP_C_LIB_NAMES "omp" CACHE STRING "" FORCE)
    set(OpenMP_omp_LIBRARY "${LIBOMP_PREFIX}/lib/libomp.dylib" CACHE FILEPATH "" FORCE)
endif()
find_package(OpenMP)
if(OpenMP_FOUND)
    add_compile_options("SHELL:${OpenMP_CXX_FLAGS}")
endif()

# Boost C++, it is a required package, if not found configuration will abort
set(Boost_USE_RELEASE_LIBS ON)

if(WIN32)
  set(Boost_USE_STATIC_LIBS OFF)
  set(Boost_DIR ${CMAKE_SOURCE_DIR}/../third_party_open/boost/boost_1_90_0/lib/cmake/Boost-1.90.0)
  find_package(Boost 1.90 CONFIG REQUIRED COMPONENTS filesystem date_time)
endif()

if(LINUX OR APPLE)
   # On APPLE, Homebrew's boost (1.90) and xerces-c CMake config packages are
   # discovered via CMake's default Homebrew-aware CMAKE_SYSTEM_PREFIX_PATH,
   # so this mirrors the Linux find_package calls unchanged. date_time is
   # requested too (APPLE-only need, see LINK_LIBRARIES below): Homebrew's
   # non-standard prefix means bare "-lboost_date_time" can't be found by the
   # linker without the imported target's search path.
   if(APPLE)
       find_package(Boost 1.90 REQUIRED COMPONENTS filesystem date_time)
   else()
       find_package(Boost 1.90 REQUIRED COMPONENTS filesystem)
   endif()
   find_package(XercesC REQUIRED)
   if(XercesC_FOUND)
      message(STATUS "Found Xerces-C: ${XercesC_VERSION}")
      include_directories(${XercesC_INCLUDE_DIRS})
   else()
      message(FATAL_ERROR "Xerces-C not found")
   endif()
endif()

# Set warning levels
if(MSVC)
    set(CMAKE_CXX_FLAGS_DEBUG "${CMAKE_CXX_FLAGS_DEBUG} /W3")
    set(CMAKE_C_FLAGS_DEBUG   "${CMAKE_C_FLAGS_DEBUG} /W3")
elseif(APPLE)
    # No raw "-lboost_..." here (unlike Linux below): Homebrew's non-standard
    # prefix means these can't be found without an -L path, which the
    # Boost::filesystem/Boost::date_time imported targets provide instead
    # (see LINK_LIBRARIES below).
    set(CMAKE_CXX_FLAGS_DEBUG "${CMAKE_CXX_FLAGS_DEBUG} -Wall -std=c++11")
    set(CMAKE_C_FLAGS_DEBUG   "${CMAKE_C_FLAGS_DEBUG} -Wall -std=c++11")
else()
    set(CMAKE_CXX_FLAGS_DEBUG "${CMAKE_CXX_FLAGS_DEBUG} -Wall -std=c++11 -lboost_filesystem -lboost_date_time")
    set(CMAKE_C_FLAGS_DEBUG   "${CMAKE_C_FLAGS_DEBUG} -Wall -std=c++11 -lboost_filesystem -lboost_date_time")
endif()

if(MSVC)
    set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} /W0")
    set(CMAKE_C_FLAGS_RELEASE   "${CMAKE_C_FLAGS_RELEASE} /W0")
elseif(APPLE)
    set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} -std=c++11")
    set(CMAKE_C_FLAGS_RELEASE   "${CMAKE_C_FLAGS_RELEASE} -std=c++11")
else()
    set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} -std=c++11 -lboost_filesystem -lboost_date_time")
    set(CMAKE_C_FLAGS_RELEASE   "${CMAKE_C_FLAGS_RELEASE} -std=c++11 -lboost_filesystem -lboost_date_time")
endif()

set (version_include_dir ${PROJECT_SOURCE_DIR}/../../version/)

# Add project include directories

include_directories("${CMAKE_SOURCE_DIR}/../version_includes")
include_directories("${version_include_dir}")
include_directories("${PROJECT_SOURCE_DIR}/src")
include_directories("${PROJECT_SOURCE_DIR}/src/dataBinding")
include_directories("${PROJECT_SOURCE_DIR}/src/optimizationProblem")
include_directories("${PROJECT_SOURCE_DIR}/src/postprocess")
include_directories("${PROJECT_SOURCE_DIR}/src/schematization")
include_directories("${PROJECT_SOURCE_DIR}/src/timeseries")
include_directories("${PROJECT_SOURCE_DIR}/src/utilities")


if(${CMAKE_SYSTEM_NAME} MATCHES "Windows")
    include_directories("${PROJECT_SOURCE_DIR}/thirdParty/xsd/xsd-3.3.0-i686-windows/libxsd")
    include_directories("${PROJECT_SOURCE_DIR}/thirdParty/xerces/xerces-c-3.1.1-x86_64-windows-vc-10.0/include")
    link_directories("${PROJECT_SOURCE_DIR}/thirdParty/xerces/xerces-c-3.1.1-x86_64-windows-vc-10.0/lib/")
elseif(${CMAKE_SYSTEM_NAME} MATCHES "Linux" OR APPLE)
    # xsd's libxsd runtime support headers are header-only/portable C++;
    # no macOS-specific vendored copy is needed, reuse the Linux one.
    include_directories("${PROJECT_SOURCE_DIR}/thirdParty/xsd/xsd-3.3.0-x86_64-linux-gnu/libxsd")
endif()

# Add source folder (FBCTools_static target)
add_subdirectory(src)


if(${CMAKE_SYSTEM_NAME} MATCHES "Windows")
# Define FBCTools executable
    add_executable(FBCTools src/rtcTools.cpp ${version_include_dir}/fbc_version.rc)

# Define BMI library
    add_library(FBCTools_BMI SHARED src/rtcToolsBMI.cpp src/bmi.h ${version_include_dir}/fbc_version.rc)

elseif(${CMAKE_SYSTEM_NAME} MATCHES "Linux" OR APPLE)
# Define FBCTools executable
    add_executable(FBCTools src/rtcTools.cpp)

# Define BMI library
    add_library(FBCTools_BMI SHARED src/rtcToolsBMI.cpp src/bmi.h)
endif()

# Link dependencies
if(${CMAKE_SYSTEM_NAME} MATCHES "Windows")
    set(LINK_LIBRARIES FBCTools_static
                       xerces-c_3
                       Boost::filesystem
                       Boost::date_time)
elseif(${CMAKE_SYSTEM_NAME} MATCHES "Linux")
    set(LINK_LIBRARIES FBCTools_static
                       ${XercesC_LIBRARIES}
                       dl
                       boost_date_time
                       boost_filesystem)
elseif(APPLE)
    # dlopen/dlsym live in libSystem on macOS: no standalone "dl" library to
    # link. Unlike Linux, Homebrew's boost isn't on the linker's default
    # search path (non-standard prefix), so bare "-lboost_filesystem"/
    # "-lboost_date_time" fail to resolve at actual link time (they also leak
    # in via CMAKE_CXX_FLAGS_RELEASE/_DEBUG above, which is where Linux gets
    # away with the raw names). Use the imported targets instead, which carry
    # the right -L path with them.
    set(LINK_LIBRARIES FBCTools_static
                       ${XercesC_LIBRARIES}
                       Boost::date_time
                       Boost::filesystem)
endif()

if(OpenMP_CXX_FOUND)
    set(LINK_LIBRARIES ${LINK_LIBRARIES} OpenMP::OpenMP_CXX)
endif()

target_link_libraries(FBCTools PRIVATE ${LINK_LIBRARIES})
target_link_libraries(FBCTools_BMI PRIVATE ${LINK_LIBRARIES})
#target_link_libraries(FBCTools_BMI PRIVATE ${Boost_LIBRARIES})
# Define how the files should be structured within Visual Studio
source_group(TREE ${CMAKE_CURRENT_SOURCE_DIR} FILES ${source_files})
set_target_properties (FBCTools PROPERTIES FOLDER engines_gpl/fbc)
set_target_properties (FBCTools_BMI PROPERTIES FOLDER engines_gpl/fbc)

#------------------------------
# configure installer for linux
set(FBC_SUPPORT_FILES
  ${PROJECT_SOURCE_DIR}/xsd/pi_diag.xsd
  ${PROJECT_SOURCE_DIR}/xsd/pi_modelparameters.xsd
  ${PROJECT_SOURCE_DIR}/xsd/pi_run.xsd
  ${PROJECT_SOURCE_DIR}/xsd/pi_sharedtypes.xsd
  ${PROJECT_SOURCE_DIR}/xsd/pi_state.xsd
  ${PROJECT_SOURCE_DIR}/xsd/pi_timeseries.xsd
  ${PROJECT_SOURCE_DIR}/xsd/rtcDataConfig.xsd
  ${PROJECT_SOURCE_DIR}/xsd/rtcObjectiveConfig.xsd
  ${PROJECT_SOURCE_DIR}/xsd/rtcRuntimeConfig.xsd
  ${PROJECT_SOURCE_DIR}/xsd/rtcSharedTypes.xsd
  ${PROJECT_SOURCE_DIR}/xsd/rtcStateConfig.xsd
  ${PROJECT_SOURCE_DIR}/xsd/rtcToolsConfig.xsd
  ${PROJECT_SOURCE_DIR}/xsd/treeVector.xsd
)
  install(FILES ${FBC_SUPPORT_FILES} DESTINATION share/drtc)
  install(TARGETS FBCTools RUNTIME DESTINATION bin)
  install(TARGETS FBCTools_BMI RUNTIME DESTINATION bin
                               LIBRARY DESTINATION lib
  )
  if(WIN32)
     install(FILES ${PROJECT_SOURCE_DIR}/thirdParty/xerces/xerces-c-3.1.1-x86_64-windows-vc-10.0/bin/xerces-c_3_1.dll DESTINATION bin)
     if(NOT Boost_USE_STATIC_LIBS)
        get_target_property(BOOST_FILESYSTEM_DLL Boost::filesystem LOCATION)
        get_target_property(BOOST_DATETIME_DLL Boost::date_time LOCATION)
        install(FILES ${BOOST_FILESYSTEM_DLL} ${BOOST_DATETIME_DLL} DESTINATION bin)
     endif()
  endif()
