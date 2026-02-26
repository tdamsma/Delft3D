from conan import ConanFile
from conan.tools.cmake import cmake_layout, CMakeToolchain


class Delft3DRecipe(ConanFile):
    settings = "os", "compiler", "build_type", "arch"
    generators = "CMakeDeps"

    def requirements(self):
      self.requires("netcdf-fortran/4.6.2")
   

    def layout(self):
        cmake_layout(self)
        
    def configure(self):
      self.options['example'].example =False
    
      
    def generate(self):
        tc = CMakeToolchain(self)
        tc.user_presets_path = "src/cmake/CMakePresets.json"
        tc.generate()
