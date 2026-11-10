idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES esp_driver_twai esp_timer
)

# Definicao aplicada somente na copia de compilacao.
target_compile_definitions(${COMPONENT_LIB} PRIVATE ENABLE_THROTTLING=1)
