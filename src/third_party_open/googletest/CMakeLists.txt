if(WIN32)
    # On Windows, build Google Test from source
    set(BUILD_GMOCK OFF)
    set(INSTALL_GTEST OFF)
    set(gtest_force_shared_crt ON)

    add_subdirectory(googletest-main)

    set_target_properties(gtest PROPERTIES FOLDER third_party_open/googletest)
    set_target_properties(gtest_main PROPERTIES FOLDER third_party_open/googletest)
else()
    # On Linux, use CMake's built-in FindGTest to find system-installed Google Test.
    # GLOBAL is required so the gtest/gtest_main ALIAS targets below correctly
    # propagate GTest's usage requirements (include dirs) to consumers in
    # unrelated directory scopes (e.g. Homebrew GTest on macOS, whose headers
    # are not on the compiler's default search path like system-installed
    # GTest on Linux typically is).
    find_package(GTest REQUIRED GLOBAL)
    if(NOT TARGET gtest)
        add_library(gtest ALIAS GTest::gtest)
        add_library(gtest_main ALIAS GTest::gtest_main)
    endif()
endif()
