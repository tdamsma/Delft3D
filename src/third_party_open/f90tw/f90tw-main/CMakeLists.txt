project(f90tw LANGUAGES CXX Fortran)

set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# f90 line length; TODO handle compilers other than GNU
set(CMAKE_Fortran_FORMAT FREE)
if(CMAKE_Fortran_COMPILER_ID STREQUAL "GNU")
    # Quote ${CMAKE_Fortran_FLAGS}: unquoted, CMake splits it into a
    # semicolon-separated list rather than a single string, so
    # CMAKE_Fortran_FLAGS ends up holding a multi-element list value
    # instead of one space-joined flag string. A consumer that expects a
    # plain flag string (e.g. one that shells it out verbatim) can then
    # mis-tokenize it -- observed as "-ffree-line-length-none" being
    # invoked as its own shell command ("not found").
    set(CMAKE_Fortran_FLAGS "${CMAKE_Fortran_FLAGS} -ffree-line-length-none")
endif()

add_subdirectory(f90tw)

message(STATUS "f90tw_INCLUDE_DIR is ${f90tw_INCLUDE_DIR}")
