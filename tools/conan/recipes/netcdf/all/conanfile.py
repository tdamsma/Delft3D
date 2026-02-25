import os
from conan import ConanFile
from conan.tools.cmake import CMake, CMakeDeps, CMakeToolchain, cmake_layout
from conan.tools.files import apply_conandata_patches, export_conandata_patches, get, copy, rm, rmdir, replace_in_file

required_conan_version = ">=2.4"

class NetcdfConan(ConanFile):
    name = "netcdf"
    description = "Unidata network Common Data Form (netCDF)"
    topics = "unidata", "unidata-netcdf", "networking"
    license = "BSD-3-Clause"
    homepage = "https://github.com/Unidata/netcdf-c"
    url = "https://github.com/conan-io/conan-center-index"
    package_type = "library"
    languages = "C"
    implements = ["auto_shared_fpic"]
    settings = "os", "arch", "compiler", "build_type"

    options = {
      "shared": [True, False],
      "fPIC": [True, False],
      "netcdf4": [True, False],
      "with_hdf5": [True, False],
      "cdf5": [True, False],
      "dap": [True, False],
      "byterange": [True, False],
    }
    default_options = {
      "shared": False,
      "fPIC": True,
      "netcdf4": True,
      "with_hdf5": True,
      "cdf5": True,
      "dap": True,
      "byterange": False,
    }

    @property
    def _with_hdf5(self):
      return self.options.with_hdf5 or self.options.netcdf4

    def export_sources(self):
      export_conandata_patches(self)

    def layout(self):
      cmake_layout(self, src_folder="src")

    def requirements(self):
      self.requires("zlib/1.3.1")                     # explicit - plugins need it
      if self._with_hdf5:
        self.requires("hdf5/1.14.3")
      if self.options.dap or self.options.byterange:
        self.requires("libcurl/[>=7.78.0 <9]")

    def source(self):
      get(self, **self.conan_data["sources"][self.version], strip_root=True)
      apply_conandata_patches(self)

    def generate(self):
      tc = CMakeToolchain(self)

      tc.variables["BUILD_TESTING"] = False
      tc.variables["BUILD_UTILITIES"] = False
      tc.variables["ENABLE_TESTS"] = False
      tc.variables["ENABLE_FILTER_TESTING"] = False
      tc.variables["ENABLE_PARALLEL4"] = True
      tc.variables["ENABLE_FILTER_SZIP"] = False          # fixed typo

      tc.variables["ENABLE_NETCDF_4"] = self.options.netcdf4
      tc.variables["ENABLE_CDF5"] = self.options.cdf5
      tc.variables["ENABLE_DAP"] = self.options.dap
      tc.variables["ENABLE_BYTERANGE"] = self.options.byterange
      tc.variables["USE_HDF5"] = self.options.with_hdf5
      tc.variables["NC_FIND_SHARED_LIBS"] = self.options.with_hdf5 and bool(self.dependencies["hdf5"].options.shared)

      # Bypass other problematic checks
      tc.cache_variables["HAVE_H5Pset_all_coll_metadata_ops"] = False
      tc.cache_variables["HAVE_H5Z_DEFLATE"] = True

      # Force zlib for main configure + find_package(ZLIB) inside netcdf cmake
      if "zlib" in self.dependencies:
        tc.variables["ZLIB_INCLUDE_DIR"] = os.path.join(self.dependencies["zlib"].package_folder, "include").replace("\\","/")
       # tc.variables["ZLIB_LIBRARY"] = self.dependencies["zlib"].cpp_info.aggregated_components.libs[0]
        tc.variables["ZLIB_FOUND"] = True
        tc.variables["ZLIB_ROOT"] = self.dependencies["zlib"].package_folder.replace("\\","/")

      tc.cache_variables["CMAKE_TRY_COMPILE_CONFIGURATION"] = str(self.settings.build_type)
      tc.generate()

      CMakeDeps(self).generate()

    def _patch_dependencies_cmake(self):
      """Bypass the two HDF5 feature checks that cause try_compile failures on Windows/Conan"""
      dep_cmake = os.path.join(self.source_folder, "cmake", "dependencies.cmake")
      if not os.path.exists(dep_cmake):
        return

      # HDF5 has zlib (we know it does)
      replace_in_file(self, dep_cmake,
                      'check_hdf5_feature(HAVE_HDF5_ZLIB H5_HAVE_ZLIB_H)',
                      'set(HAVE_HDF5_ZLIB TRUE)\nset(H5_HAVE_ZLIB_H TRUE)')

      # No SZIP in our HDF5 build
      replace_in_file(self, dep_cmake,
                      'check_hdf5_feature(HAVE_H5Z_SZIP H5_HAVE_FILTER_SZIP)',
                      'set(HAVE_H5Z_SZIP FALSE)\nset(H5_HAVE_FILTER_SZIP FALSE)')

    def _patch_plugins_cmake(self):
      """Previous fix for h5deflate etc. plugins"""
      plugins_cmake = os.path.join(self.build_folder, "plugins", "CMakeLists.txt")
      if os.path.exists(plugins_cmake):
        replace_in_file(self, plugins_cmake,
                        'buildplugin(h5deflate "h5deflate")',
                        'buildplugin(h5deflate "h5deflate")\n    target_link_libraries(h5deflate PRIVATE ZLIB::ZLIB)')

    def build(self):
      cmake = CMake(self)

      self._patch_dependencies_cmake()   # ← must be BEFORE configure
      cmake.configure()

      self._patch_plugins_cmake()        # after configure
      cmake.build()

    def package(self):
      copy(self, "COPYRIGHT", src=self.source_folder, dst=os.path.join(self.package_folder, "licenses"))
      cmake = CMake(self)
      cmake.install()

      rm(self, "nc-config", os.path.join(self.package_folder, "bin"))
      rm(self, "*.settings", os.path.join(self.package_folder, "lib"))
      rmdir(self, os.path.join(self.package_folder, "lib", "cmake"))
      rmdir(self, os.path.join(self.package_folder, "lib", "pkgconfig"))
      rmdir(self, os.path.join(self.package_folder, "share"))

      if self.settings.os == "Windows" and self.options.shared:
        for vc_file in ["concrt*.dll", "msvcp*.dll", "vcruntime*.dll"]:
          rm(self, vc_file, os.path.join(self.package_folder, "bin"))
        rm(self, "*[!.dll]", os.path.join(self.package_folder, "bin"))
      else:
        rmdir(self, os.path.join(self.package_folder, "bin"))

    def package_info(self):
      self.cpp_info.set_property("cmake_file_name", "netCDF")
      self.cpp_info.set_property("cmake_target_name", "netCDF::netcdf")
      self.cpp_info.set_property("pkg_config_name", "netcdf")

      self.cpp_info.components["libnetcdf"].libs = ["netcdf"]

      if self._with_hdf5:
        self.cpp_info.components["libnetcdf"].requires.extend(["hdf5::hdf5", "hdf5::hdf5_hl", "zlib::zlib"])

      if self.options.dap or self.options.byterange:
        self.cpp_info.components["libnetcdf"].requires.append("libcurl::libcurl")

      if self.settings.os in ["Linux", "FreeBSD"]:
        self.cpp_info.components["libnetcdf"].system_libs = ["dl", "m"]
      elif self.settings.os == "Windows" and self.options.shared:
        self.cpp_info.components["libnetcdf"].defines.append("DLL_NETCDF")

      self.cpp_info.components["libnetcdf"].set_property("cmake_target_name", "netCDF::netcdf")
      self.cpp_info.components["libnetcdf"].set_property("pkg_config_name", "netcdf")
