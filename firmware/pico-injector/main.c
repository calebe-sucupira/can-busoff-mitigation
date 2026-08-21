#include "pico/stdlib.h"

#define INJ_PIN      2
#define INJ_L_PIN    3
#define TRIGGER_PIN  4

#define PULSE_HIGH_US 8
#define PULSE_LOW_US  42

int main(void)
{
    gpio_init(INJ_PIN);
    gpio_set_dir(INJ_PIN, GPIO_OUT);
    gpio_put(INJ_PIN, 0);

    // Segundo canal reservado para testes futuros
    gpio_init(INJ_L_PIN);
    gpio_set_dir(INJ_L_PIN, GPIO_OUT);
    gpio_put(INJ_L_PIN, 0);

    // Trigger reservado para uso posterior
    gpio_init(TRIGGER_PIN);
    gpio_set_dir(TRIGGER_PIN, GPIO_OUT);
    gpio_put(TRIGGER_PIN, 0);

    while (true) {
        gpio_put(INJ_PIN, 1);
        busy_wait_us_32(PULSE_HIGH_US);

        gpio_put(INJ_PIN, 0);
        busy_wait_us_32(PULSE_LOW_US);
    }
}