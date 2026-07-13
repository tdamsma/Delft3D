# Shared definitions

message(STATUS "swan mpi:")

# Don't put the Fortran modules of the SWAN MPI executable build in a central location
unset(CMAKE_Fortran_MODULE_DIRECTORY)

# Set directory which contains all source files
set(src_path ../src)
set(version_include_dir ${CMAKE_SOURCE_DIR}/../version_includes)

# Gather source files
set(headers ../include/swanout1_deltares.inc)

get_fortran_source_files(${src_path} swan_sourcefiles)
list(FILTER swan_sourcefiles EXCLUDE REGEX ".*HottifySWAN.f90$")
list(FILTER swan_sourcefiles EXCLUDE REGEX ".*swanhcat.for$")

set(executable_files ${swan_sourcefiles})

# Set the directory referring to the res folder
set(swan_path "${CMAKE_CURRENT_SOURCE_DIR}/..")
set(res_path ${swan_path}/res)

# Define executable
set(executable_name swan_mpi)
add_executable(${executable_name}   ${headers}
                                    ${rc_version_file}
                                    ${executable_files})

target_link_libraries(${executable_name} PRIVATE no_compiler_warnings)
# Set dependencies
if (WIN32)
    set(exe_dependencies netCDF::netcdff)

    target_link_libraries(${executable_name} PRIVATE ${exe_dependencies})

    include_directories("${CMAKE_CURRENT_SOURCE_DIR}/../include"
                        ${mpi_module_path}
                        ${version_include_dir})
    # Set linker properties
    message(STATUS "Setting linker properties in windows")
    target_link_directories(${executable_name}
                            PRIVATE
                            "${mpi_library_path}"
    )

    target_link_libraries(${executable_name} PRIVATE
                          "${mpi_fortran_library}"
    )

    # Set linker options
    message(STATUS "Setting target_link_options in windows")
    target_link_options(${executable_name} PRIVATE ${nologo_flag})
endif(WIN32)

if(UNIX)
    target_link_libraries(${executable_name} PRIVATE
         netCDF::netcdff
         MPI::MPI_Fortran)

    include_directories("${CMAKE_CURRENT_SOURCE_DIR}/../include"
                        ${version_include_dir}
                        ${CMAKE_BINARY_DIR}/fortran_module_dir)

    add_definitions(-DHAVE_CONFIG_H=1)
endif(UNIX)

# Define additional compilation flags
set_source_files_properties(${checkout_src_root}/third_party_open/swan/src/ocpids.F
                            ${checkout_src_root}/third_party_open/swan/src/swancom1.F
                            ${checkout_src_root}/third_party_open/swan/src/swanmain.F
                            ${checkout_src_root}/third_party_open/swan/src/swanparll.F
                            ${checkout_src_root}/third_party_open/swan/src/swmod2.F
                            PROPERTIES COMPILE_OPTIONS "${file_preprocessor_flag}")

# Set additional compilation properties, specific for Debug mode
target_compile_options(${executable_name} PRIVATE "SHELL:$<$<CONFIG:Debug>:${check_nopointers_flag}>")

# Set additional compilation flags to match with Deltares-SWAN outside Delft3D
if (WIN32)
    target_compile_options(${executable_name} PRIVATE
                                                  "${avx2_flag}"
                                                  "${traceback_flag}"
                                                  "${heap_arrays_20_flag}"
                                                  "${automatic_local_variable_storage_flag}"
                                                  "${floating_point_source_flag}"
                                                  "${floating_point_speculation_safe_flag}")
endif(WIN32)
if (UNIX)
    target_compile_options(${executable_name} PRIVATE
                                                  "SHELL:${avx2_flag}")
endif(UNIX)

# SWAN's fixed-form sources carry inline version-history annotations past
# column 72, tolerated (warning-only) by Intel's 132-column default but a hard
# syntax error for gfortran once those columns become significant. Restrict
# this target back to the genuine F77 72-column limit under gfortran only.
target_compile_options(${executable_name} PRIVATE
    "$<$<AND:$<COMPILE_LANGUAGE:Fortran>,$<Fortran_COMPILER_ID:GNU>>:-ffixed-line-length-72>")

# This target never opts into OpenMP via ${openmp_flag} on Intel/Windows (only
# swan_omp does), so "!$OMP" sentinels are inert there. gnu.cmake's
# CMAKE_Fortran_FLAGS unconditionally adds -fopenmp for GNU though, which
# activates an MPI-only STPNOW()/RETURN sitting inside a "!$OMP DO" loop --
# gfortran correctly rejects that as branching out of a parallel region.
# Turn OpenMP back off here to match the Intel/Windows behavior this MPI-only
# target was written for.
target_compile_options(${executable_name} PRIVATE
    "$<$<AND:$<COMPILE_LANGUAGE:Fortran>,$<Fortran_COMPILER_ID:GNU>>:-fno-openmp>")

# Define preprocessor definitions
if (WIN32)
    target_compile_definitions(${executable_name} PRIVATE "WIN32;USE_MPI;SWANEXE")
endif(WIN32)

if (UNIX)
    target_compile_definitions(${executable_name} PRIVATE "USE_MPI;SWANEXE")
endif(UNIX)

# Define how the files should be structured within Visual Studio
source_group(TREE ${checkout_src_root}/third_party_open/swan FILES ${executable_files})
set_target_properties (${executable_name} PROPERTIES FOLDER third_party_open/swan_mpi)

# Set post-build step
set(install_dir ${CMAKE_BINARY_DIR})
set(build_dir ${CMAKE_BINARY_DIR})

install(TARGETS ${executable_name} RUNTIME  DESTINATION bin)

    install(PROGRAMS ../scripts/swan.${platform_extension}  DESTINATION bin)
