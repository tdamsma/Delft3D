/*
 * precice_loader.c
 *
 * Runtime loader for the preCICE shared library.
 * Has ZERO dependency on precice headers or boost.
 * Resolves the same C-ABI symbols that preciceFortran.hpp declares,
 * so the Fortran bind(c) interfaces in precice.F90 are satisfied at runtime.
 */

#if defined(_WIN32)
#  define WIN32_LEAN_AND_MEAN
#  include <windows.h>
typedef HMODULE lib_handle_t;
#  define lib_open(path)       LoadLibraryA(path)
#  define lib_sym(h, name)     GetProcAddress(h, name)
#  define lib_close(h)         FreeLibrary(h)
#  define lib_error()          "see GetLastError()"
#else
#  include <dlfcn.h>
typedef void* lib_handle_t;
#  define lib_open(path)       dlopen(path, RTLD_LAZY | RTLD_GLOBAL)
#  define lib_sym(h, name)     dlsym(h, name)
#  define lib_close(h)         dlclose(h)
#  define lib_error()          dlerror()
#endif

#include <stdio.h>
#include <string.h>

/* ------------------------------------------------------------------ */
/* Function pointer table — one entry per precicef_ C symbol          */
/* ------------------------------------------------------------------ */
typedef void (*fp_void_t)(void);

static lib_handle_t g_handle = NULL;

/* Steering */
static void (*fp_create_)(const char*, const char*, const int*, const int*, int, int)                        = NULL;
static void (*fp_create_with_communicator_)(const char*, const char*, const int*, const int*, const int*, int, int) = NULL;
static void (*fp_initialize_)(void)                                                                          = NULL;
static void (*fp_advance_)(const double*)                                                                    = NULL;
static void (*fp_finalize_)(void)                                                                            = NULL;
/* Status */
static void (*fp_is_coupling_ongoing_)(int*)                                                                 = NULL;
static void (*fp_is_time_window_complete_)(int*)                                                             = NULL;
static void (*fp_get_max_time_step_size_)(double*)                                                           = NULL;
/* Implicit */
static void (*fp_requires_writing_checkpoint_)(int*)                                                         = NULL;
static void (*fp_requires_reading_checkpoint_)(int*)                                                         = NULL;
static void (*fp_requires_initial_data_)(int*)                                                               = NULL;
/* Mesh */
static void (*fp_get_mesh_dimensions_)(const char*, int*, int)                                               = NULL;
static void (*fp_get_data_dimensions_)(const char*, const char*, int*, int, int)                             = NULL;
static void (*fp_requires_mesh_connectivity_for_)(const char*, int*, int)                                    = NULL;
static void (*fp_set_vertex_)(const char*, const double*, int*, int)                                         = NULL;
static void (*fp_set_vertices_)(const char*, const int*, double*, int*, int)                                  = NULL;
static void (*fp_get_mesh_vertex_size_)(const char*, int*, int)                                              = NULL;
static void (*fp_set_edge_)(const char*, const int*, const int*, int)                                        = NULL;
static void (*fp_set_mesh_edges_)(const char*, const int*, const int*, int)                                  = NULL;
static void (*fp_set_triangle_)(const char*, const int*, const int*, const int*, int)                        = NULL;
static void (*fp_set_mesh_triangles_)(const char*, const int*, const int*, int)                              = NULL;
static void (*fp_set_quad_)(const char*, const int*, const int*, const int*, const int*, int)                = NULL;
static void (*fp_set_mesh_quads_)(const char*, const int*, const int*, int)                                  = NULL;
static void (*fp_set_tetrahedron_)(const char*, const int*, const int*, const int*, const int*, int)         = NULL;
static void (*fp_set_mesh_tetrahedra_)(const char*, const int*, const int*, int)                             = NULL;
static void (*fp_set_mesh_access_region_)(const char*, const double*, int)                                   = NULL;
static void (*fp_get_mesh_vertex_ids_and_coordinates_)(const char*, const int*, int*, double*, int)          = NULL;
/* Data */
static void (*fp_write_data_)(const char*, const char*, const int*, int*, double*, int, int)                 = NULL;
static void (*fp_read_data_)(const char*, const char*, const int*, int*, const double*, double*, int, int)   = NULL;
static void (*fp_write_and_map_data_)(const char*, const char*, const int*, double*, double*, int, int)      = NULL;
static void (*fp_map_and_read_data_)(const char*, const char*, const int*, double*, const double*, double*, int, int) = NULL;
/* Gradient */
static void (*fp_requires_gradient_data_for_)(const char*, const char*, int*, int, int)                     = NULL;
static void (*fp_write_gradient_data_)(const char*, const char*, const int*, const int*, const double*, int, int) = NULL;
/* Profiling */
static void (*fp_start_profiling_section_)(const char*, int)                                                 = NULL;
static void (*fp_stop_last_profiling_section_)(void)                                                         = NULL;
static void (*fp_get_version_information_)(char*, int)                                                       = NULL;

/* ------------------------------------------------------------------ */
/* Helper macro — resolve one symbol, return 0 on failure             */
/* ------------------------------------------------------------------ */
#define RESOLVE(var, name) \
    do { \
        (var) = (void*)lib_sym(g_handle, (name)); \
        if (!(var)) { \
            fprintf(stderr, "precice_loader: could not resolve symbol '%s': %s\n", (name), lib_error()); \
            return 0; \
        } \
    } while(0)

/* ------------------------------------------------------------------ */
/* Public C API called from precice_adapter.F90                        */
/* ------------------------------------------------------------------ */

/** Load precice shared library from path. Returns 1 on success, 0 on failure. */
int precice_loader_load(const char* lib_path)
{
    if (g_handle) return 1; /* already loaded */

    g_handle = lib_open(lib_path);
    if (!g_handle) {
        fprintf(stderr, "precice_loader: failed to open '%s': %s\n", lib_path, lib_error());
        return 0;
    }

    RESOLVE(fp_create_,                              "precicef_create_");
    RESOLVE(fp_create_with_communicator_, "precicef_create_with_communicator_");
    RESOLVE(fp_initialize_,                          "precicef_initialize_");
    RESOLVE(fp_advance_,                             "precicef_advance_");
    RESOLVE(fp_finalize_,                            "precicef_finalize_");
    RESOLVE(fp_is_coupling_ongoing_,                 "precicef_is_coupling_ongoing_");
    RESOLVE(fp_is_time_window_complete_,             "precicef_is_time_window_complete_");
    RESOLVE(fp_get_max_time_step_size_,              "precicef_get_max_time_step_size_");
    RESOLVE(fp_requires_writing_checkpoint_,         "precicef_requires_writing_checkpoint_");
    RESOLVE(fp_requires_reading_checkpoint_,         "precicef_requires_reading_checkpoint_");
    RESOLVE(fp_requires_initial_data_,               "precicef_requires_initial_data_");
    RESOLVE(fp_get_mesh_dimensions_,                 "precicef_get_mesh_dimensions_");
    RESOLVE(fp_get_data_dimensions_,                 "precicef_get_data_dimensions_");
    RESOLVE(fp_requires_mesh_connectivity_for_,      "precicef_requires_mesh_connectivity_for_");
    RESOLVE(fp_set_vertex_,                          "precicef_set_vertex_");
    RESOLVE(fp_set_vertices_,                        "precicef_set_vertices_");
    RESOLVE(fp_get_mesh_vertex_size_,                "precicef_get_mesh_vertex_size_");
    RESOLVE(fp_set_edge_,                            "precicef_set_edge_");
    RESOLVE(fp_set_mesh_edges_,                      "precicef_set_mesh_edges_");
    RESOLVE(fp_set_triangle_,                        "precicef_set_triangle_");
    RESOLVE(fp_set_mesh_triangles_,                  "precicef_set_mesh_triangles_");
    RESOLVE(fp_set_quad_,                            "precicef_set_quad_");
    RESOLVE(fp_set_mesh_quads_,                      "precicef_set_mesh_quads_");
    RESOLVE(fp_set_tetrahedron_,                     "precicef_set_tetrahedron_");
    RESOLVE(fp_set_mesh_tetrahedra_,                 "precicef_set_mesh_tetrahedra_");
    RESOLVE(fp_set_mesh_access_region_,              "precicef_set_mesh_access_region_");
    RESOLVE(fp_get_mesh_vertex_ids_and_coordinates_, "precicef_get_mesh_vertex_ids_and_coordinates_");
    RESOLVE(fp_write_data_,                          "precicef_write_data_");
    RESOLVE(fp_read_data_,                           "precicef_read_data_");
    RESOLVE(fp_write_and_map_data_,                  "precicef_write_and_map_data_");
    RESOLVE(fp_map_and_read_data_,                   "precicef_map_and_read_data_");
    RESOLVE(fp_requires_gradient_data_for_,          "precicef_requires_gradient_data_for_");
    RESOLVE(fp_write_gradient_data_,                 "precicef_write_gradient_data_");
    RESOLVE(fp_start_profiling_section_,             "precicef_start_profiling_section_");
    RESOLVE(fp_stop_last_profiling_section_,         "precicef_stop_last_profiling_section_");
    RESOLVE(fp_get_version_information_,             "precicef_get_version_information_");

    return 1;
}

void precice_loader_unload(void)
{
    if (g_handle) { lib_close(g_handle); g_handle = NULL; }
}

/* ------------------------------------------------------------------ */
/* Forwarding stubs — these are the symbols Fortran bind(c) resolves  */
/* at link time against THIS file, not against precice.dll            */
/* ------------------------------------------------------------------ */
void precicef_create_(const char* a, const char* b, const int* c, const int* d, int e, int f)
    { if (fp_create_) fp_create_(a,b,c,d,e,f); }

void precicef_create_with_communicator_(const char* a, const char* b, const int* c, const int* d, const int* e, int f, int g)
{
   if (fp_create_with_communicator_) fp_create_with_communicator_(a, b, c, d, e, f, g);
}

void precicef_initialize_(void)
    { if (fp_initialize_) fp_initialize_(); }

void precicef_advance_(const double* dt)
    { if (fp_advance_) fp_advance_(dt); }

void precicef_finalize_(void)
    { if (fp_finalize_) fp_finalize_(); }

void precicef_is_coupling_ongoing_(int* v)
    { if (fp_is_coupling_ongoing_) fp_is_coupling_ongoing_(v); else *v = 0; }

void precicef_is_time_window_complete_(int* v)
    { if (fp_is_time_window_complete_) fp_is_time_window_complete_(v); else *v = 0; }

void precicef_get_max_time_step_size_(double* v)
    { if (fp_get_max_time_step_size_) fp_get_max_time_step_size_(v); else *v = 0.0; }

void precicef_requires_writing_checkpoint_(int* v)
    { if (fp_requires_writing_checkpoint_) fp_requires_writing_checkpoint_(v); else *v = 0; }

void precicef_requires_reading_checkpoint_(int* v)
    { if (fp_requires_reading_checkpoint_) fp_requires_reading_checkpoint_(v); else *v = 0; }

void precicef_requires_initial_data_(int* v)
    { if (fp_requires_initial_data_) fp_requires_initial_data_(v); else *v = 0; }

void precicef_get_mesh_dimensions_(const char* a, int* b, int c)
    { if (fp_get_mesh_dimensions_) fp_get_mesh_dimensions_(a,b,c); else *b = 0; }

void precicef_get_data_dimensions_(const char* a, const char* b, int* c, int d, int e)
    { if (fp_get_data_dimensions_) fp_get_data_dimensions_(a,b,c,d,e); else *c = 0; }

void precicef_requires_mesh_connectivity_for_(const char* a, int* b, int c)
    { if (fp_requires_mesh_connectivity_for_) fp_requires_mesh_connectivity_for_(a,b,c); else *b = 0; }

void precicef_set_vertex_(const char* a, const double* b, int* c, int d)
    { if (fp_set_vertex_) fp_set_vertex_(a,b,c,d); }

void precicef_set_vertices_(const char* a, const int* b, double* c, int* d, int e)
    { if (fp_set_vertices_) fp_set_vertices_(a,b,c,d,e); }

void precicef_get_mesh_vertex_size_(const char* a, int* b, int c)
    { if (fp_get_mesh_vertex_size_) fp_get_mesh_vertex_size_(a,b,c); else *b = 0; }

void precicef_set_edge_(const char* a, const int* b, const int* c, int d)
    { if (fp_set_edge_) fp_set_edge_(a,b,c,d); }

void precicef_set_mesh_edges_(const char* a, const int* b, const int* c, int d)
    { if (fp_set_mesh_edges_) fp_set_mesh_edges_(a,b,c,d); }

void precicef_set_triangle_(const char* a, const int* b, const int* c, const int* d, int e)
    { if (fp_set_triangle_) fp_set_triangle_(a,b,c,d,e); }

void precicef_set_mesh_triangles_(const char* a, const int* b, const int* c, int d)
    { if (fp_set_mesh_triangles_) fp_set_mesh_triangles_(a,b,c,d); }

void precicef_set_quad_(const char* a, const int* b, const int* c, const int* d, const int* e, int f)
    { if (fp_set_quad_) fp_set_quad_(a,b,c,d,e,f); }

void precicef_set_mesh_quads_(const char* a, const int* b, const int* c, int d)
    { if (fp_set_mesh_quads_) fp_set_mesh_quads_(a,b,c,d); }

void precicef_set_tetrahedron_(const char* a, const int* b, const int* c, const int* d, const int* e, int f)
    { if (fp_set_tetrahedron_) fp_set_tetrahedron_(a,b,c,d,e,f); }

void precicef_set_mesh_tetrahedra_(const char* a, const int* b, const int* c, int d)
    { if (fp_set_mesh_tetrahedra_) fp_set_mesh_tetrahedra_(a,b,c,d); }

void precicef_set_mesh_access_region_(const char* a, const double* b, int c)
    { if (fp_set_mesh_access_region_) fp_set_mesh_access_region_(a,b,c); }

void precicef_get_mesh_vertex_ids_and_coordinates_(const char* a, const int* b, int* c, double* d, int e)
    { if (fp_get_mesh_vertex_ids_and_coordinates_) fp_get_mesh_vertex_ids_and_coordinates_(a,b,c,d,e); }

void precicef_write_data_(const char* a, const char* b, const int* c, int* d, double* e, int f, int g)
    { if (fp_write_data_) fp_write_data_(a,b,c,d,e,f,g); }

void precicef_read_data_(const char* a, const char* b, const int* c, int* d, const double* e, double* f, int g, int h)
    { if (fp_read_data_) fp_read_data_(a,b,c,d,e,f,g,h); }

void precicef_write_and_map_data_(const char* a, const char* b, const int* c, double* d, double* e, int f, int g)
    { if (fp_write_and_map_data_) fp_write_and_map_data_(a,b,c,d,e,f,g); }

void precicef_map_and_read_data_(const char* a, const char* b, const int* c, double* d, const double* e, double* f, int g, int h)
    { if (fp_map_and_read_data_) fp_map_and_read_data_(a,b,c,d,e,f,g,h); }

void precicef_requires_gradient_data_for_(const char* a, const char* b, int* c, int d, int e)
    { if (fp_requires_gradient_data_for_) fp_requires_gradient_data_for_(a,b,c,d,e); else *c = 0; }

void precicef_write_gradient_data_(const char* a, const char* b, const int* c, const int* d, const double* e, int f, int g)
    { if (fp_write_gradient_data_) fp_write_gradient_data_(a,b,c,d,e,f,g); }

void precicef_start_profiling_section_(const char* a, int b)
    { if (fp_start_profiling_section_) fp_start_profiling_section_(a,b); }

void precicef_stop_last_profiling_section_(void)
    { if (fp_stop_last_profiling_section_) fp_stop_last_profiling_section_(); }

void precicef_get_version_information_(char* a, int b)
    { if (fp_get_version_information_) fp_get_version_information_(a,b); }