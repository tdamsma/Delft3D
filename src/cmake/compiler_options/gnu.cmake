# Set Intel compiler specific flags:
enable_language (Fortran)
set(src_root_dir ${CMAKE_SOURCE_DIR}/..)

if (WIN32)
    message(FATAL_ERROR "GNU compilers are not supported on Windows. CMake will exit.")
endif(WIN32)

if (UNIX)
    # Set optional flags:
    message(STATUS "Setting Fortran compiler flags in Unix")

    if(APPLE)
        # Apple's Clang does not provide an OpenMP runtime. OpenMP is used
        # by the GNU Fortran targets and is enabled there via openmp_flag
        # below; the C/C++ sides on macOS build without it rather than
        # requiring a separate libomp installation for a handful of
        # translation units.
        set(CMAKE_CXX_FLAGS_RELEASE  "-O2 -fPIC")
        set(CMAKE_C_FLAGS_RELEASE    "-O2 -fPIC")
        set(CMAKE_CXX_FLAGS_DEBUG    "-g -O0 -fPIC")
        set(CMAKE_C_FLAGS_DEBUG      "-g -O0 -fPIC")
    else()
        set(CMAKE_CXX_FLAGS_RELEASE  "-O2 -fPIC -fopenmp")
        set(CMAKE_C_FLAGS_RELEASE    "-O2 -fPIC -fopenmp")
        set(CMAKE_CXX_FLAGS_DEBUG    "-g -O0 -fPIC -fopenmp")
        set(CMAKE_C_FLAGS_DEBUG      "-g -O0 -fPIC -fopenmp")
    endif()
    # -ffree-line-length-none: some sources (e.g. long "use ... only:" lists)
    # exceed the previous 512-column cap; gfortran has no perf/behavior reason
    # to cap it, so drop the limit entirely rather than chase each long line.
    set(CMAKE_Fortran_FLAGS          "-O2 -fPIC -fopenmp -ffixed-line-length-132 -ffree-line-length-none -fallow-argument-mismatch")

    if(APPLE)
        # Unlike a full C/C++ compiler driver, gfortran's Fortran front end
        # does not predefine ANY platform macro (verified: no __APPLE__,
        # __linux__, __unix__, __MACH__ come out of `gfortran -cpp -dM -E`
        # on either platform). The tree is full of "#if defined(__linux__)
        # ... #else <windows-only code> #endif" guards (system_utils.F90
        # being the load-bearing example: ARCH/FILESEP/SHARED_LIB_EXTENSION)
        # that "worked" on Linux only because that toolchain is Intel ifx,
        # which does predefine __linux__ for Fortran. Under gfortran on
        # macOS every one of those guards silently fell into the Windows
        # branch. Define __APPLE__ explicitly so they take the (correct,
        # already-written) Unix-like path instead.
        set(CMAKE_Fortran_FLAGS      "${CMAKE_Fortran_FLAGS} -D__APPLE__")

        # -flto is deliberately absent here: gfortran 16.1.0 hits an
        # internal compiler error in the LTO streamer (write_symbol,
        # lto-streamer-out.cc:3096) on dflowfm_kernel's
        # fm_external_forcings_update.f90. Re-evaluate on a newer gfortran.
    else()
        # Same mechanism as the __APPLE__ block above, verified on Linux
        # too (gfortran's Fortran front end predefines no platform macro
        # for a real .F90 file on any UNIX platform -- only a stdin-fed
        # invocation, which dispatches through the generic C preprocessor
        # front end instead, shows __linux__/__APPLE__/etc.). Without this,
        # a GNU-Fortran build on Linux falls into the same
        # "#if defined(__linux__) ... #else <Windows-only> #endif" guard's
        # Windows branch that motivated the __APPLE__ fix (e.g.
        # system_utils.F90's FILESEP/ARCH/SHARED_LIB_EXTENSION). Dead code
        # on the ifx-on-Linux toolchain, which predefines __linux__ itself
        # and never includes this file.
        set(CMAKE_Fortran_FLAGS      "${CMAKE_Fortran_FLAGS} -D__linux__")
    endif()

    # Release optimization flags. Portable by default: CMake's built-in GNU
    # default for CMAKE_Fortran_FLAGS_RELEASE is already "-O3", and
    # per-config flags are appended after CMAKE_Fortran_FLAGS, so Release
    # builds are -O3; kept explicit here for clarity, not because it
    # changes anything.
    set(CMAKE_Fortran_FLAGS_RELEASE "-O3")

    # D3D_NATIVE_CPU_TUNING: opt-in machine-tuned Release codegen. Uses
    # -mcpu=native, which the compiler resolves to whatever CPU it is
    # actually being built on, rather than hard-coding a specific model --
    # so binaries built with this ON are optimized for, and only meant to
    # run on, the exact machine that built them (not portable to a
    # different machine, even of the same architecture family). OFF by
    # default so a plain `build.py --config <config> --build --build-type
    # Release` produces a portable binary.
    option(D3D_NATIVE_CPU_TUNING
        "Append -mcpu=native -funroll-loops to GNU Fortran Release flags \
for machine-tuned (non-portable) codegen. OFF by default so Release \
builds stay portable; turn ON only for binaries that will run on the \
exact machine that built them."
        OFF)
    if(D3D_NATIVE_CPU_TUNING)
        set(CMAKE_Fortran_FLAGS_RELEASE "${CMAKE_Fortran_FLAGS_RELEASE} -mcpu=native -funroll-loops")
        message(STATUS "D3D_NATIVE_CPU_TUNING=ON: Release Fortran flags include -mcpu=native -funroll-loops (machine-tuned, not portable to other machines)")
    endif()

    set(cpp_compiler_flags           "-std=c++17")
    set(dialect                      "-std=f2008")
    set(bounds                       "-fbounds-check")

    set(file_preprocessor_flag       "-cpp")
    set(traceback_flag               "-fbacktrace")
    set(automatic_local_variable_storage_flag "-fautomatic")
    set(heap_arrays_one_flag         "")
    set(heap_arrays_20_flag          "")
    set(heap_arrays_100_flag         "")
    set(real_size_64_flag            -fdefault-real-8 -fdefault-double-8)
    set(check_bounds_flag            "-fcheck=bounds")
    set(check_nobounds_flag          "")
    set(check_pointers_flag          "-fcheck=pointer")
    set(check_nopointers_flag        "")
    set(check_uninit_flag            "-finit-real=snan")
    set(check_stack_flag             "")
    set(openmp_flag                  "-fopenmp")
    set(generate_reentrancy_threaded_flag "-frecursive")
    set(floating_point_exception_flag "-ffpe-trap=invalid,zero,overflow")
    set(flush_to_zero_flag           "")

    set(CMAKE_POSITION_INDEPENDENT_CODE ON)
endif(UNIX)

set(qauto_threaded_flags "SHELL:${automatic_local_variable_storage_flag}" "SHELL:${generate_reentrancy_threaded_flag}")
set(waq_default_flags ${file_preprocessor_flag} ${traceback_flag})
