set(library_name io_netcdf)


# Note that the CMAKE_CURRENT_SOURCE_DIR has a path to THIS CMakeLists location
set(fortran_version_file ${CMAKE_CURRENT_SOURCE_DIR}/src/io_netcdf_version.F90)
set(version_include_dir ${CMAKE_SOURCE_DIR}/../version_includes)
set(rc_dir ${CMAKE_CURRENT_SOURCE_DIR}/version)
set(rc_version_file ${rc_dir}/io_netcdf_version_number.rc)

###########
# IO_NETCDF
###########

create_target(${library_name} ${CMAKE_CURRENT_SOURCE_DIR} src_dir src resource_files ${fortran_version_file})

# Create the folder structure in vfproj
set_target_properties (${library_name} PROPERTIES FOLDER utils_lgpl/io_netcdf)

target_include_directories(${library_name}  PRIVATE ${version_include_dir} ${rc_dir})

target_link_libraries(${library_name} PRIVATE
                        deltares_common
                        io_netcdf_data
                        fortrangis
)
target_link_libraries(${library_name} PUBLIC
                        netCDF::netcdff
)

if(UNIX)
    target_compile_definitions(${library_name} PRIVATE LINUX64)
endif(UNIX)

if (WIN32)
    target_compile_definitions(${library_name} PRIVATE WIN64)
    target_compile_options(${library_name} PRIVATE "${heap_arrays_one_flag}")
endif(WIN32)

set(src_path src)
# Set additional compilation properties
set_source_files_properties(${fortran_version_file}
                            ${src_path}/coordinate_reference_system.F90
                            ${src_path}/io_ugrid.F90
                            PROPERTIES COMPILE_OPTIONS "${file_preprocessor_flag}")


###############
# IO_NETCDF_DLL
###############
string(TOUPPER ${CONFIGURATION_TYPE} configuration_type)
# Configurations that would otherwise build io_netcdf_dll (kept as a single
# list so the "build it" and "explain why it was skipped" branches below
# can't drift apart).
set(io_netcdf_dll_configs
    DFLOWFM DELFT3D4 FM-SUITE D3D4-SUITE ALL ALL-TESTBENCH FM-TESTBENCH TOOLS)
list(FIND io_netcdf_dll_configs ${configuration_type} io_netcdf_dll_config_index)
if (io_netcdf_dll_config_index EQUAL -1)
    set(io_netcdf_dll_wanted_for_config FALSE)
else()
    set(io_netcdf_dll_wanted_for_config TRUE)
endif()

if ( NOT (CMAKE_Fortran_COMPILER_ID MATCHES "GNU") AND io_netcdf_dll_wanted_for_config )
    # io_netcdf_api.F90 exposes several BIND(C) functions whose dummy
    # arguments are of type t_ug_meta / t_ug_charinfo (utils_lgpl/io_netcdf/
    # packages/io_netcdf_data/src/ug_meta.f90, ug_charinfo.f90). Those types
    # have character(len=N>1) components, which the Fortran standard does
    # not consider C-interoperable; gfortran enforces this strictly and
    # rejects the BIND(C) procedures, whereas Intel Fortran (the supported
    # toolchain on both Linux and Windows) accepts it as a lenient
    # extension. Making the types genuinely interoperable would mean
    # reworking them to fixed character(kind=c_char) arrays, which ripple
    # through their many ordinary (non-interop) uses in
    # io_netcdf.f90/io_ugrid.F90 -- out of scope for the macOS port right
    # now. This C-callable DLL (for C/C#/Python bindings) is a leaf target
    # nothing else in this repo depends on, so skip it whenever the
    # Fortran compiler is GNU (gfortran) -- macOS (always gfortran) and
    # any GNU-Fortran build on Linux alike -- rather than leave "all"
    # permanently broken; revisit if/when this target needs to support
    # gfortran's stricter interoperability checking.
    set(library_name io_netcdf_dll)
    set(library_renamed libio_netcdf.so)
    # Add dynamic io_netcdf library
    add_rc_object_library(${library_name} "${rc_version_file}" "${version_include_dir};${rc_dir}")
    add_library(${library_name} SHARED ${src_path}/../../io_netcdf_api/io_netcdf_api.F90)
    target_link_libraries(${library_name} PRIVATE ${library_name}_rc)
    include_directories(${version_include_dir})

    set(oss_dependencies io_netcdf)
    target_link_libraries(${library_name} PRIVATE ${oss_dependencies})

    # Create the folder structure in vfproj
    source_group(TREE ${CMAKE_CURRENT_SOURCE_DIR} FILES ${src_path}/io_netcdf_api.F90)
    set_target_properties(${library_name} PROPERTIES FOLDER utils_lgpl/io_netcdf)
    set_target_properties(${library_name} PROPERTIES OUTPUT_NAME io_netcdf)
    if(WIN32)
        # Use a distinct name for the DLL import library so it does not
        # overwrite the static io_netcdf.lib that other targets link against.
        set_target_properties(${library_name} PROPERTIES ARCHIVE_OUTPUT_NAME io_netcdf_dll)
    endif()
    if(UNIX)
        set_target_properties(${library_name} PROPERTIES PREFIX "")
    endif()

    install(TARGETS ${library_name} RUNTIME DESTINATION bin
                                    LIBRARY DESTINATION lib
    )
elseif (CMAKE_Fortran_COMPILER_ID MATCHES "GNU" AND io_netcdf_dll_wanted_for_config)
    message(STATUS
        "io_netcdf: SKIPPING io_netcdf_dll for this configuration "
        "(CMAKE_Fortran_COMPILER_ID=${CMAKE_Fortran_COMPILER_ID}, "
        "CONFIGURATION_TYPE=${CONFIGURATION_TYPE}). io_netcdf_api.F90's "
        "BIND(C) procedures pass derived types with "
        "CHARACTER(len>1) components (t_ug_meta/t_ug_charinfo), which "
        "gfortran correctly rejects as non-interoperable and Intel Fortran "
        "accepts only as a lenient extension -- see the comment above this "
        "message for the full explanation. Nothing else in this repository "
        "links io_netcdf_dll (dflowfm/dimr/etc. use the ordinary io_netcdf "
        "Fortran target instead), so this build is not missing a "
        "dependency -- but no C-callable libio_netcdf shared library is "
        "produced or installed for external C/C#/Python bindings on this "
        "configuration. Rework ug_meta.f90/ug_charinfo.f90 to use "
        "interoperable character(kind=c_char) arrays to lift this "
        "restriction.")
endif()
