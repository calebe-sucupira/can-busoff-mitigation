cmake_minimum_required(VERSION 3.13)

include($ENV{PICO_SDK_PATH}/external/pico_sdk_import.cmake)

project(can_injector C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

pico_sdk_init()

add_executable(can_injector
    main.c
)

target_link_libraries(can_injector
    pico_stdlib
)

pico_add_extra_outputs(can_injector)
