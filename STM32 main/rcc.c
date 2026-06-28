#include "rcc.h"

/*
 * ClockInit() — настройка тактирования на 84 МГц.
 *
 * Стратегия:
 *   1. Пробуем HSE (8 МГц внешний кварц)
 *   2. Если HSE не завёлся — fallback на HSI (16 МГц внутренний)
 *   3. В обоих случаях PLL даёт одинаковый результат:
 *
 *      HSE: 8 МГц / 4 = 2 МГц * 168 = 336 МГц / 4 = 84 МГц
 *      HSI: 16 МГц / 8 = 2 МГц * 168 = 336 МГц / 4 = 84 МГц
 *
 * Итоговые частоты (всегда одинаковые):
 *   SYSCLK = 84 МГц
 *   AHB    = 84 МГц
 *   APB2   = 84 МГц  (USART1 тактируется отсюда)
 *   APB1   = 42 МГц  (TIM2, I2C, SPI2 тактируются отсюда)
 *
 * Возвращает:
 *   0 — работаем от HSE + PLL
 *   1 — HSE не завёлся, работаем от HSI + PLL (частоты те же)
 */
int ClockInit(void) {
    __IO int StartUpCounter;
    uint32_t pllm;
    int result = 0;

    // ========================
    // 1. Пробуем запустить HSE
    // ========================
    RCC->CR |= RCC_CR_HSEON;

    for (StartUpCounter = 0; StartUpCounter < 0x1000; StartUpCounter++) {
        if (RCC->CR & RCC_CR_HSERDY)
            break;
    }

    if (RCC->CR & RCC_CR_HSERDY) {
        // HSE завёлся: 8 МГц / 4 = 2 МГц на входе VCO
        pllm = 4;
        RCC->PLLCFGR |= RCC_PLLCFGR_PLLSRC_HSE;
        result = 0;
    } else {
        // HSE не завёлся — выключаем, используем HSI
        RCC->CR &= ~RCC_CR_HSEON;
        // HSI включён по умолчанию, убеждаемся
        RCC->CR |= RCC_CR_HSION;
        while (!(RCC->CR & RCC_CR_HSIRDY));
        // HSI: 16 МГц / 8 = 2 МГц на входе VCO
        pllm = 8;
        RCC->PLLCFGR &= ~RCC_PLLCFGR_PLLSRC;  // Источник = HSI
        result = 1;
    }

    // ========================
    // 2. Настройка PLL
    // ========================
    // VCO input = 2 МГц (в обоих случаях)
    // VCO output = 2 * 168 = 336 МГц
    // SYSCLK = 336 / 4 = 84 МГц
    // PLLQ = 7 → USB = 336 / 7 = 48 МГц (на всякий случай)

    RCC->PLLCFGR &= ~RCC_PLLCFGR_PLLM;
    RCC->PLLCFGR |= pllm;

    RCC->PLLCFGR &= ~RCC_PLLCFGR_PLLN;
    RCC->PLLCFGR |= 168 << 6;

    RCC->PLLCFGR &= ~RCC_PLLCFGR_PLLP;
    RCC->PLLCFGR |= 1 << 16;               // PLLP = 4 (значение 01 в битах)

    RCC->PLLCFGR &= ~RCC_PLLCFGR_PLLQ;
    RCC->PLLCFGR |= 7 << 24;

    // Запуск PLL
    RCC->CR |= RCC_CR_PLLON;
    while (!(RCC->CR & RCC_CR_PLLRDY));

    // ========================
    // 3. Flash, делители шин, переключение на PLL
    // ========================
    // 2 wait states для 84 МГц
    FLASH->ACR &= ~FLASH_ACR_LATENCY;
    FLASH->ACR |= FLASH_ACR_LATENCY_2WS;

    RCC->CFGR &= ~RCC_CFGR_HPRE;          // AHB  = SYSCLK     = 84 МГц
    RCC->CFGR &= ~RCC_CFGR_PPRE1;
    RCC->CFGR |= RCC_CFGR_PPRE1_2;         // APB1 = SYSCLK / 2 = 42 МГц
    RCC->CFGR &= ~RCC_CFGR_PPRE2;          // APB2 = SYSCLK     = 84 МГц

    // Переключение на PLL
    RCC->CFGR &= ~RCC_CFGR_SW;
    RCC->CFGR |= RCC_CFGR_SW_PLL;
    while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_PLL);

    return result;
}

void delayMicroseconds(uint32_t microsec) {
    volatile uint32_t loops = microsec * LOOPS_PER_US;
    while (loops--);
}

void delay(uint32_t ms) {
    volatile uint32_t loops = ms * LOOPS_PER_MS;
    while (loops--);
}

/*
 * getMicros() — счётчик микросекунд на базе TIM2.
 *
 * TIM2 на STM32F401:
 *   - тактируется от APB1 = 42 МГц
 *   - таймер умножается на 2 если APB1 prescaler != 1 → 84 МГц на входе TIM2
 *   - Prescaler = 83 → счётчик тикает на 84 МГц / (83+1) = 1 МГц = 1 мкс/тик
 *   - ARR = 0xFFFFFFFF (32-битный режим, переполнение раз в ~71 мин)
 *
 * ВАЖНО: вызвать MicroTimer_Init() один раз в main() до любого использования.
 */

void MicroTimer_Init(void) {
    // Включить тактирование TIM2
    RCC->APB1ENR |= RCC_APB1ENR_TIM2EN;

    // Сбросить таймер
    TIM2->CR1  = 0;
    TIM2->CNT  = 0;

    // Prescaler: 84 МГц / (83+1) = 1 МГц → 1 тик = 1 мкс
    // Если APB1 = 42 МГц и APBx prescaler != 1, то TIM clock = 42*2 = 84 МГц
    TIM2->PSC  = 83;

    // Auto-reload: максимум для 32-битного счётчика
    TIM2->ARR  = 0xFFFFFFFF;

    // Сгенерировать Update Event чтобы PSC и ARR применились немедленно
    TIM2->EGR  = TIM_EGR_UG;

    // Запустить таймер
    TIM2->CR1  = TIM_CR1_CEN;
}

uint32_t getMicros(void) {
    return TIM2->CNT;
}

/*
 * Блокирующая задержка в микросекундах.
 * Максимум ~71 минута (предел 32-битного счётчика на 1 МГц).
 * Корректно обрабатывает переполнение счётчика.
 */