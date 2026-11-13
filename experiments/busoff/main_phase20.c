#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>

#include "pico/stdlib.h"
#include "hardware/clocks.h"
#include "hardware/pio.h"

#include "injector.pio.h"

#define INJ_PIN 2
#define INJ_PIN_COUNT 1

#define TRIGGER_PIN 4

#define BASELINE_DURATION_US 5000000ULL
#define RECOVERY_DURATION_US 5000000ULL


#define PULSE_WIDTH_US 8u

// Profile PHASE20: phase sweep at a lower pulse rate than official ALTO.
#define PHASE_INTERVAL_US 20000u
#define PHASE_SHIFT_US 500u
#define PHASE_HOLD_PULSES 50u
#define NODE_TX_PERIOD_US 10000u
#define PHASE_MAX_DURATION_S 40u


#include <string.h>

#define CONFIG_PROTOCOL_VERSION "pico-param-v1.6-phase20"

static uint32_t configured_run_id = 0;
static char configured_profile[16] = "ALTO";
static uint32_t interval_min_us = 9375u;
static uint32_t interval_max_us = 14375u;
static uint32_t configured_seed = 0x6D2B79F5u;
static uint64_t injection_duration_us = 20000000ULL;

static char command_buffer[96];
static uint32_t command_length = 0;

typedef enum {
    TEST_IDLE,
    TEST_BASELINE,
    TEST_INJECTION,
    TEST_RECOVERY
} test_state_t;

static test_state_t test_state = TEST_IDLE;

static uint64_t state_started_us = 0;
static uint64_t next_pulse_us = 0;

static uint32_t pulse_count = 0;
static uint32_t missed_deadlines = 0;
static uint32_t max_late_us = 0;
static uint32_t random_interval_us(void);

static uint32_t rng_state = 0x6D2B79F5u;
static uint32_t phase_step_count = 0u;

static bool phase20_active(void)
{
    return strcmp(configured_profile, "PHASE20") == 0;
}

static uint32_t scheduling_interval_us(void)
{
    if (phase20_active()) {
        // One positive phase shift after each block of 50 emitted pulses.
        return PHASE_INTERVAL_US +
            ((pulse_count > 0u && (pulse_count % PHASE_HOLD_PULSES) == 0u)
                ? PHASE_SHIFT_US : 0u);
    }
    return random_interval_us();
}

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

static void injector_prepare_idle(
    PIO pio,
    uint sm,
    uint offset,
    const pio_sm_config *config
)
{
    pio_sm_set_enabled(
        pio,
        sm,
        false
    );

    pio_sm_clear_fifos(
        pio,
        sm
    );

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

    gpio_put(
        TRIGGER_PIN,
        0
    );

    pio_sm_set_enabled(
        pio,
        sm,
        true
    );
}

static uint32_t prng_next(void)
{
    uint32_t x = rng_state;

    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;

    rng_state = x;

    return x;
}

static uint32_t random_interval_us(void)
{
    uint32_t span =
        interval_max_us -
        interval_min_us +
        1u;

    return
        interval_min_us +
        (prng_next() % span);
}

static void injector_pulse(
    PIO pio,
    uint sm
)
{
    pio_sm_put_blocking(
        pio,
        sm,
        1u
    );

    pulse_count++;
}

static void start_test(
    PIO pio,
    uint sm,
    uint offset,
    const pio_sm_config *config
)
{
    if (test_state != TEST_IDLE) {
        log_event(
            "COMMAND",
            "TEST_ALREADY_RUNNING"
        );

        return;
    }

    injector_prepare_idle(
        pio,
        sm,
        offset,
        config
    );

    rng_state = configured_seed;
    pulse_count = 0;
    phase_step_count = 0u;
    missed_deadlines = 0;
    max_late_us = 0;

    state_started_us = time_us_64();
    test_state = TEST_BASELINE;

    char detail[192];
    snprintf(detail, sizeof(detail),
        "run_id=%lu;profile=%s;baseline_us=5000000;injection_us=%llu;recovery_us=5000000",
        (unsigned long)configured_run_id, configured_profile,
        (unsigned long long)injection_duration_us);
    log_event("TEST_START", detail);
}

static void abort_test(
    PIO pio,
    uint sm,
    uint offset,
    const pio_sm_config *config
)
{
    injector_prepare_idle(
        pio,
        sm,
        offset,
        config
    );

    test_state = TEST_IDLE;

    char detail[128];

    snprintf(
        detail,
        sizeof(detail),
        "run_id=%lu;pulses=%lu;missed_deadlines=%lu;max_late_us=%lu",
        (unsigned long)configured_run_id,
        (unsigned long)pulse_count,
        (unsigned long)missed_deadlines,
        (unsigned long)max_late_us
    );

    log_event(
        "TEST_ABORTED",
        detail
    );
}

static void update_test(
    PIO pio,
    uint sm
)
{
    uint64_t now_us = time_us_64();

    if (test_state == TEST_BASELINE) {
        if (
            now_us - state_started_us
            >= BASELINE_DURATION_US
        ) {
            test_state = TEST_INJECTION;
            state_started_us = now_us;

            next_pulse_us =
                now_us + scheduling_interval_us();

            gpio_put(
                TRIGGER_PIN,
                1
            );

            char detail[256];

            snprintf(detail, sizeof(detail),
                "profile=%s;run_id=%lu;pulse_us=%u;interval_min_us=%lu;interval_max_us=%lu;mean_us=%lu;seed=0x%08lx;strategy=%s;phase_shift_us=%u;phase_hold_pulses=%u",
                configured_profile, (unsigned long)configured_run_id,
                PULSE_WIDTH_US, (unsigned long)interval_min_us,
                (unsigned long)interval_max_us,
                (unsigned long)((interval_min_us + interval_max_us) / 2u),
                (unsigned long)configured_seed,
                phase20_active() ? "phase_scan" : "random",
                phase20_active() ? PHASE_SHIFT_US : 0u,
                phase20_active() ? PHASE_HOLD_PULSES : 0u);

            log_event(
                "NOISE_START",
                detail
            );
        }

        return;
    }

    if (test_state == TEST_INJECTION) {
        if (
            now_us - state_started_us
            >= injection_duration_us
        ) {
            injector_set_high_z(
                pio,
                sm
            );

            gpio_put(
                TRIGGER_PIN,
                0
            );

            test_state = TEST_RECOVERY;
            state_started_us = now_us;

            char detail[128];

            snprintf(
                detail,
                sizeof(detail),
                "run_id=%lu;pulses=%lu;missed_deadlines=%lu;max_late_us=%lu",
                (unsigned long)configured_run_id,
                (unsigned long)pulse_count,
                (unsigned long)missed_deadlines,
                (unsigned long)max_late_us
            );

            log_event(
                "NOISE_END",
                detail
            );

            return;
        }

        if (now_us >= next_pulse_us) {
            uint64_t lateness_us =
                now_us - next_pulse_us;

            if (lateness_us > max_late_us) {
                max_late_us = (uint32_t)lateness_us;
            }

            injector_pulse(
                pio,
                sm
            );

            next_pulse_us += scheduling_interval_us();

            if (phase20_active() &&
                (pulse_count % PHASE_HOLD_PULSES) == 0u) {
                phase_step_count++;
                char detail[128];
                snprintf(detail, sizeof(detail),
                    "run_id=%lu;pulses=%lu;phase_offset_us=%lu;step=%lu",
                    (unsigned long)configured_run_id,
                    (unsigned long)pulse_count,
                    (unsigned long)((phase_step_count * PHASE_SHIFT_US) % NODE_TX_PERIOD_US),
                    (unsigned long)phase_step_count);
                log_event("PHASE_STEP", detail);
            }

            uint64_t after_pulse_us = time_us_64();

            while (next_pulse_us <= after_pulse_us) {
                missed_deadlines++;
                // A skipped deadline is not another emitted pulse or phase step.
                next_pulse_us += phase20_active()
                    ? PHASE_INTERVAL_US : random_interval_us();
            }
        }

        return;
    }

    if (test_state == TEST_RECOVERY) {
        if (
            now_us - state_started_us
            >= RECOVERY_DURATION_US
        ) {
            test_state = TEST_IDLE;

            char detail[128];

            snprintf(
                detail,
                sizeof(detail),
                "run_id=%lu;pulses=%lu;missed_deadlines=%lu;max_late_us=%lu",
                (unsigned long)configured_run_id,
                (unsigned long)pulse_count,
                (unsigned long)missed_deadlines,
                (unsigned long)max_late_us
            );

            log_event(
                "TEST_END",
                detail
            );
        }
    }
}


static void send_status(void)
{
    char detail[192];
    snprintf(detail, sizeof(detail),
        "firmware=%s;state=%s;run_id=%lu;profile=%s;interval_min_us=%lu;interval_max_us=%lu;seed=0x%08lx;injection_us=%llu",
        CONFIG_PROTOCOL_VERSION,
        test_state == TEST_IDLE ? "IDLE" : "BUSY",
        (unsigned long)configured_run_id, configured_profile,
        (unsigned long)interval_min_us, (unsigned long)interval_max_us,
        (unsigned long)configured_seed,
        (unsigned long long)injection_duration_us);
    log_event("STATUS", detail);
}

static void apply_command_line(const char *line)
{
    if (strncmp(line, "CFG,", 4) != 0) {
        log_event("CONFIG_ERROR", "reason=UNKNOWN_COMMAND");
        return;
    }

    if (test_state != TEST_IDLE) {
        log_event("CONFIG_ERROR", "reason=BUSY");
        return;
    }

    unsigned long id = 0, minimum = 0, maximum = 0, seed = 0, duration_s = 0;
    char profile[16] = {0};
    char extra = 0;
    int parsed = sscanf(line, "CFG,%lu,%15[^,],%lu,%lu,%lx,%lu%c",
        &id, profile, &minimum, &maximum, &seed, &duration_s, &extra);

    if (parsed != 6 || id == 0 || minimum < 1000 ||
        maximum > 100000 || minimum > maximum ||
        seed == 0 || duration_s < 5 || duration_s > 180 ||
        (strcmp(profile, "BAIXO") != 0 &&
         strcmp(profile, "MEDIO_V2") != 0 &&
         strcmp(profile, "MEDIO_ORIGINAL") != 0 &&
         strcmp(profile, "ALTO") != 0 &&
         strcmp(profile, "PHASE20") != 0) ||
        (strcmp(profile, "PHASE20") == 0 &&
         (minimum != PHASE_INTERVAL_US ||
          maximum != PHASE_INTERVAL_US ||
          duration_s > PHASE_MAX_DURATION_S))) {
        log_event("CONFIG_ERROR", "reason=INVALID_PARAMETERS");
        return;
    }

    configured_run_id = (uint32_t)id;
    strcpy(configured_profile, profile);
    interval_min_us = (uint32_t)minimum;
    interval_max_us = (uint32_t)maximum;
    configured_seed = (uint32_t)seed;
    injection_duration_us = (uint64_t)duration_s * 1000000ULL;

    char detail[192];
    snprintf(detail, sizeof(detail),
        "run_id=%lu;profile=%s;interval_min_us=%lu;interval_max_us=%lu;seed=0x%08lx;injection_us=%llu",
        (unsigned long)configured_run_id, configured_profile,
        (unsigned long)interval_min_us, (unsigned long)interval_max_us,
        (unsigned long)configured_seed,
        (unsigned long long)injection_duration_us);
    log_event("CONFIG_OK", detail);
}

static void process_input(int command, PIO pio, uint sm,
                          uint offset, const pio_sm_config *config)
{
    if (command < 0) {
        return;
    }

    if (command_length == 0 && (command == 's' || command == 'S')) {
        log_event("COMMAND", "TEST_REQUEST");
        start_test(pio, sm, offset, config);
        return;
    }
    if (command_length == 0 && (command == 'x' || command == 'X')) {
        log_event("COMMAND", "STOP_REQUEST");
        abort_test(pio, sm, offset, config);
        return;
    }
    if (command_length == 0 && command == '?') {
        send_status();
        return;
    }
    if (command == '\r') {
        return;
    }
    if (command == '\n') {
        command_buffer[command_length] = '\0';
        if (command_length > 0) {
            apply_command_line(command_buffer);
        }
        command_length = 0;
        return;
    }
    if (command_length < sizeof(command_buffer) - 1u) {
        command_buffer[command_length++] = (char)command;
    } else {
        command_length = 0;
        log_event("CONFIG_ERROR", "reason=COMMAND_TOO_LONG");
    }
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

    injector_prepare_idle(
        pio,
        sm,
        offset,
        &config
    );

    sleep_ms(1500);

    log_event(
        "READY",
        "WAITING_COMMAND"
    );

    while (true) {
        int command = getchar_timeout_us(0);
        process_input(command, pio, sm, offset, &config);
        update_test(pio, sm);
        tight_loop_contents();
    }
}