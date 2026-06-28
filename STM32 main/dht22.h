#ifndef DHT22_H
#define DHT22_H

#include <stdint.h>
#include <stdbool.h>
#include "stm32f401xc.h"

// Инициализация (вызвать 1 раз в начале программы)
void DHT22_Init(void);

// Чтение данных с датчика
// Возвращает: true = успех, false = ошибка
// data[5] всегда заполняется:
//   - при успехе: данные датчика
//   - при ошибке: все 5 байт = 0
bool DHT22_Read(uint8_t data[5]);

// Конвертация сырых данных в удобные величины
float DHT22_GetHumidity(uint8_t data[5]);
float DHT22_GetTemperature(uint8_t data[5]);

#endif