# C runtime loader — no Fortran, no precice headers
set(loader_source src/precice_loader.c)

add_library(precice_loader STATIC ${loader_source})

target_link_libraries(precice_loader PRIVATE no_compiler_warnings)

if (UNIX)
    target_link_libraries(precice_loader PRIVATE ${CMAKE_DL_LIBS})
endif()

set_target_properties(precice_loader PROPERTIES FOLDER third_party_open/precicef)

# Fortran module — depends on the loader for its bind(c) symbols
set(source_files src/precice.F90)

add_library(precicef STATIC ${source_files})

target_link_libraries(precicef PUBLIC precice_loader)

# Define how the files should be structured within Visual Studio
source_group(TREE ${CMAKE_CURRENT_SOURCE_DIR} FILES ${source_files} ${loader_source})
set_target_properties(precicef PROPERTIES FOLDER third_party_open/precicef)