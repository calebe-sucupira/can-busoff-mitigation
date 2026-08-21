#include "pico/stdlib.h"
#include "hardware/clocks.h"
#include "hardware/pio.h"

#include "injector.pio.h"

#define INJ_PIN 2

int main(void)
{
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

    pio_sm_set_enabled(
        pio,
        sm,
        true
    );

    while (true) {
        tight_loop_contents();
    }
}