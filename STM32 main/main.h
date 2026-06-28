#include "stm32f401xc.h"
#include "stdbool.h"
#include "rcc.h"
#include "gpio.h"
#include "usart1.h"
#include "pwm.h"
#include "adc.h"
#include "dht22.h"
void LedBlink_Init(void);

#ifndef MAIN_H
#define MAIN_H

// ============================================================
// Протокол UART (OrangePi ↔ STM32)
// ============================================================
#define BYTE_START              0xBF   // Маркер начала пакета
#define BYTE_END                0xFF   // Маркер конца пакета

// Байт TYPE: [бит7..6=флаги | биты5..3=System Part | биты2..1=Command Type | бит0=Source]
#define PROTOCOL_SOURCE_msk             0b00000001   // бит 0
#define PROTOCOL_TYPE_COMMAND_TYPE_msk  0b00000110   // биты 2..1
#define PROTOCOL_TYPE_SENSOR_TYPE_msk   0b00111000   // биты 5..3

// Квитанции STM32 → OrangePi (байт TYPE в ответном пакете)
#define ACK_TYPE                0b01000000   // Успешно выполнено
#define NACK_TYPE               0b11000000   // Ошибка выполнения

// Ограничения
#define MAX_DATA_LEN            100    // Макс. длина поля DATA
#define MAX_MESSAGE_LENGTH      (MAX_DATA_LEN + 5)  // BYTE_START + TYPE + LEN + DATA + CRC + BYTE_END
#define BUFFER_LENGTH           10
#define INTER_BYTE_TIMEOUT_US   100000 // 100 мс межбайтовый таймаут (в мкс)
#define PWM_MIN 1000
#define PWM_CENTER 1500
#define PWM_MAX 2000

// Индексы полей в пакете
#define MESSAGE_STB             0   // BYTE_START (0xBF)
#define MESSAGE_TYPE            1   // TYPE
#define MESSAGE_LEN             2   // LEN (длина DATA)
// DATA начинается с индекса 3

// Климат-контроль
#define HEATER_MAX_TEMPERATURE  20
#define HEATER_MIN_TEMPERATURE  10
#define COOLER_MAX_TEMPERATURE  35
#define COOLER_MIN_TEMPERATURE  15

// Шаговый двигатель — стол (table)
#define TABLE_SPEED_MIN       3000.0f   // стартовая скорость (шаги/сек)
#define TABLE_SPEED_MAX       15000.0f  // целевая скорость (шаги/сек)
#define TABLE_ACCEL           8000.0f   // ускорение (шаги/с²)

// Шаговый двигатель — зарядные лапки (gripper)
#define GRIPPER_SPEED_MIN     3000.0f
#define GRIPPER_SPEED_MAX     10000.0f
#define GRIPPER_ACCEL         5000.0f

// Таймауты механики — шаговики (в шагах), крыша (в мс для delay)
#define STEP_MOTOR_TABLE_UPPER_TIMEOUT   155000      // шаги подъёма стола
#define STEP_MOTOR_TABLE_LOWER_TIMEOUT   155000      // шаги опускания стола
#define STEP_MOTOR_DRONE_HOLD_TIMEOUT    8000       // шаги сжатия лапок
#define STEP_MOTOR_DRONE_OPEN_TIMEOUT    8000       // шаги разжатия лапок
#define TABLE_NUDGE_STEPS                50         // порция шагов "подтолкнуть стол" (CMD 21)
#define GRIPPER_ENDSTOP_OPEN_PIN         8          // PB8 — концевик "лапки открыты"
#define AIR_SHUTTERS_OPEN_TIMEOUT        1000000
#define AIR_SHUTTERS_CLOSE_TIMEOUT       1000000
#define  ROOF_SHUTTERS_OPEN_TIMEOUT       15000      // мс — открытие крыши
#define ROOF_SHUTTERS_CLOSE_TIMEOUT      29000      // мс — закрытие крыши

// Буферы сообщений
uint8_t msg_tx[MAX_MESSAGE_LENGTH];
uint8_t msg_rx[BUFFER_LENGTH][MAX_MESSAGE_LENGTH];
uint8_t start_msg_index  = 0;
uint8_t last_msg_index   = 0;
uint8_t msg_byte_index   = 0;
bool    isClimatic       = 0;

// Таймаут между байтами: обновляется в IRQ, проверяется в main
volatile uint32_t last_byte_tick = 0;
volatile bool     rx_in_progress = 0;

// Флаг аварийной паузы: ставится в IRQ при cmd=25, снимается при cmd=26
volatile bool emergency_stop = false;

#endif