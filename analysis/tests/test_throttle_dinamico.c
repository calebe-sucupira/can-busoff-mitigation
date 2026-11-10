#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "throttle_policy.h"

typedef struct {
    const char *label;
    uint32_t start_seq;
    uint32_t count_updates;
    uint16_t tec;
    bool enabled;
    bool bus_off;
    bool tx_pending;
    unsigned expected_count;
    int expected_first;
    int expected_last;
} phase_t;

typedef struct {
    const char *label;
    const phase_t *phases;
    unsigned phases_count;
    unsigned expected_total;
} test_t;

static int run_test(const test_t *test)
{
    uint32_t last_accepted = 0;
    bool has_last_accepted = false;
    unsigned total_accepted = 0;
    int failures = 0;

    printf("\n%s\n", test->label);
    printf("%-24s %8s %8s %10s %10s %s\n",
           "Fase", "Esperado", "Obtido", "Primeiro", "Ultimo", "Status");

    for (unsigned i = 0; i < test->phases_count; ++i) {
        const phase_t *phase = &test->phases[i];
        unsigned accepted = 0;
        int first = -1;
        int last = -1;
        bool invariants_ok = true;
        throttle_mode_t mode = throttle_mode_from_tec(phase->tec);
        uint32_t stride = throttle_update_stride(mode, phase->enabled);

        for (uint32_t n = 0; n < phase->count_updates; ++n) {
            uint32_t seq = phase->start_seq + n;
            bool allowed = throttle_can_submit_update(
                seq, last_accepted, has_last_accepted, phase->tx_pending,
                phase->bus_off, mode, phase->enabled
            );
            if (allowed) {
                if (phase->bus_off || phase->tx_pending) {
                    invariants_ok = false;
                }
                if (has_last_accepted &&
                    (uint32_t)(seq - last_accepted) < stride) {
                    invariants_ok = false;
                }
                last_accepted = seq;
                has_last_accepted = true;
                if (first == -1) {
                    first = (int)seq;
                }
                last = (int)seq;
                ++accepted;
            }
        }

        bool pass = accepted == phase->expected_count &&
                    first == phase->expected_first &&
                    last == phase->expected_last && invariants_ok;
        printf("%-24s %8u %8u %10d %10d %s\n",
               phase->label, phase->expected_count, accepted,
               first, last, pass ? "OK" : "FALHOU");
        if (!pass) {
            printf("  Esperados: primeiro=%d, ultimo=%d, invariantes=OK\n",
                   phase->expected_first, phase->expected_last);
            ++failures;
        }
        total_accepted += accepted;
    }

    bool total_ok = total_accepted == test->expected_total;
    printf("TOTAL: esperado=%u observado=%u %s\n",
           test->expected_total, total_accepted,
           total_ok ? "OK" : "FALHOU");
    if (!total_ok) {
        ++failures;
    }
    return failures;
}

int main(void)
{
    const phase_t main_phases[] = {
        {"NORMAL TEC=95",        0, 200,  95, true, false, false, 200,   0, 199},
        {"ALERTA TEC=96",      200, 200,  96, true, false, false, 100, 201, 399},
        {"CRITICO TEC=128",    400, 200, 128, true, false, false,  50, 403, 599},
        {"BUS_OFF",            600, 200, 255, true, true,  false,   0,  -1,  -1},
        {"RECUPERADO TEC=0",   800, 200,   0, true, false, false, 200, 800, 999},
    };
    const phase_t extra_phases[] = {
        {"CRITICO TEC=128",      0,  20, 128, true, false, false,   5,   0,  16},
        {"ALERTA TEC=127",      20,  20, 127, true, false, false,  10,  20,  38},
        {"NORMAL TEC=95",       40,  20,  95, true, false, false,  20,  40,  59},
        {"TX_PENDENTE",         60,  20,  95, true, false, true,    0,  -1,  -1},
        {"ATIVO TEC=255",       80,  20, 255, true, false, false,   5,  80,  96},
        {"BUS_OFF SINALIZADO",  100,  20, 255, true, true,  false,   0,  -1,  -1},
        {"RETORNO TEC=95",     120,  20,  95, true, false, false,  20, 120, 139},
    };
    const test_t tests[] = {
        {"Cenario principal: 1.000 atualizacoes em 10 s",
         main_phases, sizeof main_phases / sizeof main_phases[0], 550},
        {"Cenario adicional: quedas de TEC e travas",
         extra_phases, sizeof extra_phases / sizeof extra_phases[0], 60},
    };

    printf("Validacao dinamica OFFLINE de throttle_can_submit_update\n");
    printf("Nenhum ESP32, Pico ou barramento CAN e acessado.\n");

    int failures = 0;
    for (unsigned i = 0; i < sizeof tests / sizeof tests[0]; ++i) {
        failures += run_test(&tests[i]);
    }
    printf("\nRESULTADO: %s (%d falhas)\n",
           failures ? "FALHOU" : "APROVADO", failures);
    return failures ? 1 : 0;
}
