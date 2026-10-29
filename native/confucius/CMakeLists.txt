cmake_minimum_required(VERSION 3.26)
project(ming_confucius_python LANGUAGES CXX)
set(LLAMA_CPP_DIR "" CACHE PATH "Pinned llama.cpp checkout")
set(LLAMA_BUILD_DIR "" CACHE PATH "Matching already-built CUDA libraries")
find_package(Python COMPONENTS Interpreter Development.Module REQUIRED)
find_package(pybind11 CONFIG REQUIRED)
foreach(lib llama mtmd)
    add_library(${lib} SHARED IMPORTED)
endforeach()
set_target_properties(llama PROPERTIES
    IMPORTED_IMPLIB "${LLAMA_BUILD_DIR}/llama_cpp/src/Release/llama.lib"
    IMPORTED_LOCATION "${LLAMA_BUILD_DIR}/bin/Release/llama.dll")
set_target_properties(mtmd PROPERTIES
    IMPORTED_IMPLIB "${LLAMA_BUILD_DIR}/llama_cpp/tools/mtmd/Release/mtmd.lib"
    IMPORTED_LOCATION "${LLAMA_BUILD_DIR}/bin/Release/mtmd.dll")
pybind11_add_module(ming_confucius_native native_ext.cpp)
target_compile_features(ming_confucius_native PRIVATE cxx_std_17)
target_compile_options(ming_confucius_native PRIVATE /utf-8)
target_include_directories(ming_confucius_native PRIVATE
    "${LLAMA_CPP_DIR}/include" "${LLAMA_CPP_DIR}/ggml/include" "${LLAMA_CPP_DIR}/tools/mtmd")
target_link_libraries(ming_confucius_native PRIVATE mtmd llama
    "${LLAMA_BUILD_DIR}/llama_cpp/ggml/src/Release/ggml-base.lib")
set_target_properties(ming_confucius_native PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}/python"
    LIBRARY_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}/python")
