#include "pwm.h"
#include "stm32f401xc.h"

// ─── Константы для ESC ───
#define ESC_MIN_PULSE  1000  // Мин. импульс (мкс) - мотор стоп
#define ESC_MAX_PULSE  2000  // Макс. импульс (мкс) - полный газ
#define ESC_NEUTRAL    1500  // Нейтраль (мкс)
#define PWM_PERIOD_US  20000 // Период 20 мс (50 Гц)

// ─── Настройки таймера (TIM3 clock = 84 МГц: APB1=42МГц × 2) ───
// Prescaler = 83 → 84 МГц / 84 = 1 МГц (1 тик = 1 мкс)
// ARR = 19999 → 20000 тиков = 20000 мкс = 20 мс (50 Гц)
#define TIM_PRESCALER  41   // 42 МГц / 42 = 1 МГц → 50 Гц (факт)
#define TIM_ARR        19999

void PWM_Init(void) {
    // ─── 1. Тактирование ───
    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN;   // GPIOA
    RCC->APB1ENR |= RCC_APB1ENR_TIM3EN;    // TIM3
    
    // ─── 2. Настройка PA6 (TIM3_CH1, AF2) ───
    GPIOA->MODER &= ~GPIO_MODER_MODER6;    // Сброс режима
    GPIOA->MODER |= GPIO_MODER_MODER6_1;   // Alternate Function
    GPIOA->OSPEEDR |= GPIO_OSPEEDER_OSPEEDR6; // High speed
    GPIOA->PUPDR &= ~GPIO_PUPDR_PUPDR6;    // Без подтяжки
    GPIOA->AFR[0] &= ~(0xF << 24);    // Очистить старые биты 
		GPIOA->AFR[0] |=  (2 << 24);      // Установить AF2 = TIM3
    
    // ─── 3. Настройка TIM3 ───
    TIM3->CR1 &= ~TIM_CR1_CEN;             // Остановить таймер
    
    TIM3->PSC = TIM_PRESCALER;             // Предделитель (1 МГц)
    TIM3->ARR = TIM_ARR;                   // Период (20 мс)
    
    // Настройка канала 1 (PA6) в режим PWM
    TIM3->CCMR1 &= ~TIM_CCMR1_CC1S;        // CC1 = выход
    TIM3->CCMR1 |= TIM_CCMR1_OC1M_1 | TIM_CCMR1_OC1M_2; // PWM mode 1
    TIM3->CCMR1 |= TIM_CCMR1_OC1PE;        // Предзагрузка включена
    
    TIM3->CCER |= TIM_CCER_CC1E;           // Включить выход на пин
    TIM3->CCER &= ~TIM_CCER_CC1P;          // Полярность: высокий активный
    
    TIM3->EGR |= TIM_EGR_UG;               // Обновить регистры
    TIM3->CR1 |= TIM_CR1_CEN;              // Запустить таймер
    
    // По умолчанию: импульс 1500 мкс (нейтраль)
    PWM_SetPulseWidth(ESC_MAX_PULSE);
}

void PWM_SetPulseWidth(uint16_t microseconds) {
    // Ограничение диапазона
    if (microseconds < ESC_MIN_PULSE) microseconds = ESC_MIN_PULSE;
    if (microseconds > ESC_MAX_PULSE) microseconds = ESC_MAX_PULSE;
    
    // При 1 МГц: 1 мкс = 1 тик таймера
    TIM3->CCR1 = microseconds;
}

void PWM_SetDutyPercent(uint8_t percent) {
    if (percent > 100) percent = 100;
    
    // Конвертация процента в микросекунды (1000-2000 мкс)
    uint16_t pulse = ESC_MIN_PULSE + ((uint32_t)percent * (ESC_MAX_PULSE - ESC_MIN_PULSE)) / 100;
    PWM_SetPulseWidth(pulse);
}

void PWM_Enable(void) {
    TIM3->CR1 |= TIM_CR1_CEN;
}

void PWM_Disable(void) {
    TIM3->CR1 &= ~TIM_CR1_CEN;
}