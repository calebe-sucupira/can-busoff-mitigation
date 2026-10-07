#include <stdio.h>

#include "pico/stdlib.h"
#include "hardware/clocks.h"
#include "hardware/pio.h"

#include "injector.pio.h"

#define INJ_PIN 2
#define INJ_PIN_COUNT 1

#define TRIGGER_PIN 4

#define TEST_DURATION_US 12000
#define TEST_SETTLE_US 1000

static bool injector_running = false;

static uint32_t injector_mask(void)
{
    return 1u << INJ_PIN;
}

static void log_event(
    const char *event,
    const char *detail
)
{
    uint64_t timestamp_us = time_us_64();

    printf(
        "DATA,%llu,%s,-1,0,0,-,-,%s\n",
        (unsigned long long)timestamp_us,
        event,
        detail
    );

    fflush(stdout);
}

static void injector_set_high_z(
    PIO pio,
    uint sm
)
{
    pio_sm_set_pins_with_mask(
        pio,
        sm,
        injector_mask(),
        injector_mask()
    );

    pio_sm_set_consecutive_pindirs(
        pio,
        sm,
        INJ_PIN,
        INJ_PIN_COUNT,
        false
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

    injector_set_high_z(
        pio,
        sm
    );

    sleep_us(
        TEST_SETTLE_US
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
        "HL_SHORT_PULSE_TRAIN"
    );
}

static void injector_stop(
    PIO pio,
    uint sm
)
{
    pio_sm_set_enabled(
        pio,
        sm,
        false
    );

    injector_set_high_z(
        pio,
        sm
    );

    gpio_put(
        TRIGGER_PIN,
        0
    );

    if (injector_running) {
        log_event(
            "NOISE_END",
            "HL_SHORT_DISABLED"
        );
    }

    injector_running = false;
}

static void injector_test(
    PIO pio,
    uint sm,
    uint offset,
    const pio_sm_config *config
)
{
    injector_start(
        pio,
        sm,
        offset,
        config
    );

    sleep_us(
        TEST_DURATION_US
    );

    injector_stop(
        pio,
        sm
    );

    log_event(
        "PIO_TEST",
        "duration_us=1000"
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

    uint offset =
        pio_add_program(
            pio,
            &injector_program
        );

    uint sm =
        pio_claim_unused_sm(
            pio,
            true
        );

    pio_gpio_init(
        pio,
        INJ_PIN
    );

    gpio_disable_pulls(
        INJ_PIN
    );

    pio_sm_config config =
        injector_program_get_default_config(
            offset
        );

    sm_config_set_set_pins(
        &config,
        INJ_PIN,
        INJ_PIN_COUNT
    );

    float divider =
        (float)clock_get_hz(
            clk_sys
        )
        / 1000000.0f;

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

    injector_set_high_z(
        pio,
        sm
    );

    sleep_ms(1500);

    log_event(
        "READY",
        "WAITING_COMMAND"
    );

    while (true) {
        int command =
            getchar_timeout_us(1000);

        if (
            command == 's'
            || command == 'S'
            || command == 't'
            || command == 'T'
        ) {
            log_event(
                "COMMAND",
                "TEST_REQUEST"
            );

            injector_test(
                pio,
                sm,
                offset,
                &config
            );
        }

        if (
            command == 'x'
            || command == 'X'
        ) {
            log_event(
                "COMMAND",
                "STOP_REQUEST"
            );

            injector_stop(
                pio,
                sm
            );
        }

        tight_loop_contents();
    }
}