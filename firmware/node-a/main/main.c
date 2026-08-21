#include <stdint.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "esp_log.h"
#include "esp_timer.h"
#include "esp_twai.h"
#include "esp_twai_onchip.h"

#define TWAI_TX_GPIO       21
#define TWAI_RX_GPIO       22

#define CAN_BITRATE        125000
#define CAN_ID_UPDATE      0x100

#define UPDATE_PERIOD_MS   10

static const char *TAG = "NODE_A";

static twai_node_handle_t twai_node = NULL;

static void transmitter_task(void *arg)
{
    uint32_t sequence = 0;
    TickType_t last_wake_time = xTaskGetTickCount();

    while (1) {
        uint32_t timestamp_ms =
            (uint32_t)(esp_timer_get_time() / 1000ULL);

        uint8_t payload[8];

        memcpy(&payload[0], &sequence, sizeof(sequence));
        memcpy(&payload[4], &timestamp_ms, sizeof(timestamp_ms));

        twai_frame_t frame = {
            .header.id = CAN_ID_UPDATE,
            .buffer = payload,
            .buffer_len = sizeof(payload),
        };

        esp_err_t err = twai_node_transmit(
            twai_node,
            &frame,
            0
        );

        if (err == ESP_OK) {
            err = twai_node_transmit_wait_all_done(
                twai_node,
                100
            );

            if (err == ESP_OK) {
                if ((sequence % 100) == 0) {
                    ESP_LOGI(
                        TAG,
                        "TX seq=%lu timestamp=%lu ms",
                        (unsigned long)sequence,
                        (unsigned long)timestamp_ms
                    );
                }
            } else {
                ESP_LOGW(
                    TAG,
                    "Falha na transmissao: %s",
                    esp_err_to_name(err)
                );
            }
        } else {
            ESP_LOGW(
                TAG,
                "Frame nao submetido: %s",
                esp_err_to_name(err)
            );
        }

        sequence++;

        xTaskDelayUntil(
            &last_wake_time,
            pdMS_TO_TICKS(UPDATE_PERIOD_MS)
        );
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "Inicializando No A");

    twai_onchip_node_config_t node_config = {
        .io_cfg = {
            .tx = TWAI_TX_GPIO,
            .rx = TWAI_RX_GPIO,
            .quanta_clk_out = -1,
            .bus_off_indicator = -1,
        },

        .bit_timing = {
            .bitrate = CAN_BITRATE,
        },

        .tx_queue_depth = 1,
        .fail_retry_cnt = -1,
    };

    ESP_ERROR_CHECK(
        twai_new_node_onchip(
            &node_config,
            &twai_node
        )
    );

    ESP_ERROR_CHECK(
        twai_node_enable(twai_node)
    );

    ESP_LOGI(
        TAG,
        "TWAI iniciado: %d bit/s | TX GPIO %d | RX GPIO %d",
        CAN_BITRATE,
        TWAI_TX_GPIO,
        TWAI_RX_GPIO
    );

    xTaskCreate(
        transmitter_task,
        "transmitter_task",
        4096,
        NULL,
        5,
        NULL
    );
}