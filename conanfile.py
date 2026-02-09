from conan import ConanFile
from conan.tools.cmake import cmake_layout, CMakeToolchain


class Delft3DRecipe(ConanFile):
    settings = "os", "compiler", "build_type", "arch"
    generators = "CMakeDeps"

    def requirements(self):
      self.requires("netcdf-fortran/4.6.2")
      # 
      # self.requires(
      #   "hdf5/1.14.6",
      #   options={
      #     "parallel": True,
      #     "enable_fortran": True
      #   },
      # )
      # 
      # self.requires(
      #   "netcdf/4.8.1",
      #   options={
      #     "shared": False,
      #     "fPIC": True,
      #     "netcdf4": True,
      #     "with_hdf5": True,
      #     "cdf5": True,
      #     "dap": False,
      #     "byterange": False,
      # 
      #   },
      #   transitive_headers=True,
      # )

    def layout(self):
        cmake_layout(self)
        
    def configure(self):
      self.options['example'].example =False
      # self.options["netcdf-c"].parallel = True
      # self.options["netcdf-c"].mpi = True
      # self.options["netcdf-c"].hdf5 = True
      # self.options["netcdf-c"].shared = False
      # 
      # self.options["hdf5"].enable_parallel = True
      # self.options["hdf5"].shared = True
      # self.options["hdf5"].mpi = True
      
    def generate(self):
        tc = CMakeToolchain(self)
        # Required for parallel HDF5 detection
        # tc.cache_variables["HDF5_PREFER_PARALLEL"] = True
        # tc.cache_variables["HDF5_IS_PARALLEL"] = True

        # # Force netCDF to actually enable parallel I/O
        # tc.cache_variables["NETCDF_ENABLE_PARALLEL4"] = True
        # tc.cache_variables["NETCDF_ENABLE_PARALLEL"] = True

        # Make sure MPI wrappers are used
        # tc.cache_variables["CMAKE_C_COMPILER"] = "mpicc"
        # tc.cache_variables["CMAKE_CXX_COMPILER"] = "mpicxx"
        # tc.cache_variables["CMAKE_Fortran_COMPILER"] = "mpiifx"
        # 
        tc.user_presets_path = "src/cmake/CMakePresets.json"
        tc.generate()
