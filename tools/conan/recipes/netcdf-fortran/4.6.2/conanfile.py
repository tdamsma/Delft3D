from conan import ConanFile
from conan.tools.cmake import (
    CMake,
    CMakeDeps,
    CMakeToolchain,
    cmake_layout,
)
from conan.tools.scm import Git


class NetcdfFortranRecipe(ConanFile):
    name = "netcdf-fortran"
    #version = "4.6.2"
    package_type = "library"

    license = "MIT"
    url = "https://github.com/Unidata/netcdf-fortran"
    description = "NetCDF Fortran library"
    topics = ("netcdf", "fortran", "hdf5", "mpi")

    settings = "os", "compiler", "build_type", "arch"
    options = {
        "shared": [True, False],
        "fPIC": [True, False],
    }
    default_options = {
        "shared": False,
        "fPIC": True,
    }

    # -------------------------------------------------------------------------
    # Dependency graph (THIS is where correctness matters)
    # -------------------------------------------------------------------------
    def requirements(self): 
      if self.settings.os == "Windows":
        self.requires(
          "hdf5/1.14.3",
          options={
            "parallel": True,
            "enable_fortran": False,
            "enable_cxx" : False,
            "shared": True,
            "with_zlib": True
          }
        )
        self.requires(
          "netcdf/4.9.3",
          options={
            "shared": True,
            #"fPIC": True,
            "netcdf4": True,
            "with_hdf5": True,
            "cdf5": True,
            "dap": False,
            "byterange": False,

          },
          transitive_libs=True,
          transitive_headers=True,
        )
        
      else: 
        self.requires(
            "hdf5/1.14.3",
            options={
              "parallel": True,
              "enable_fortran": True,
              "enable_cxx" : False
            },
            
        )
        self.requires(
            "netcdf/4.9.2",
            options={
              "shared": False,
              #"fPIC": True,
              "netcdf4": True,
              "with_hdf5": True,
              "cdf5": True,
              "dap": False,
              "byterange": False,
                     
            },
            transitive_headers=True,
          )
      
    # -------------------------------------------------------------------------
    def config_options(self):
      if self.settings.os == "Windows":    
        self.options.rm_safe("fPIC")

    # -------------------------------------------------------------------------
    def layout(self):
      cmake_layout(self)

    # -------------------------------------------------------------------------
    def source(self):
      git = Git(self)
      git.clone(
        url="https://github.com/Unidata/netcdf-fortran.git",
        target=".",
        args=["--branch", "v4.6.2", "--depth", "1"],
      )

    # -------------------------------------------------------------------------
    def generate(self):
      deps = CMakeDeps(self)
      deps.generate()

      tc = CMakeToolchain(self)

      # Ensure correct try-compile behavior (Conan bug workaround)
      tc.cache_variables["CMAKE_TRY_COMPILE_CONFIGURATION"] = str(
        self.settings.build_type
      )

      # Disable unnecessary components
      tc.variables["ENABLE_TESTS"] = False
      tc.variables["BUILD_EXAMPLES"] = False

      tc.generate()

    # -------------------------------------------------------------------------
    def build(self):
      cmake = CMake(self)
      cmake.configure()
      cmake.build()

    # -------------------------------------------------------------------------
    def package(self):
      cmake = CMake(self)
      cmake.install()

    # -------------------------------------------------------------------------
    def package_info(self):
      self.cpp_info.libs = ["netcdff"]
      