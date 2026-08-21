#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
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
#define MONITOR_PERIOD_MS  10

typedef enum {
    EVENT_TX_DONE,
    EVENT_STATE_CHANGE,
    EVENT_ERROR
} event_type_t;

typedef struct {
    event_type_t type;
    uint64_t timestamp_us;

    union {
        struct {
            uint32_t sequence;
            bool success;
        } tx;

        struct {
            twai_error_state_t old_state;
            twai_error_state_t new_state;
        } state;

        struct {
            uint32_t flags;
        } error;
    };
} node_event_t;

static const char *TAG = "NODE_A";

static twai_node_handle_t twai_node = NULL;
static QueueHandle_t event_queue = NULL;

static const char *state_to_string(twai_error_state_t state)
{
    switch (state) {
        case TWAI_ERROR_ACTIVE:
            return "ACTIVE";
        case TWAI_ERROR_WARNING:
            return "WARNING";
        case TWAI_ERROR_PASSIVE:
            return "PASSIVE";
        case TWAI_ERROR_BUS_OFF:
            return "BUS_OFF";
        default:
            return "UNKNOWN";
    }
}

static bool tx_done_callback(
    twai_node_handle_t handle,
    const twai_tx_done_event_data_t *edata,
    void *user_ctx)
{
    node_event_t event = {
        .type = EVENT_TX_DONE,
        .timestamp_us = esp_timer_get_time(),
    };

    event.tx.success = edata->is_tx_success;
    event.tx.sequence = 0;

    if (edata->done_tx_frame != NULL &&
        edata->done_tx_frame->buffer != NULL &&
        edata->done_tx_frame->buffer_len >= sizeof(uint32_t)) {

        memcpy(
            &event.tx.sequence,
            edata->done_tx_frame->buffer,
            sizeof(event.tx.sequence)
        );
    }

    BaseType_t task_woken = pdFALSE;

    xQueueSendFromISR(
        event_queue,
        &event,
        &task_woken
    );

    return task_woken == pdTRUE;
}

static bool state_change_callback(
    twai_node_handle_t handle,
    const twai_state_change_event_data_t *edata,
    void *user_ctx)
{
    node_event_t event = {
        .type = EVENT_STATE_CHANGE,
        .timestamp_us = esp_timer_get_time(),
    };

    event.state.old_state = edata->old_sta;
    event.state.new_state = edata->new_sta;

    BaseType_t task_woken = pdFALSE;

    xQueueSendFromISR(
        event_queue,
        &event,
        &task_woken
    );

    return task_woken == pdTRUE;
}

static bool error_callback(
    twai_node_handle_t handle,
    const twai_error_event_data_t *edata,
    void *user_ctx)
{
    node_event_t event = {
        .type = EVENT_ERROR,
        .timestamp_us = esp_timer_get_time(),
    };

    event.error.flags = edata->err_flags.val;

    BaseType_t task_woken = pdFALSE;

    xQueueSendFromISR(
        event_queue,
        &event,
        &task_woken
    );

    return task_woken == pdTRUE;
}

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
            twai_node_transmit_wait_all_done(
                twai_node,
                100
            );
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

static void monitor_task(void *arg)
{
    TickType_t last_wake_time = xTaskGetTickCount();

    while (1) {
        twai_node_status_t status;
        twai_node_record_t record;

        if (twai_node_get_info(
                twai_node,
                &status,
                &record
            ) == ESP_OK) {

            printf(
                "%llu,SAMPLE,-1,%u,%u,%s,bus_errors=%lu\n",
                esp_timer_get_time(),
                status.tx_error_count,
                status.rx_error_count,
                state_to_string(status.state),
                (unsigned long)record.bus_err_num
            );
        }

        xTaskDelayUntil(
            &last_wake_time,
            pdMS_TO_TICKS(MONITOR_PERIOD_MS)
        );
    }
}

static void event_task(void *arg)
{
    node_event_t event;

    while (1) {
        if (xQueueReceive(
                event_queue,
                &event,
                portMAX_DELAY
            ) != pdTRUE) {
            continue;
        }

        twai_node_status_t status;
        twai_node_record_t record;

        if (twai_node_get_info(
                twai_node,
                &status,
                &record
            ) != ESP_OK) {
            continue;
        }

        switch (event.type) {
            case EVENT_TX_DONE:
                printf(
                    "%llu,%s,%lu,%u,%u,%s,-\n",
                    event.timestamp_us,
                    event.tx.success ? "TX_SUCCESS" : "TX_FAILED",
                    (unsigned long)event.tx.sequence,
                    status.tx_error_count,
                    status.rx_error_count,
                    state_to_string(status.state)
                );
                break;

            case EVENT_STATE_CHANGE:
                printf(
                    "%llu,STATE_CHANGE,-1,%u,%u,%s,%s->%s\n",
                    event.timestamp_us,
                    status.tx_error_count,
                    status.rx_error_count,
                    state_to_string(status.state),
                    state_to_string(event.state.old_state),
                    state_to_string(event.state.new_state)
                );
                break;

            case EVENT_ERROR:
                printf(
                    "%llu,ERROR,-1,%u,%u,%s,flags=0x%08lx\n",
                    event.timestamp_us,
                    status.tx_error_count,
                    status.rx_error_count,
                    state_to_string(status.state),
                    (unsigned long)event.error.flags
                );
                break;
        }
    }
}

void app_main(void)
{
    event_queue = xQueueCreate(
        64,
        sizeof(node_event_t)
    );

    ESP_ERROR_CHECK(
        event_queue != NULL ? ESP_OK : ESP_ERR_NO_MEM
    );

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

    twai_event_callbacks_t callbacks = {
        .on_tx_done = tx_done_callback,
        .on_state_change = state_change_callback,
        .on_error = error_callback,
    };

    ESP_ERROR_CHECK(
        twai_node_register_event_callbacks(
            twai_node,
            &callbacks,
            NULL
        )
    );

    ESP_ERROR_CHECK(
        twai_node_enable(twai_node)
    );

    ESP_LOGI(
        TAG,
        "TWAI iniciado: %d bit/s",
        CAN_BITRATE
    );

    xTaskCreate(
        transmitter_task,
        "transmitter_task",
        4096,
        NULL,
        5,
        NULL
    );

    xTaskCreate(
        monitor_task,
        "monitor_task",
        4096,
        NULL,
        6,
        NULL
    );

    xTaskCreate(
        event_task,
        "event_task",
        4096,
        NULL,
        7,
        NULL
    );
}