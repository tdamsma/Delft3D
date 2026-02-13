# NetCDF
find_package(netcdf REQUIRED)
find_package(netcdf-fortran REQUIRED)

if(UNIX AND NOT APPLE)
    message(STATUS "Defining linux macro")
    add_compile_definitions(linux)
endif()