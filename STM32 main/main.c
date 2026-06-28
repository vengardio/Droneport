#include "main.h"
#include "stdlib.h"
#include "stdint.h"
#include "stdio.h"

extern uint8_t  msg_tx[MAX_MESSAGE_LENGTH];
extern uint8_t  msg_rx[BUFFER_LENGTH][MAX_MESSAGE_LENGTH];
extern uint8_t  start_msg_index;
extern uint8_t  last_msg_index;
extern uint8_t  msg_byte_index;
extern bool     isClimatic;
extern volatile uint32_t last_byte_tick;
extern volatile bool     rx_in_progress;
extern volatile bool     emergency_stop;

// ============================================================
// Вспомогательные функции протокола
// ============================================================

/*
 * Подсчёт контрольной суммы.
 * Суммируются ВСЕ байты пакета КРОМЕ: BYTE_START, BYTE_END и самого CRC.
 * Иными словами: TYPE + LEN + DATA[0..LEN-1].
 * Результат берётся по модулю 256.
 */
uint8_t calc_checksum(uint8_t *buf, uint8_t type, uint8_t len) {
    uint32_t sum = type + len;
    for (uint8_t i = 0; i < len; i++) sum += buf[i];
    return (uint8_t)(sum & 0xFF);
}

/*
 * Отправить пакет STM32 → OrangePi.
 * Структура: [BYTE_START | TYPE | LEN | DATA[0..len-1] | CRC | BYTE_END]
 * CRC = (TYPE + LEN + sum(DATA)) % 256
 */
void send_packet(uint8_t type, uint8_t *data, uint8_t len) {
    uint8_t pkt[MAX_MESSAGE_LENGTH];
    pkt[0] = BYTE_START;
    pkt[1] = type;
    pkt[2] = len;
    for (uint8_t i = 0; i < len; i++) pkt[3 + i] = data[i];
    pkt[3 + len]     = calc_checksum(data, type, len);
    pkt[3 + len + 1] = BYTE_END;
    USART1_SendArray(pkt, 3 + len + 2);
}

/*
 * Отправить ACK: TYPE=0b01000000, LEN=0, DATA пусто.
 */
void send_ack(void) {
    send_packet(ACK_TYPE, NULL, 0);
}

/*
 * Отправить NACK + пакет об ошибке.
 * error_code: 0=CRC, 1=длина DATA > MAX_DATA_LEN, 2=буфер переполнен, 3=ошибка чтения пакета
 * Формат пакета ошибки: TYPE биты[5..3]=000 (Software), биты[2..1]=11 (Error), бит[0]=0 (от STM32)
 *   → TYPE = 0b00000110
 */
void send_nack_with_error(uint8_t error_code) {
    // 1. Квитанция ошибки
    send_packet(NACK_TYPE, NULL, 0);
    // 2. Пакет с кодом ошибки
    // TYPE: Source=0(STM32), CommandType=11(Error), SystemPart=000(Software) → 0b00000110
    uint8_t err_data[1] = { error_code };
    send_packet(0b00000110, err_data, 1);
}

// ============================================================
// Механика
// ============================================================

void Airing_control(uint8_t sw) {
    switch (sw) {
        case 0:  // Открыть заслонки
            GPIOA->ODR |=  (1 << 11);
            GPIOA->ODR &= ~(1 << 5);
            uint32_t c = 0;
            while (c <= AIR_SHUTTERS_OPEN_TIMEOUT
                   && !(GPIOB->IDR & (1 << 4))
                   && !(GPIOB->IDR & (1 << 5))
                   && !emergency_stop) c++;
            GPIOA->ODR &= ~(1 << 11);
            GPIOA->ODR &= ~(1 << 1);
            break;
        case 1:  // Закрыть заслонки
            GPIOA->ODR |=  (1 << 5);
            GPIOA->ODR &= ~(1 << 11);
            delay(1500);
            GPIOA->ODR &= ~(1 << 5);
            GPIOA->ODR |=  (1 << 1);
            break;
        default: break;
    }
}

// Один шаг с переменным полупериодом
static void doStepVar(volatile uint32_t *odr, uint8_t step_pin, uint32_t half_period_us) {
    uint32_t t;
    *odr |=  (1 << step_pin);
    t = getMicros(); while ((getMicros() - t) < half_period_us);
    *odr &= ~(1 << step_pin);
    t = getMicros(); while ((getMicros() - t) < half_period_us);
}

// Профиль: разгон → круиз. Резкая остановка по концевику или по исчерпанию шагов.
// Возвращает кол-во сделанных шагов. es_port=NULL — без концевика.
static uint32_t runStepProfile(volatile uint32_t *odr, uint8_t step_pin,
                               uint32_t max_steps,
                               float speed_min, float speed_max, float accel,
                               GPIO_TypeDef *es_port, uint8_t es_pin) {
    if (max_steps == 0) return 0;

    uint32_t accel_steps = 0;
    float spd = speed_min;
    while (spd < speed_max) {
        spd += accel / spd;
        accel_steps++;
    }
    if (accel_steps > max_steps) accel_steps = max_steps;

    uint32_t done = 0;

    // --- Фаза 1: разгон ---
    spd = speed_min;
    for (uint32_t i = 0; i < accel_steps; i++) {
        if (emergency_stop) return done;
        doStepVar(odr, step_pin, (uint32_t)(1000000.0f / spd));
        done++;
        spd += accel / spd;
        if (spd > speed_max) spd = speed_max;
        if (es_port && !(es_port->IDR & (1 << es_pin))) return done;
    }

    // --- Фаза 2: круиз ---
    uint32_t cruise_hp = (uint32_t)(1000000.0f / speed_max);
    while (done < max_steps) {
        if (emergency_stop) return done;
        doStepVar(odr, step_pin, cruise_hp);
        done++;
        if (es_port && !(es_port->IDR & (1 << es_pin))) return done;
    }

    return done;
}

uint32_t makeSteps(uint8_t params, uint32_t max_steps, GPIO_TypeDef *es_port, uint8_t es_pin) {
    switch (params & 0b11) {
        case 0b00:  // Подъём стола
            GPIOB->ODR |=  (1 << 10);
            return runStepProfile(&GPIOB->ODR, 12, max_steps,
                                  TABLE_SPEED_MIN, TABLE_SPEED_MAX, TABLE_ACCEL,
                                  es_port, es_pin);
        case 0b01:  // Опускание стола
            GPIOB->ODR &= ~(1 << 10);
            return runStepProfile(&GPIOB->ODR, 12, max_steps,
                                  TABLE_SPEED_MIN, TABLE_SPEED_MAX, TABLE_ACCEL,
                                  es_port, es_pin);
        case 0b10:  // Разжать лапки
            GPIOB->ODR |=  (1 << 14);
            return runStepProfile(&GPIOB->ODR, 15, max_steps,
                                  GRIPPER_SPEED_MIN, GRIPPER_SPEED_MAX, GRIPPER_ACCEL,
                                  es_port, es_pin);
        case 0b11:  // Сжать лапки
            GPIOB->ODR &= ~(1 << 14);
            return runStepProfile(&GPIOB->ODR, 15, max_steps,
                                  GRIPPER_SPEED_MIN, GRIPPER_SPEED_MAX, GRIPPER_ACCEL,
                                  es_port, es_pin);
        default: return 0;
    }
}

// ============================================================
// Обработка принятого сообщения
// ============================================================

void read_message(void) {
		uint8_t debug_msg[MAX_MESSAGE_LENGTH];
		for (int i = 0; i < MAX_MESSAGE_LENGTH; i++) debug_msg[i] = msg_rx[start_msg_index][i];
    uint8_t len     = msg_rx[start_msg_index][MESSAGE_LEN];
    uint8_t type    = msg_rx[start_msg_index][MESSAGE_TYPE];
    uint8_t *data   = &msg_rx[start_msg_index][3];          // DATA начинается с байта 3
    uint8_t rx_crc  = msg_rx[start_msg_index][3 + len];     // CRC стоит после DATA

    // --- Проверка CRC ---
    uint8_t calc_crc = calc_checksum(data, type, len);
    if (calc_crc != rx_crc) {
        send_nack_with_error(0);  // 0 = ошибка CRC
        goto cleanup;
    }

    // --- Пакет должен быть от OrangePi (Source бит = 1) ---
    if (!(type & PROTOCOL_SOURCE_msk)) goto cleanup;

    // --- Разбор по Command Type (биты 2..1) ---
    switch ((type & PROTOCOL_TYPE_COMMAND_TYPE_msk) >> 1) {

        // ---- Запрос статуса (00) ----
        case 0b00: {
            uint8_t system_part = (type & PROTOCOL_TYPE_SENSOR_TYPE_msk) >> 3;
            switch (system_part) {

                case 0b001: {  // Датчики Холла
                    uint8_t hall = (uint8_t)(
                        (((~GPIOB->IDR) >> 0) & 1) << 0 |  // Крыша открыта
                        (((~GPIOB->IDR) >> 1) & 1) << 1 |  // Крыша закрыта
                        (((~GPIOB->IDR) >> 2) & 1) << 2 |  // Стол поднят
                        (((~GPIOB->IDR) >> 3) & 1) << 3 |  // Стол опущен
                        (((~GPIOB->IDR) >> 4) & 1) << 4 |  // Вентиляция 1 закрыта
                        (((~GPIOB->IDR) >> 5) & 1) << 5 |  // Вентиляция 2 закрыта
                        (((~GPIOB->IDR) >> 7) & 1) << 6    // Лапки сжаты (PB7 → бит 6)
                    );
                    // TYPE ответа: Source=0(STM32), CommandType=01(ответ), SystemPart=001
                    // → 0b00001010
                    uint8_t resp[1] = { hall };
                    send_packet(0b00001010, resp, 1);
                    break;
                }

                case 0b010: {  // Напряжение АКБ
                    uint16_t raw = ADC_ReadRaw();
                    uint8_t resp[2] = { (uint8_t)((raw >> 8) & 0xFF),
                                        (uint8_t)(raw & 0xFF) };
                    // TYPE: Source=0, CommandType=01, SystemPart=010 → 0b00010010
                    send_packet(0b00010010, resp, 2);
                    break;
                }

                case 0b011: {  // DHT22
                    uint8_t dht[5] = {0,0,0,0,0};
                    if (DHT22_Read(dht)) {
                        // TYPE: Source=0, CommandType=01, SystemPart=011 → 0b00011010
                        send_packet(0b00011010, dht, 5);
                    } else {
                        // Ошибка CRC датчика → error_code=4
                        send_nack_with_error(4);
                    }
                    break;
                }

                default:
                    send_nack_with_error(3);  // Неизвестный system_part
                    break;
            }
            break;
        }

        // ---- Команда действия (10) ----
        case 0b10: {
            //if (len < 1) { send_nack_with_error(3); break; }
            uint8_t cmd = data[0];
            bool ok = true;

            switch (cmd) {
                case 1:  GPIOA->ODR &= ~0b1;      break;  // Старт вибромотора
                case 2:  GPIOA->ODR |=  0b1;      break;  // Стоп вибромотора
                case 3:  GPIOA->ODR &= ~(1<<2); isClimatic = 0; break;  // Нагрев воздуха вкл
                case 4:  GPIOA->ODR |=  (1<<2); isClimatic = 0; break;  // Нагрев воздуха выкл
                case 5:  GPIOC->ODR &= ~(1<<13);   break;  // Нагрев крыши вкл
                case 6:  GPIOC->ODR |=  (1<<13);   break;  // Нагрев крыши выкл
                case 7:  GPIOA->ODR &= ~(1<<3);    break;  // LED вкл
                case 8:  GPIOA->ODR |=  (1<<3);    break;  // LED выкл
                case 9:  // Открыть заслонки
                    GPIOA->ODR |=  (1<<5);
                    GPIOA->ODR &= ~(1<<11);
                    delay(1500);
                    GPIOA->ODR &= ~(1<<5);
                    break;
                case 10: {  // Закрыть заслонки
                    GPIOA->ODR |=  (1<<11);
                    GPIOA->ODR &= ~(1<<5);
                    uint32_t cnt = 0;
                    while (cnt <= AIR_SHUTTERS_CLOSE_TIMEOUT
                           && !(GPIOB->IDR & (1<<4))
                           && !(GPIOB->IDR & (1<<5))
                           && !emergency_stop) cnt++;
                    GPIOA->ODR &= ~(1<<11);
                    break;
                }
                case 11: GPIOA->ODR &= ~(1<<4); break;  // Вентиляторы вкл
                case 12: GPIOA->ODR |=  (1<<4); break;  // Вентиляторы выкл
                case 13: {  // Поднять стол
                    GPIOB->ODR &= ~(1 << 9);
                    uint32_t done13 = makeSteps(0b00, STEP_MOTOR_TABLE_UPPER_TIMEOUT, GPIOB, 2);
                    if (done13 >= STEP_MOTOR_TABLE_UPPER_TIMEOUT) {
                        uint8_t err[1] = { 3 };
                        send_packet(0b00001110, err, 1);
                        ok = false;
                    }
                    break;
                }
                case 14: {  // Опустить стол
                    uint32_t done14 = makeSteps(0b01, STEP_MOTOR_TABLE_LOWER_TIMEOUT, GPIOB, 3);
                    GPIOB->ODR |= (1 << 9);
                    if (done14 >= STEP_MOTOR_TABLE_LOWER_TIMEOUT) {
                        uint8_t err[1] = { 4 };
                        send_packet(0b00001110, err, 1);
                        ok = false;
                    }
                    break;
                }
                case 15: {  // Открыть лапки
                    GPIOB->ODR &= ~(1 << 13);
                    makeSteps(0b10, STEP_MOTOR_DRONE_OPEN_TIMEOUT, GPIOB, 8);
                    break;
                }
                case 16: {  // Закрыть лапки
                    uint32_t done16 = makeSteps(0b11, STEP_MOTOR_DRONE_HOLD_TIMEOUT, GPIOB, 7);
                    GPIOB->ODR |= (1 << 13);
                    if (done16 >= STEP_MOTOR_DRONE_HOLD_TIMEOUT) {
                        uint8_t err[1] = { 7 };
                        send_packet(0b00001110, err, 1);
                        ok = false;
                    }
                    break;
                }
                case 17: {  // Открыть крышу
                    PWM_SetPulseWidth(PWM_MIN);
										delay(500);
										PWM_SetPulseWidth(PWM_MIN);
                    uint32_t t17 = getMicros();
                    bool done17 = false;
                    while ((getMicros() - t17) < (uint32_t)ROOF_SHUTTERS_OPEN_TIMEOUT * 1000
                           && !emergency_stop) {
                        if (!(GPIOB->IDR & (1 << 0))) { done17 = true; break; }
                    }
                    PWM_SetPulseWidth(PWM_CENTER);  // Стоп ESC
                    if (!done17) {
                        uint8_t err[1] = { 1 };
                        send_packet(0b00001110, err, 1);
                        ok = false;
                    }
                    break;
                }
                case 18: {  // Закрыть крышу
                    PWM_SetPulseWidth(PWM_MAX);
									  delay(500);
									  PWM_SetPulseWidth(PWM_MAX);
                    uint32_t t18 = getMicros();
                    bool done18 = false;
                    while ((getMicros() - t18) < (uint32_t)ROOF_SHUTTERS_CLOSE_TIMEOUT * 1000
                           && !emergency_stop) {
                        if (!(GPIOB->IDR & (1 << 1))) { done18 = true; break; }
                    }
                    PWM_SetPulseWidth(PWM_CENTER);  // Стоп ESC
                    if (!done18) {
                        uint8_t err[1] = { 2 };
                        send_packet(0b00001110, err, 1);
                        ok = false;
                    }
                    break;
                }
                case 19: isClimatic = 1; break;  // Включить климат-контроль
                case 20: isClimatic = 0; break;  // Выключить климат-контроль
                case 21: {  // Поднять стол на порцию (без концевика)
                    GPIOB->ODR |=  (1 << 9);
                    makeSteps(0b00, TABLE_NUDGE_STEPS, NULL, 0);
                    break;
                }
                case 22: {  // Параллельное открытие крыши + подъём стола
                    PWM_SetPulseWidth(PWM_MAX);
                    GPIOB->ODR &= ~(1 << 9);
                    uint32_t done22 = makeSteps(0b00, STEP_MOTOR_TABLE_UPPER_TIMEOUT, GPIOB, 2);
                    PWM_SetPulseWidth(PWM_CENTER);
                    if (done22 >= STEP_MOTOR_TABLE_UPPER_TIMEOUT) {
                        uint8_t err[1] = { 3 };
                        send_packet(0b00001110, err, 1);
                        ok = false;
                    }
                    break;
                }
                case 25: {  // Аварийная пауза — ждём cmd=26 для возобновления
                    emergency_stop = true;
                    send_ack();
                    while (emergency_stop) {
                        if (last_msg_index != start_msg_index) {
                            uint8_t t2   = msg_rx[start_msg_index][MESSAGE_TYPE];
                            uint8_t cmd2 = msg_rx[start_msg_index][3];
                            for (int i = 0; i < MAX_MESSAGE_LENGTH; i++) msg_rx[start_msg_index][i] = 0;
                            start_msg_index++;
                            if (start_msg_index >= BUFFER_LENGTH) start_msg_index = 0;
                            if (((t2 & PROTOCOL_TYPE_COMMAND_TYPE_msk) >> 1) == 0b10 && cmd2 == 26) {
                                emergency_stop = false;
                                send_ack();
                            }
                        }
                    }
                    ok = false;  // ack уже отправлен внутри
                    break;
                }
                default:
                    send_nack_with_error(3);
                    ok = false;
                    break;
            }

            if (ok) send_ack();
            break;
        }

        default:
            send_nack_with_error(3);
            break;
    }

cleanup:
    // Очистить слот буфера и сдвинуть индекс
    for (int i = 0; i < MAX_MESSAGE_LENGTH; i++) msg_rx[start_msg_index][i] = 0;
    start_msg_index++;
    if (start_msg_index >= BUFFER_LENGTH) start_msg_index = 0;
}
void loopback_message(void) {
	
    uint8_t len  = msg_rx[start_msg_index][MESSAGE_LEN];
    uint8_t type = msg_rx[start_msg_index][MESSAGE_TYPE];
    uint8_t *data = &msg_rx[start_msg_index][3];

    // Проверка CRC — как в основном проекте
    //uint8_t rx_crc   = msg_rx[start_msg_index][3 + len];
    //uint8_t calc_crc = calc_checksum(data, type, len);

    //if (calc_crc != rx_crc) {
    //    send_nack_with_error(0);  // 0 = ошибка CRC
    //    goto cleanup;
    //}

    // Эхо: отправляем обратно тот же тип и данные
    send_packet(type, data, len);

/*cleanup:
    for (int i = 0; i < MAX_MESSAGE_LENGTH; i++)
        msg_rx[start_msg_index][i] = 0;ПРИВЕТ КОЗЕЛ ЬЛЯТЬ  ПИДОР
    start_msg_index++;
    if (start_msg_index >= BUFFER_LENGTH) start_msg_index = 0;
*/}

// ============================================================
// main
// ============================================================

int main(void) {
    ClockInit();
    GPIO_init();
		GPIOA->ODR |= (0b1);    //Вибромотор
		GPIOC->ODR |= (0b1<<13);
		GPIOA->ODR |= (0b1<<2);
		GPIOA->ODR |= (0b1<<3);
		GPIOA->ODR |= (0b1<<4);
    LedBlink_Init();
    USART1_Init(115200);
    PWM_Init();
		PWM_Enable();
    ADC_Init();
    DHT22_Init();
		MicroTimer_Init();
			
			
		//Калибровка ESC
		PWM_SetPulseWidth(PWM_MAX); //Полный газ
		delay(4000); //Запомнили
		PWM_SetPulseWidth(PWM_MIN); //Полный тормоз
		delay(2000); //Запомнили
		PWM_SetPulseWidth(PWM_CENTER); //Переключили на нейтраль чтобы не мучать
		delay(2000);
		//send_ack();
		
		GPIOB->ODR &= ~(0b1<<9);
		




    while (true) {
			//PWM_SetPulseWidth(PWM_MAX);
        // --- Обработка принятых сообщений ---
        if (last_msg_index != start_msg_index) {
					read_message();
				}

        // --- Межбайтовый таймаут: завершить незаконченный пакет ---
        if (rx_in_progress) {
            uint32_t now = getMicros();  // Нужна функция getMicros() в rcc
            if ((now - last_byte_tick) >= INTER_BYTE_TIMEOUT_US) {
                // Таймаут истёк — считаем пакет завершённым (если хоть что-то есть)
                rx_in_progress = 0;
                if (msg_byte_index > 0) {
                    last_msg_index++;
                    if (last_msg_index >= BUFFER_LENGTH) last_msg_index = 0;
                    msg_byte_index = 0;
                }
            }
        }
				
        // --- Климат-контроль ---
				
        if (isClimatic) {
            uint8_t dht[5] = {0,0,0,0,0};
            float temp     = DHT22_GetTemperature(dht);
            float humidity = DHT22_GetHumidity(dht);

            if      (temp <= COOLER_MIN_TEMPERATURE) Airing_control(0);
            else if (temp >= COOLER_MAX_TEMPERATURE) Airing_control(1);

            if      (temp <= HEATER_MIN_TEMPERATURE) GPIOA->ODR &= ~(1<<2);
            else if (temp >= HEATER_MAX_TEMPERATURE) GPIOA->ODR |=  (1<<2);

            if (humidity > 90.0f) {
                Airing_control(1);
                delay(25000);
                Airing_control(0);
            }
        }
				
    }
}

// ============================================================
// USART1 IRQ — приём байт с межбайтовым таймаутом
// ============================================================

void TIM4_IRQHandler(void) {
    if (TIM4->SR & TIM_SR_UIF) {
        TIM4->SR &= ~TIM_SR_UIF;
        GPIOC->ODR ^= (1 << 0);
    }
}

void USART1_IRQHandler(void) {
    if (!(USART1->SR & USART_SR_RXNE)) return;

    uint8_t byte = USART1->DR;  // Чтение сбрасывает флаг RXNE

    last_byte_tick = getMicros();

    // Начало нового пакета
    if (byte == BYTE_START) {
        msg_byte_index = 0;
        rx_in_progress = 1;
        msg_rx[last_msg_index][msg_byte_index++] = byte;
        return;
    }

    // Если пакет не начат — игнорируем
    if (!rx_in_progress) return;

    // Защита от переполнения буфера сообщения
    if (msg_byte_index >= MAX_MESSAGE_LENGTH) {
        // Ошибка — пакет слишком длинный
        rx_in_progress = 0;
        msg_byte_index = 0;
        // Шлём ошибку асинхронно нельзя из IRQ — ставим флаг или просто сбрасываем
        return;
    }

    msg_rx[last_msg_index][msg_byte_index++] = byte;

    // Проверяем: знаем ли мы уже LEN?
    if (msg_byte_index > 2) {
        uint8_t declared_len = msg_rx[last_msg_index][MESSAGE_LEN];

        // Защита: DATA не может быть длиннее MAX_DATA_LEN
        if (declared_len > MAX_DATA_LEN) {
            rx_in_progress = 0;
            msg_byte_index = 0;
            // Отправить ошибку из IRQ нельзя напрямую — пометим для main
            // Для MVP: просто сбрасываем, main пришлёт nack при следующем чтении
            return;
        }

        // Полный пакет: BYTE_START(1) + TYPE(1) + LEN(1) + DATA(len) + CRC(1) + BYTE_END(1)
        uint8_t expected_total = 3 + declared_len + 2;

        bool packet_done = false;

        // Условие 1: получили BYTE_END
        if (byte == BYTE_END) packet_done = true;

        // Условие 2: набрали ровно нужное количество байт
        //if (msg_byte_index >= expected_total) packet_done = true;

        if (packet_done) {
            rx_in_progress = 0;
            msg_byte_index = 0;
            // Если это action + cmd=25 — ставим флаг немедленно, не дожидаясь main loop
            uint8_t t_ = msg_rx[last_msg_index][MESSAGE_TYPE];
            if (((t_ & PROTOCOL_TYPE_COMMAND_TYPE_msk) >> 1) == 0b10
                && msg_rx[last_msg_index][3] == 25) {
                emergency_stop = true;
            }
            last_msg_index++;
            if (last_msg_index >= BUFFER_LENGTH) last_msg_index = 0;
        }
    }
}


