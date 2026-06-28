#include "dht22.h"
#include "rcc.h"

// ─── Константы ───
#define TIMEOUT_US       200       // Таймаут ожидания любой фазы (мкс)
#define BIT_THRESHOLD_US 20        // Порог: бит '0' ≈ 11 тиков, бит '1' ≈ 28 тиков

// ─── Вспомогательные функции для работы с PA7 ───

static inline void PA7_Output_Low(void) {
    GPIOA->MODER &= ~GPIO_MODER_MODER7;
    GPIOA->MODER |=  GPIO_MODER_MODER7_0;
    GPIOA->ODR &= ~(1 << 7);
}

static inline void PA7_Output_High(void) {
    GPIOA->MODER &= ~GPIO_MODER_MODER7;
    GPIOA->MODER |=  GPIO_MODER_MODER7_0;
    GPIOA->ODR   |=  (1 << 7);
}

static inline void PA7_Input_PullUp(void) {
    GPIOA->MODER &= ~GPIO_MODER_MODER7;
    GPIOA->PUPDR &= ~GPIO_PUPDR_PUPDR7;
    GPIOA->PUPDR |=  GPIO_PUPDR_PUPDR7_0;
}

static inline uint8_t PA7_Read(void) {
    return (GPIOA->IDR & (1 << 7)) ? 1 : 0;
}

// ─── Ожидание состояния пина с таймаутом (через TIM2) ───
// Ждёт пока пин == level, возвращает false если таймаут
static inline bool WaitForLevel(uint8_t level, uint32_t timeout_us) {
    uint32_t start = getMicros();
    while (PA7_Read() == level) {
        if ((getMicros() - start) >= timeout_us) return false;
    }
    return true;
}

// ─── Вспомогательная функция: очистка буфера нулями ───
static inline void ClearData(uint8_t data[5]) {
    data[0] = 0;
    data[1] = 0;
    data[2] = 0;
    data[3] = 0;
    data[4] = 0;
}

// ─── Инициализация ───
void DHT22_Init(void) {
    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN;
    PA7_Input_PullUp();
}

// ─── Чтение данных с DHT22 ───
bool DHT22_Read(uint8_t data[5]) {
    uint8_t byteIndex = 0, bitIndex = 0;
    uint8_t i;
    uint32_t start;

    // ─── СРАЗУ очищаем буфер (на случай ошибки) ───
    ClearData(data);

    // ─── 1. Стартовый сигнал от МК ───
    PA7_Output_Low();
    start = getMicros();
    while ((getMicros() - start) < 2000);  // 2 мс LOW

    PA7_Output_High();
    start = getMicros();
    while ((getMicros() - start) < 30);    // 30 мкс HIGH

    PA7_Input_PullUp();

    // ─── 2. Ждём ответа датчика ───
    // Ждём пока линия упадёт в LOW (датчик тянет ~80 мкс)
    if (!WaitForLevel(1, TIMEOUT_US)) { data[0] = 0xE1; return false; }

    // Ждём пока линия поднимется в HIGH (~80 мкс)
    if (!WaitForLevel(0, TIMEOUT_US)) { data[0] = 0xE2; return false; }

    // Ждём пока HIGH ответа закончится — после этого пойдут биты
    if (!WaitForLevel(1, TIMEOUT_US)) { data[0] = 0xE3; return false; }

    // ─── 3. Чтение 40 бит данных ───
    for (i = 0; i < 40; i++) {
        // Ждём окончания LOW-фазы (~50 мкс)
        if (!WaitForLevel(0, TIMEOUT_US)) { data[0] = 0xE4; data[1] = i; return false; }

        // Засекаем начало HIGH-фазы
        start = getMicros();

        // Ждём окончания HIGH-фазы
        if (!WaitForLevel(1, TIMEOUT_US)) { data[0] = 0xE5; data[1] = i; return false; }

        // Определяем бит по длительности HIGH
        if ((getMicros() - start) > BIT_THRESHOLD_US) {
            data[byteIndex] |= (1 << (7 - bitIndex));
        }

        bitIndex++;
        if (bitIndex == 8) {
            bitIndex = 0;
            byteIndex++;
        }
    }

    // ─── 4. Проверка CRC ───
    uint8_t crc = (data[0] + data[1] + data[2] + data[3]) & 0xFF;
    if (data[4] != crc) {
        ClearData(data);
        return false;
    }

    return true;
}

// ─── Конвертация в удобные величины ───
float DHT22_GetHumidity(uint8_t data[5]) {
    if (data[0] == 0 && data[1] == 0) return 0.0f;
    return ((float)data[0] * 256.0f + (float)data[1]) / 10.0f;
}

float DHT22_GetTemperature(uint8_t data[5]) {
    if (data[2] == 0 && data[3] == 0) return 0.0f;
    float temp = ((float)(data[2] & 0x7F) * 256.0f + (float)data[3]) / 10.0f;
    if (data[2] & 0x80) {
        temp = -temp;
    }
    return temp;
}
