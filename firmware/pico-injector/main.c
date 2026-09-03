#include <stdio.h>

#include "pico/stdlib.h"
#include "hardware/clocks.h"
#include "hardware/pio.h"

#include "injector.pio.h"

#define INJ_PIN 2
#define TRIGGER_PIN 4

static bool injector_running = false;

static void log_event(
    const char *event,
    const char *detail
)
{
    uint64_t timestamp_us = time_us_64();

    printf(
        "DATA,%llu,PICO,%s,,,,,,%s\n",
        (unsigned long long)timestamp_us,
        event,
        detail
    );
}

static void injector_start(
    PIO pio,
    uint sm,
    uint offset,
    const pio_sm_config *config
)
{
    if (injector_running) {
        return;
    }

    pio_sm_init(
        pio,
        sm,
        offset,
        config
    );

    gpio_put(
        TRIGGER_PIN,
        1
    );

    pio_sm_set_enabled(
        pio,
        sm,
        true
    );

    injector_running = true;

    log_event(
        "NOISE_START",
        "PIO_ENABLED"
    );
}

static void injector_stop(
    PIO pio,
    uint sm
)
{
    if (!injector_running) {
        return;
    }

    pio_sm_set_enabled(
        pio,
        sm,
        false
    );

    pio_sm_set_pins_with_mask(
        pio,
        sm,
        0,
        1u << INJ_PIN
    );

    gpio_put(
        TRIGGER_PIN,
        0
    );

    injector_running = false;

    log_event(
        "NOISE_END",
        "PIO_DISABLED"
    );
}

int main(void)
{
    stdio_init_all();

    gpio_init(
        TRIGGER_PIN
    );

    gpio_set_dir(
        TRIGGER_PIN,
        GPIO_OUT
    );

    gpio_put(
        TRIGGER_PIN,
        0
    );

    PIO pio = pio0;

    uint offset = pio_add_program(
        pio,
        &injector_program
    );

    uint sm = pio_claim_unused_sm(
        pio,
        true
    );

    pio_gpio_init(
        pio,
        INJ_PIN
    );

    pio_sm_set_consecutive_pindirs(
        pio,
        sm,
        INJ_PIN,
        1,
        true
    );

    pio_sm_config config =
        injector_program_get_default_config(offset);

    sm_config_set_set_pins(
        &config,
        INJ_PIN,
        1
    );

    float divider =
        (float)clock_get_hz(clk_sys) / 1000000.0f;

    sm_config_set_clkdiv(
        &config,
        divider
    );

    pio_sm_init(
        pio,
        sm,
        offset,
        &config
    );

    pio_sm_set_pins_with_mask(
        pio,
        sm,
        0,
        1u << INJ_PIN
    );

    while (true) {
        int command = getchar_timeout_us(0);

        if (
            command == 's' ||
            command == 'S'
        ) {
            injector_start(
                pio,
                sm,
                offset,
                &config
            );
        }

        if (
            command == 'x' ||
            command == 'X'
        ) {
            injector_stop(
                pio,
                sm
            );
        }

        tight_loop_contents();
    }
}