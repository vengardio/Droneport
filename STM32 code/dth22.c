#include "dht22.h"

// ─── Константы ───
#define LOOPS_PER_US     14        // 14 итераций ≈ 1 мкс при 42 МГц
#define BIT_THRESHOLD    35        // Порог для бита '1': 35 × 1.2 мкс ≈ 42 мкс
#define TIMEOUT_ITER     100       // Таймаут для ожидания сигнала (мкс)

// ─── Простая задержка в микросекундах ───
static inline void delay_us(uint32_t us) {
    volatile uint32_t loops = us * LOOPS_PER_US;
    while (loops--);
}

// ─── Вспомогательные функции для работы с PA7 ───

static inline void PA7_Output_Low(void) {
    GPIOA->MODER &= ~GPIO_MODER_MODER7;
    GPIOA->MODER |=  GPIO_MODER_MODER7_0;
    GPIOA->ODR   &= ~GPIO_ODR_ODR7;
}

static inline void PA7_Output_High(void) {
    GPIOA->MODER &= ~GPIO_MODER_MODER7;
    GPIOA->MODER |=  GPIO_MODER_MODER7_0;
    GPIOA->ODR   |=  GPIO_ODR_ODR7;
}

static inline void PA7_Input_PullUp(void) {
    GPIOA->MODER &= ~GPIO_MODER_MODER7;
    GPIOA->PUPDR &= ~GPIO_PUPDR_PUPDR7;
    GPIOA->PUPDR |=  GPIO_PUPDR_PUPDR7_0;
}

static inline uint8_t PA7_Read(void) {
    return (GPIOA->IDR & GPIO_IDR_IDR7) ? 1 : 0;
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
    uint8_t i, counter;
    
    // ─── СРАЗУ очищаем буфер (на случай ошибки) ───
    ClearData(data);
    
    // ─── 1. Стартовый сигнал от МК ───
    PA7_Output_Low();
    delay_us(2000);
    PA7_Output_High();
    delay_us(40);
    PA7_Input_PullUp();
    
    // ─── 2. Ждём ответа датчика ───
    // Ждём LOW от датчика (~80 мкс)
    for (i = 0; i < TIMEOUT_ITER && PA7_Read(); i++) { 
        delay_us(1); 
    }
    if (i >= TIMEOUT_ITER) {
        ClearData(data);  // На всякий случай ещё раз очищаем
        return false;     // Таймаут — датчик не ответил
    }
    
    // Ждём HIGH от датчика (~80 мкс)
    for (i = 0; i < TIMEOUT_ITER && !PA7_Read(); i++) { 
        delay_us(1); 
    }
    if (i >= TIMEOUT_ITER) {
        ClearData(data);
        return false;     // Таймаут — ошибка
    }
    
    // ─── 3. Чтение 40 бит данных ───
    for (i = 0; i < 40; i++) {
        // Ждём окончания LOW-фазы
        counter = 0;
        while (PA7_Read() == 0 && counter < TIMEOUT_ITER) {
            counter++;
            delay_us(1);
        }
        if (counter >= TIMEOUT_ITER) {
            ClearData(data);
            return false;
        }
        
        // Измеряем длительность HIGH-фазы
        counter = 0;
        while (PA7_Read() == 1 && counter < TIMEOUT_ITER) {
            counter++;
            delay_us(1);
        }
        if (counter >= TIMEOUT_ITER) {
            ClearData(data);
            return false;
        }
        
        // Определяем значение бита
        if (counter > BIT_THRESHOLD) {
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
        ClearData(data);  // CRC не совпал — очищаем все байты!
        return false;
    }
    
    return true;  // Успех: data заполнен корректными данными
}

// ─── Конвертация в удобные величины ───
float DHT22_GetHumidity(uint8_t data[5]) {
    if (data[0] == 0 && data[1] == 0) return 0.0f;  // Защита от нулей
    return ((float)data[0] * 256.0f + (float)data[1]) / 10.0f;
}

float DHT22_GetTemperature(uint8_t data[5]) {
    if (data[2] == 0 && data[3] == 0) return 0.0f;  // Защита от нулей
    float temp = ((float)(data[2] & 0x7F) * 256.0f + (float)data[3]) / 10.0f;
    if (data[2] & 0x80) {
        temp = -temp;
    }
    return temp;
}