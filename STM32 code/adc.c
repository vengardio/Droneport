#include "adc.h"
#include "stm32f401xc.h"

// ─── Инициализация ADC1 на PA1 (делитель напряжения АКБ) ───
void ADC_Init(void) {
    // ─── 1. Тактирование ───
    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN;   // GPIOA
    RCC->APB2ENR |= RCC_APB2ENR_ADC1EN;     // ADC1 (на APB2)

    // ─── 2. PA1 → аналоговый режим (MODER = 0b11) ───
    GPIOA->MODER |= GPIO_MODER_MODER1;

    // ─── 3. Настройка ADC1 ───
    ADC1->CR2 &= ~ADC_CR2_ADON;             // Выключить ADC для настройки

    // Разрешение: 12 бит (RES = 00)
    ADC1->CR1 &= ~ADC_CR1_RES;

    // Время выборки канала 1: 84 цикла (SMP1 = 0b100)
    // Делитель 10к/1к = ~910 Ом импеданс → нужно >= 84 циклов
    ADC1->SMPR2 &= ~ADC_SMPR2_SMP1;
    ADC1->SMPR2 |= ADC_SMPR2_SMP1_2;        // 100 = 84 цикла

    // Канал: Channel 1 (PA1 = ADC1_IN1)
    ADC1->SQR3 &= ~ADC_SQR3_SQ1;
    ADC1->SQR3 |= (1 << 0);                 // SQ1 = канал 1

    // Количество преобразований: 1
    ADC1->SQR1 &= ~ADC_SQR1_L;              // L = 0 → 1 преобразование

    // ─── 4. Включение ADC ───
    // STM32F401 не имеет автокалибровки ADC (это фича F1/F3/L4)
    ADC1->CR2 |= ADC_CR2_ADON;
    for (volatile int i = 0; i < 1000; i++); // Ждём стабилизации (~2 мкс)
}

// ─── Чтение сырого значения (0-4095) ───
uint16_t ADC_ReadRaw(void) {
    // Запуск преобразования
    ADC1->CR2 |= ADC_CR2_SWSTART;
    
    // Ждём завершения (флаг EOC)
    while (!(ADC1->SR & ADC_SR_EOC));
    
    // Читаем результат (12 бит)
    return (uint16_t)(ADC1->DR & 0x0FFF);
}
