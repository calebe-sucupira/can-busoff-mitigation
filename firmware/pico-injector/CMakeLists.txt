cmake_minimum_required(VERSION 3.13)

include($ENV{PICO_SDK_PATH}/external/pico_sdk_import.cmake)

project(can_injector C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

pico_sdk_init()

add_executable(can_injector
    main.c
)

pico_generate_pio_header(
    can_injector
    ${CMAKE_CURRENT_LIST_DIR}/injector.pio
)

target_link_libraries(
    can_injector
    pico_stdlib
    hardware_pio
    hardware_clocks
)

pico_add_extra_outputs(can_injector)